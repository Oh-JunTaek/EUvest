"""독립 신규 DB의 상태와 intent 저장. 주문 전송 기능은 없다."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sysconfig
from contextlib import closing
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError as PydanticValidationError

from invest_agent.domain.contracts import (
    AssetInput,
    DecisionLink,
    EvidenceInput,
    OrderIntentInput,
    RunInput,
    ThesisInput,
    utc_text,
)
from invest_agent.domain.errors import InvalidProposalError, StaleStateError


def _validate_decision(proposal_json: str) -> DecisionLink:
    """버전 관리된 원본 스키마 및 Pydantic 검사. 오류 내용에 입력값을 포함하지 않는다."""
    source_path = Path(__file__).resolve().parents[3] / "schemas" / "decision_proposal.schema.json"
    installed_path = (Path(sysconfig.get_path("data")) / "share" / "invest_agent" / "schemas"
                      / "decision_proposal.schema.json")
    schema_path = source_path if source_path.is_file() else installed_path
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    checker = FormatChecker()
    if "date-time" not in checker.checkers:
        raise RuntimeError("JSON Schema 시간 형식 검사기를 사용할 수 없습니다")
    try:
        proposal = json.loads(proposal_json)
        Draft202012Validator(schema, format_checker=checker).validate(proposal)
        validated = DecisionLink.model_validate(proposal)
        if validated.as_of_utc.utcoffset() != timedelta(0):
            raise InvalidProposalError("판단 시각은 UTC여야 합니다")
        return validated
    except (json.JSONDecodeError, SchemaValidationError, PydanticValidationError):
        raise InvalidProposalError("판단 JSON 계약 검증 실패") from None


def _schema_objects(conn: sqlite3.Connection) -> list[tuple[str, str, str, str]]:
    return conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY type, name"
    ).fetchall()


@lru_cache(maxsize=1)
def _expected_schema_objects() -> tuple[tuple[str, str, str, str], ...]:
    migration_dir = files("invest_agent").joinpath("migrations")
    sql = "\n".join(
        migration_dir.joinpath(name).read_text(encoding="utf-8")
        for name in ("001_init.sql", "002_ai_state.sql")
    )
    with closing(sqlite3.connect(":memory:")) as reference:
        reference.executescript(sql)
        return tuple(_schema_objects(reference))


def _check_contract(conn: sqlite3.Connection) -> None:
    versions = conn.execute("SELECT version FROM schema_version").fetchall()
    if versions != [(1,)]:
        raise sqlite3.DatabaseError("지원하지 않는 계약 DB 버전")
    if tuple(_schema_objects(conn)) != _expected_schema_objects():
        raise sqlite3.DatabaseError("계약 DB의 테이블·인덱스·트리거 정의 불일치")
    if conn.execute("PRAGMA quick_check").fetchone() != ("ok",):
        raise sqlite3.DatabaseError("DB 무결성 검사 실패")
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise sqlite3.IntegrityError("외래키 무결성 검사 실패")
    for query in (
        "SELECT version, created_at, active_thesis_ids_json, hypothesis_digest, last_run_id FROM strategy_state LIMIT 0",
        "SELECT decision_id, proposal_json, state_version, schema_valid FROM decisions LIMIT 0",
        "SELECT intent_id, decision_id, idempotency_key, status FROM order_intents LIMIT 0",
        "SELECT event_id, intent_id, status, created_utc FROM order_events LIMIT 0",
        "SELECT decision_id, failure_code, recorded_utc FROM decision_validation_failures LIMIT 0",
    ):
        conn.execute(query)


def _active_digest(conn: sqlite3.Connection, active_ids: list[str]) -> str:
    if not isinstance(active_ids, list) or any(not isinstance(item, str) or not item.strip() for item in active_ids) or len(set(active_ids)) != len(active_ids):
        raise ValueError("활성 가설 ID가 비어 있거나 중복되었습니다")
    active = []
    for thesis_id in sorted(active_ids):
        row = conn.execute(
            "SELECT thesis_id, version, asset_id, status, premise, invalidation_json, evidence_ids_json, horizon_days "
            "FROM theses WHERE thesis_id = ? ORDER BY version DESC LIMIT 1", (thesis_id,),
        ).fetchone()
        if row is None:
            raise ValueError("존재하지 않는 활성 가설입니다")
        active.append(row)
    return hashlib.sha256(json.dumps(active, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _check_expected_version(value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("상태 버전은 0 이상의 정수여야 합니다")


def _check_evidence(conn: sqlite3.Connection, proposal_json: str, as_of: datetime) -> None:
    proposal = json.loads(proposal_json)
    references = [(evidence_id, None) for evidence_id in proposal["evidence_ids"]]
    for item in proposal["items"]:
        references.extend((evidence_id, item["asset_id"]) for evidence_id in item["evidence_ids"])
    for update in proposal["thesis_updates"]:
        references.extend((evidence_id, update["asset_id"]) for evidence_id in update["evidence_ids"])
    for evidence_id, asset_id in references:
        row = conn.execute(
            "SELECT asset_ids_json, published_at, fetched_at FROM evidence WHERE evidence_id = ?",
            (evidence_id,),
        ).fetchone()
        try:
            if row is None:
                raise ValueError
            assets = json.loads(row[0])
            published = datetime.fromisoformat(row[1])
            fetched = datetime.fromisoformat(row[2])
            if (not isinstance(assets, list) or (asset_id is not None and asset_id not in assets)
                    or published.utcoffset() is None or fetched.utcoffset() is None
                    or published.utcoffset() != timedelta(0) or fetched.utcoffset() != timedelta(0)
                    or published > fetched or published > as_of or fetched > as_of):
                raise ValueError
        except (TypeError, ValueError):
            raise InvalidProposalError("판단의 증거가 없거나 시점·자산이 일치하지 않습니다") from None


def create_contract_db(path: str | Path) -> None:
    """새 DB만 생성한다. 기존 파일은 FileExistsError, DB 오류는 sqlite3.Error."""
    db_path = Path(path)
    fd = os.open(db_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with closing(sqlite3.connect(db_path)) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            migration_dir = files("invest_agent").joinpath("migrations")
            sql = "\n".join(
                migration_dir.joinpath(name).read_text(encoding="utf-8")
                for name in ("001_init.sql", "002_ai_state.sql")
            )
            conn.executescript("BEGIN IMMEDIATE;\n" + sql)
            now = utc_text(datetime.now(UTC))
            conn.execute("INSERT INTO schema_version VALUES (?, ?)", (1, now))
            conn.execute("INSERT INTO strategy_state VALUES (0, ?, '[]', ?, NULL)",
                         (now, _active_digest(conn, [])))
            if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise sqlite3.IntegrityError("외래키 무결성 검사 실패")
            conn.commit()
    except Exception:
        # 실패한 파일은 진단을 위해 보존하고 자동 재사용하지 않는다.
        raise


def ensure_contract_db(path: str | Path) -> None:
    """신규 DB를 준비한다. 기존 DB는 검증만 하고 자동 이행하지 않는다.

    알 수 없는 DB나 버전은 sqlite3.DatabaseError, 파일 오류는 OSError 계열이다.
    """
    db_path = Path(path)
    if not db_path.exists():
        create_contract_db(db_path)
        return
    with closing(sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
        conn.execute("PRAGMA query_only = ON")
        conn.execute("BEGIN")
        _check_contract(conn)


def load_state(path: str | Path) -> tuple[int, list[str], str]:
    """현재 상태를 읽는다. 무결성·참조 오류는 sqlite3.DatabaseError 계열."""
    with closing(sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)) as conn:
        conn.execute("PRAGMA query_only = ON")
        conn.execute("BEGIN")
        _check_contract(conn)
        row = conn.execute(
            "SELECT version, active_thesis_ids_json, hypothesis_digest "
            "FROM strategy_state ORDER BY version DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise sqlite3.DatabaseError("현재 상태가 없습니다")
        try:
            active_ids = json.loads(row[1])
            if not isinstance(active_ids, list) or row[2] != _active_digest(conn, active_ids):
                raise ValueError
        except (TypeError, ValueError):
            raise sqlite3.DatabaseError("현재 가설 상태가 손상되었습니다") from None
        return row[0], active_ids, row[2]


def load_thesis(path: str | Path, thesis_id: str, version: int) -> ThesisInput | None:
    """지정 버전의 가설을 읽는다. 유효하지 않은 데이터는 ValueError 계열."""
    with closing(sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)) as conn:
        conn.execute("PRAGMA query_only = ON")
        conn.execute("BEGIN")
        _check_contract(conn)
        row = conn.execute(
            "SELECT thesis_id, version, asset_id, status, premise, invalidation_json, evidence_ids_json, horizon_days "
            "FROM theses WHERE thesis_id = ? AND version = ?", (thesis_id, version),
        ).fetchone()
        if row is None:
            return None
        return ThesisInput(thesis_id=row[0], version=row[1], asset_id=row[2], status=row[3],
                           premise=row[4], invalidation=json.loads(row[5]), evidence_ids=json.loads(row[6]),
                           horizon_days=row[7])


def load_asset(path: str | Path, asset_id: str) -> AssetInput | None:
    """자산을 읽어 식별자·유형을 재검증한다. 잘못된 데이터는 ValueError 계열."""
    with closing(sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)) as conn:
        conn.execute("PRAGMA query_only = ON")
        conn.execute("BEGIN")
        _check_contract(conn)
        row = conn.execute(
            "SELECT asset_id, market, venue, symbol, type, currency, leveraged, eligibility_status, trading_enabled "
            "FROM assets WHERE asset_id = ?", (asset_id,),
        ).fetchone()
        if row is None:
            return None
        if row[6] not in (0, 1) or row[8] not in (0, 1):
            raise sqlite3.DataError("자산의 불리언 값이 잘못되었습니다")
        return AssetInput(asset_id=row[0], market=row[1], venue=row[2], symbol=row[3], asset_type=row[4],
                          currency=row[5], leveraged=bool(row[6]), eligibility_status=row[7],
                          trading_enabled=bool(row[8]))


def load_evidence(path: str | Path, evidence_id: str) -> EvidenceInput | None:
    """증거를 읽어 시각과 필드를 재검증한다. 잘못된 데이터는 ValueError 계열."""
    with closing(sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)) as conn:
        conn.execute("PRAGMA query_only = ON")
        conn.execute("BEGIN")
        _check_contract(conn)
        row = conn.execute(
            "SELECT evidence_id, asset_ids_json, source_url, published_at, fetched_at, source_hash, publisher, text_excerpt "
            "FROM evidence WHERE evidence_id = ?", (evidence_id,),
        ).fetchone()
        if row is None:
            return None
        return EvidenceInput(evidence_id=row[0], asset_ids=json.loads(row[1]), source_url=row[2],
                             published_at_utc=row[3], retrieved_at_utc=row[4], content_hash=row[5],
                             publisher=row[6], text_excerpt=row[7])


def load_decision(path: str | Path, decision_id: str) -> str | None:
    """검증된 판단 JSON을 읽는다. 잘못된 JSON은 InvalidProposalError."""
    with closing(sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)) as conn:
        conn.execute("PRAGMA query_only = ON")
        conn.execute("BEGIN")
        _check_contract(conn)
        row = conn.execute(
            "SELECT proposal_json, schema_valid, run_id, state_version FROM decisions WHERE decision_id = ?",
            (decision_id,),
        ).fetchone()
        if row is None:
            return None
        proposal = _validate_decision(row[0])
        if row[1] != 1 or proposal.run_id != row[2] or proposal.state_version != row[3]:
            raise InvalidProposalError("판단 기록이 일치하지 않습니다")
        _check_evidence(conn, row[0], proposal.as_of_utc)
        return row[0]


def load_intent(path: str | Path, intent_id: str) -> tuple[OrderIntentInput, str] | None:
    """주문 의도와 저장 상태를 읽는다. 유효하지 않은 데이터는 ValueError 계열."""
    with closing(sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)) as conn:
        conn.execute("PRAGMA query_only = ON")
        conn.execute("BEGIN")
        _check_contract(conn)
        row = conn.execute(
            "SELECT intent_id, decision_id, asset_id, side, qty, limit_price, ccy, mode, idempotency_key, status "
            "FROM order_intents WHERE intent_id = ?", (intent_id,),
        ).fetchone()
        if row is None:
            return None
        return OrderIntentInput(intent_id=row[0], decision_id=row[1], asset_id=row[2], side=row[3],
                                qty=row[4], limit_price=row[5], currency=row[6], mode=row[7],
                                idempotency_key=row[8]), row[9]


def save_asset(path: str | Path, asset: AssetInput, expected_version: int, at: datetime) -> int:
    """자산과 상태를 저장한다. 입력 오류는 ValueError, 충돌은 StaleStateError, DB 오류는 sqlite3.Error."""
    _check_expected_version(expected_version)
    asset = AssetInput.model_validate(asset.model_dump(warnings=False))
    timestamp = utc_text(at)
    with closing(sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=rw", uri=True)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("BEGIN IMMEDIATE")
            _check_contract(conn)
            current = conn.execute(
                "SELECT version, active_thesis_ids_json, hypothesis_digest, last_run_id "
                "FROM strategy_state ORDER BY version DESC LIMIT 1"
            ).fetchone()
            if current is None or current[0] != expected_version:
                raise StaleStateError("상태 버전 충돌")
            conn.execute(
                "INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (asset.asset_id, asset.market, asset.venue, asset.symbol, asset.asset_type,
                 asset.currency, int(asset.leveraged), asset.eligibility_status, int(asset.trading_enabled)),
            )
            version = expected_version + 1
            conn.execute("INSERT INTO strategy_state VALUES (?, ?, ?, ?, ?)",
                         (version, timestamp, current[1], current[2], current[3]))
            conn.commit()
            return version
        except Exception:
            conn.rollback()
            raise


def save_run(path: str | Path, run: RunInput) -> None:
    """실행을 저장한다. 입력 오류는 ValueError, 충돌은 StaleStateError, DB 오류는 sqlite3.Error."""
    run = RunInput.model_validate(run.model_dump(warnings=False))
    timestamp = utc_text(run.started_utc)
    with closing(sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=rw", uri=True)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("BEGIN IMMEDIATE")
            _check_contract(conn)
            current = conn.execute("SELECT MAX(version) FROM strategy_state").fetchone()[0]
            if current != run.state_version:
                raise StaleStateError("상태 버전 충돌")
            conn.execute(
                "INSERT INTO agent_runs (run_id, state_version, mode, provider, model, input_hash, started_utc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run.run_id, run.state_version, run.mode, run.provider, run.model, run.input_hash, timestamp),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def save_evidence(path: str | Path, evidence: EvidenceInput, expected_version: int, at: datetime) -> int:
    """증거와 상태를 저장한다. 입력 오류는 ValueError, 충돌은 StaleStateError, DB 오류는 sqlite3.Error."""
    _check_expected_version(expected_version)
    evidence = EvidenceInput.model_validate(evidence.model_dump(warnings=False))
    timestamp = utc_text(at)
    with closing(sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=rw", uri=True)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("BEGIN IMMEDIATE")
            _check_contract(conn)
            current = conn.execute(
                "SELECT version, active_thesis_ids_json, hypothesis_digest, last_run_id "
                "FROM strategy_state ORDER BY version DESC LIMIT 1"
            ).fetchone()
            if current is None or current[0] != expected_version:
                raise StaleStateError("상태 버전 충돌")
            for asset_id in evidence.asset_ids:
                if conn.execute("SELECT 1 FROM assets WHERE asset_id = ?", (asset_id,)).fetchone() is None:
                    raise ValueError("존재하지 않는 증거 자산입니다")
            conn.execute(
                "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (evidence.evidence_id, json.dumps(evidence.asset_ids), evidence.source_url,
                 utc_text(evidence.published_at_utc), utc_text(evidence.retrieved_at_utc),
                 evidence.content_hash, evidence.publisher, evidence.text_excerpt),
            )
            version = expected_version + 1
            conn.execute("INSERT INTO strategy_state VALUES (?, ?, ?, ?, ?)",
                         (version, timestamp, current[1], current[2], current[3]))
            conn.commit()
            return version
        except Exception:
            conn.rollback()
            raise


def save_thesis(
    path: str | Path,
    thesis: ThesisInput,
    active_ids: list[str],
    expected_version: int,
    at: datetime,
) -> int:
    """가설과 상태를 저장한다. 입력 오류는 ValueError, 충돌은 StaleStateError, DB 오류는 sqlite3.Error."""
    _check_expected_version(expected_version)
    thesis = ThesisInput.model_validate(thesis.model_dump(warnings=False))
    timestamp = utc_text(at)
    with closing(sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=rw", uri=True)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("BEGIN IMMEDIATE")
            _check_contract(conn)
            current = conn.execute(
                "SELECT version, last_run_id FROM strategy_state ORDER BY version DESC LIMIT 1"
            ).fetchone()
            if current is None or current[0] != expected_version:
                raise StaleStateError("상태 버전 충돌")
            prior = conn.execute(
                "SELECT version, asset_id FROM theses WHERE thesis_id = ? ORDER BY version DESC LIMIT 1",
                (thesis.thesis_id,),
            ).fetchone()
            if thesis.version != (prior[0] + 1 if prior else 1) or (prior and prior[1] != thesis.asset_id):
                raise ValueError("가설 버전 또는 자산이 이전 기록과 일치하지 않습니다")
            for evidence_id in thesis.evidence_ids:
                if conn.execute("SELECT 1 FROM evidence WHERE evidence_id = ?", (evidence_id,)).fetchone() is None:
                    raise ValueError("존재하지 않는 증거입니다")
            conn.execute(
                "INSERT INTO theses VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (thesis.thesis_id, thesis.version, thesis.asset_id, thesis.status, thesis.premise,
                 json.dumps(thesis.invalidation, ensure_ascii=False),
                 json.dumps(thesis.evidence_ids, ensure_ascii=False), thesis.horizon_days),
            )
            digest = _active_digest(conn, active_ids)
            version = expected_version + 1
            conn.execute("INSERT INTO strategy_state VALUES (?, ?, ?, ?, ?)",
                         (version, timestamp, json.dumps(sorted(active_ids)), digest, current[1]))
            conn.commit()
            return version
        except Exception:
            conn.rollback()
            raise


def advance_state(
    path: str | Path,
    expected_version: int,
    thesis_ids: list[str],
    digest: str,
    at: datetime,
) -> int:
    """상태를 원자적으로 추가한다. 충돌 시 StaleStateError, DB 오류는 sqlite3.Error."""
    _check_expected_version(expected_version)
    timestamp = utc_text(at)
    with closing(sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=rw", uri=True)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("BEGIN IMMEDIATE")
            _check_contract(conn)
            current = conn.execute(
                "SELECT version, last_run_id FROM strategy_state ORDER BY version DESC LIMIT 1"
            ).fetchone()
            if current is None or current[0] != expected_version:
                raise StaleStateError("상태 버전 충돌")
            if digest != _active_digest(conn, thesis_ids):
                raise ValueError("활성 가설 해시가 현재 가설과 일치하지 않습니다")
            version = expected_version + 1
            conn.execute(
                "INSERT INTO strategy_state VALUES (?, ?, ?, ?, ?)",
                (version, timestamp, json.dumps(sorted(thesis_ids)), digest, current[1]),
            )
            conn.commit()
            return version
        except Exception:
            conn.rollback()
            raise


def save_decision(path: str | Path, decision_id: str, proposal_json: str) -> None:
    """유효한 판단을 현재 상태와 실행에 연결한다.

    잘못된 판단은 ValueError, 오래된 상태는 StaleStateError, DB 오류는 sqlite3.Error.
    무효 판단 원문 없이 실패 코드만 기록한다.
    """
    if not decision_id.strip():
        raise ValueError("판단 식별자는 비어 있을 수 없습니다")
    try:
        proposal = _validate_decision(proposal_json)
    except InvalidProposalError:
        with closing(sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=rw", uri=True)) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN IMMEDIATE")
            _check_contract(conn)
            conn.execute(
                "INSERT OR IGNORE INTO decision_validation_failures VALUES (?, ?, ?)",
                (decision_id, "INVALID_PROPOSAL", utc_text(datetime.now(UTC))),
            )
            conn.commit()
        raise
    evidence_ids = json.loads(proposal_json)["evidence_ids"]
    with closing(sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=rw", uri=True)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("BEGIN IMMEDIATE")
            _check_contract(conn)
            current = conn.execute("SELECT MAX(version) FROM strategy_state").fetchone()[0]
            if current != proposal.state_version:
                raise StaleStateError("상태 버전 충돌")
            run = conn.execute(
                "SELECT state_version FROM agent_runs WHERE run_id = ?", (proposal.run_id,)
            ).fetchone()
            if run != (current,):
                raise ValueError("현재 상태의 실행 기록이 필요합니다")
            try:
                _check_evidence(conn, proposal_json, proposal.as_of_utc)
            except InvalidProposalError:
                conn.execute(
                    "INSERT OR IGNORE INTO decision_validation_failures VALUES (?, ?, ?)",
                    (decision_id, "INVALID_EVIDENCE", utc_text(datetime.now(UTC))),
                )
                conn.commit()
                raise
            conn.execute(
                "INSERT INTO decisions VALUES (?, ?, ?, ?, ?, 1)",
                (decision_id, proposal.run_id, proposal_json, json.dumps(evidence_ids), current),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def save_intent(
    path: str | Path,
    intent: OrderIntentInput,
    expected_version: int,
    event_id: str,
    at: datetime,
) -> None:
    """intent와 최초 감사 이벤트를 원자 저장한다. 위험 검증이나 주문 호출은 수행하지 않는다.

    오래된 상태는 StaleStateError, 유일키·참조 오류는 sqlite3.IntegrityError.
    """
    _check_expected_version(expected_version)
    intent = OrderIntentInput.model_validate(intent.model_dump(warnings=False))
    timestamp = utc_text(at)
    if not event_id.strip():
        raise ValueError("이벤트 식별자는 비어 있을 수 없습니다")
    with closing(sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=rw", uri=True)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("BEGIN IMMEDIATE")
            _check_contract(conn)
            current = conn.execute("SELECT MAX(version) FROM strategy_state").fetchone()[0]
            if current != expected_version:
                raise StaleStateError("상태 버전 충돌")
            decision = conn.execute(
                "SELECT d.state_version, d.schema_valid, r.mode, r.run_id, r.state_version, "
                "d.proposal_json FROM decisions d "
                "JOIN agent_runs r ON r.run_id = d.run_id WHERE d.decision_id = ?",
                (intent.decision_id,),
            ).fetchone()
            if decision is None or decision[:3] != (expected_version, 1, intent.mode):
                raise ValueError("현재 상태·모드의 유효한 판단이 필요합니다")
            proposal = _validate_decision(decision[5])
            _check_evidence(conn, decision[5], proposal.as_of_utc)
            if (decision[4] != expected_version or proposal.state_version != expected_version
                    or proposal.run_id != decision[3] or proposal.action != "TRADE"
                    or proposal.as_of_utc.utcoffset() != timedelta(0)
                    or not any(item.asset_id == intent.asset_id and item.side == intent.side
                               for item in proposal.items)):
                raise ValueError("판단과 주문 intent가 일치하지 않습니다")
            asset = conn.execute(
                "SELECT market, venue, symbol, type, currency FROM assets WHERE asset_id = ?",
                (intent.asset_id,),
            ).fetchone()
            if asset is None or tuple(intent.asset_id.split(":")) != asset[:4] or asset[4] != intent.currency:
                raise ValueError("자산 식별자 또는 통화가 일치하지 않습니다")
            conn.execute(
                "INSERT INTO order_intents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'INTENT_CREATED')",
                (intent.intent_id, intent.decision_id, intent.mode, intent.asset_id,
                 intent.side, str(intent.qty), str(intent.limit_price), intent.currency,
                 intent.idempotency_key),
            )
            conn.execute(
                "INSERT INTO order_events VALUES (?, ?, 'INTENT_CREATED', ?)",
                (event_id, intent.intent_id, timestamp),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
