"""신규 계약 DB 검증. 모든 데이터는 테스트용이다."""

import hashlib
import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from invest_agent.domain.contracts import (
    AssetInput,
    EvidenceInput,
    OrderIntentInput,
    RunInput,
    ThesisInput,
    utc_text,
)
from invest_agent.storage.contract_store import (
    StaleStateError,
    advance_state,
    create_contract_db,
    ensure_contract_db,
    load_asset,
    load_decision,
    load_evidence,
    load_intent,
    load_state,
    load_thesis,
    save_asset,
    save_decision,
    save_evidence,
    save_intent,
    save_run,
    save_thesis,
)

EMPTY_DIGEST = hashlib.sha256(b"[]").hexdigest()


@pytest.fixture
def contract_db(tmp_path):
    path = tmp_path / "new.db"
    create_contract_db(path)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("INSERT INTO assets VALUES ('US:NASDAQ:AAPL:STOCK', 'US', 'NASDAQ', 'AAPL', 'STOCK', 'USD', 0, 'UNVERIFIED', 0)")
        conn.execute("INSERT INTO evidence VALUES ('evidence', ?, 'https://example.test', '2025-01-01T00:00:00+00:00', '2025-01-01T00:00:00+00:00', 'hash', 'fixture', '')", (json.dumps(['US:NASDAQ:AAPL:STOCK']),))
        conn.execute("INSERT INTO agent_runs VALUES ('run', 0, 'OFFLINE_SIM', 'fake', 'fixture', 'hash', NULL, NULL, '2026-01-01T00:00:00+00:00', NULL)")
        proposal = {
            "schema_version": "1.0", "run_id": "run", "state_version": 0,
            "as_of_utc": "2026-01-01T00:00:00Z", "action": "TRADE",
            "items": [{"asset_id": "US:NASDAQ:AAPL:STOCK", "side": "BUY",
                       "target_weight_bps": 100, "rationale": "fixture reason",
                       "evidence_ids": ["evidence"]}],
            "rationale": "fixture reason", "evidence_ids": ["evidence"], "thesis_updates": [],
        }
        conn.execute("INSERT INTO decisions VALUES ('decision', 'run', ?, '[]', 0, 1)",
                     (json.dumps(proposal),))
        conn.commit()
    return path


def make_intent(**overrides):
    values = dict(intent_id="intent", decision_id="decision", asset_id="US:NASDAQ:AAPL:STOCK",
                  side="BUY", qty=Decimal("0.1234567890123456789"), limit_price=Decimal("1.000001"),
                  currency="USD", mode="OFFLINE_SIM", idempotency_key="key")
    values.update(overrides)
    return OrderIntentInput(**values)


def test_existing_db_is_never_overwritten(tmp_path):
    path = tmp_path / "legacy.db"
    path.write_bytes(b"legacy-data")
    with pytest.raises(FileExistsError):
        create_contract_db(path)
    assert path.read_bytes() == b"legacy-data"


def test_corrupt_file_is_rejected_and_preserved(tmp_path):
    path = tmp_path / "damaged.db"
    path.write_bytes(b"invalid sqlite file")
    before = path.read_bytes()
    with pytest.raises(sqlite3.DatabaseError):
        ensure_contract_db(path)
    assert path.read_bytes() == before


def test_ensure_contract_db_creates_new_and_rejects_legacy(tmp_path):
    from invest_agent.storage.schema import init_db

    new_path = tmp_path / "new.db"
    ensure_contract_db(new_path)
    ensure_contract_db(new_path)
    old_path = tmp_path / "legacy.db"
    init_db(old_path)
    before = old_path.read_bytes()
    with pytest.raises(sqlite3.DatabaseError):
        ensure_contract_db(old_path)
    assert old_path.read_bytes() == before


def test_required_tables_and_market_identity(contract_db):
    with closing(sqlite3.connect(contract_db)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"app_config_versions", "assets", "allowlist", "account_snapshots", "quotes",
                "evidence", "theses", "strategy_state", "handoffs", "agent_runs", "decisions",
                "risk_checks", "order_intents", "broker_orders", "order_events", "fills",
                "cashflows", "model_usage", "evaluations", "runtime_locks"} <= tables
        conn.execute("INSERT INTO assets VALUES ('US:ARCA:AAPL:STOCK', 'US', 'ARCA', 'AAPL', 'STOCK', 'USD', 0, 'UNVERIFIED', 0)")
        conn.execute("INSERT INTO assets VALUES ('KRX:KRX:AAPL:STOCK', 'KRX', 'KRX', 'AAPL', 'STOCK', 'KRW', 0, 'UNVERIFIED', 0)")
        assert conn.execute("SELECT COUNT(*) FROM assets WHERE symbol='AAPL'").fetchone() == (3,)
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_identity_decimal_and_utc_validation():
    assert make_intent().qty == Decimal("0.1234567890123456789")
    for value in (1.2, True, "NaN", "-1"):
        with pytest.raises(ValidationError):
            make_intent(qty=value)
    with pytest.raises(ValidationError):
        make_intent(asset_id="US:AAPL")
    with pytest.raises(ValueError):
        utc_text(datetime(2026, 1, 1))
    assert utc_text(datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=9)))) == "2025-12-31T15:00:00+00:00"


def test_two_connections_only_one_can_advance(contract_db):
    def run(_):
        try:
            return advance_state(contract_db, 0, [], EMPTY_DIGEST, datetime.now(UTC))
        except StaleStateError:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sorted(map(str, results)) == ["1", "stale"]
    with closing(sqlite3.connect(contract_db)) as conn:
        assert conn.execute("SELECT version FROM strategy_state ORDER BY version").fetchall() == [(0,), (1,)]


def test_intent_atomic_unique_and_append_only(contract_db):
    now = datetime.now(UTC)
    save_intent(contract_db, make_intent(), 0, "event", now)
    with pytest.raises(sqlite3.IntegrityError):
        save_intent(contract_db, make_intent(intent_id="second"), 0, "second-event", now)
    with pytest.raises(sqlite3.IntegrityError):
        save_intent(contract_db, make_intent(intent_id="third", idempotency_key="other"), 0, "event", now)
    with closing(sqlite3.connect(contract_db)) as conn:
        assert conn.execute("SELECT intent_id, qty, limit_price FROM order_intents").fetchall() == [("intent", "0.1234567890123456789", "1.000001")]
        assert conn.execute("SELECT intent_id FROM order_events").fetchall() == [("intent",)]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM order_events")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT OR REPLACE INTO order_events VALUES ('event', 'intent', 'REPLACED', 'time')")
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_stale_decision_cannot_create_intent(contract_db):
    now = datetime.now(UTC)
    advance_state(contract_db, 0, [], EMPTY_DIGEST, now)
    with pytest.raises(StaleStateError):
        save_intent(contract_db, make_intent(), 0, "event", now)
    with pytest.raises(ValueError, match="유효한 판단"):
        save_intent(contract_db, make_intent(), 1, "event", now)
    with closing(sqlite3.connect(contract_db)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM order_intents").fetchone() == (0,)


@pytest.mark.parametrize("change", ["missing", "invalid_date", "non_utc", "no_trade", "wrong_asset", "wrong_side", "wrong_run", "wrong_version"])
def test_invalid_or_unmatched_proposal_cannot_create_intent(contract_db, change):
    with closing(sqlite3.connect(contract_db)) as conn:
        proposal = json.loads(conn.execute("SELECT proposal_json FROM decisions").fetchone()[0])
        if change == "missing":
            del proposal["rationale"]
        elif change == "invalid_date":
            proposal["as_of_utc"] = "2026-01-01T00:00:00"
        elif change == "non_utc":
            proposal["as_of_utc"] = "2026-01-01T00:00:00+09:00"
        elif change == "no_trade":
            proposal.update(action="NO_TRADE", items=[])
        elif change == "wrong_asset":
            proposal["items"][0]["asset_id"] = "US:NASDAQ:OTHER:STOCK"
        elif change == "wrong_side":
            proposal["items"][0]["side"] = "SELL"
        elif change == "wrong_run":
            proposal["run_id"] = "other"
        else:
            proposal["state_version"] = 1
        conn.execute("UPDATE decisions SET proposal_json = ?", (json.dumps(proposal),))
        conn.commit()
    with pytest.raises(ValueError):
        save_intent(contract_db, make_intent(), 0, "event", datetime.now(UTC))
    with closing(sqlite3.connect(contract_db)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM order_intents").fetchone() == (0,)


def test_intent_currency_must_match_asset(contract_db):
    with pytest.raises(ValueError, match="통화"):
        save_intent(contract_db, make_intent(currency="KRW"), 0, "event", datetime.now(UTC))
    with closing(sqlite3.connect(contract_db)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM order_intents").fetchone() == (0,)


def test_save_decision_checks_schema_version_and_is_atomic(contract_db):
    with closing(sqlite3.connect(contract_db)) as conn:
        valid = conn.execute("SELECT proposal_json FROM decisions").fetchone()[0]
    invalid = json.loads(valid)
    del invalid["evidence_ids"]
    with pytest.raises(ValueError, match="계약 검증"):
        save_decision(contract_db, "invalid", json.dumps(invalid))
    save_decision(contract_db, "new", valid)
    with pytest.raises(sqlite3.IntegrityError):
        save_decision(contract_db, "new", valid)
    advance_state(contract_db, 0, [], EMPTY_DIGEST, datetime.now(UTC))
    with pytest.raises(StaleStateError):
        save_decision(contract_db, "stale", valid)
    with closing(sqlite3.connect(contract_db)) as conn:
        assert conn.execute("SELECT decision_id FROM decisions ORDER BY decision_id").fetchall() == [("decision",), ("new",)]
        assert conn.execute("SELECT schema_valid, evidence_ids_json FROM decisions WHERE decision_id='new'").fetchone() == (1, '["evidence"]')
        assert conn.execute("SELECT decision_id, failure_code FROM decision_validation_failures").fetchall() == [("invalid", "INVALID_PROPOSAL")]


@pytest.mark.parametrize("case", ["missing", "future", "wrong_asset", "naive"])
def test_decision_rejects_invalid_evidence_and_records_failure(contract_db, case):
    with closing(sqlite3.connect(contract_db)) as conn:
        valid = conn.execute("SELECT proposal_json FROM decisions").fetchone()[0]
        if case == "missing":
            conn.execute("DELETE FROM evidence WHERE evidence_id = 'evidence'")
        elif case == "future":
            conn.execute("UPDATE evidence SET fetched_at = '2027-01-01T00:00:00+00:00'")
        elif case == "wrong_asset":
            conn.execute("UPDATE evidence SET asset_ids_json = '[]'")
        else:
            conn.execute("UPDATE evidence SET fetched_at = '2025-01-01T00:00:00'")
        conn.commit()
    with pytest.raises(ValueError, match="증거"):
        save_decision(contract_db, "bad-evidence", valid)
    with closing(sqlite3.connect(contract_db)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM decisions WHERE decision_id='bad-evidence'").fetchone() == (0,)
        assert conn.execute("SELECT failure_code FROM decision_validation_failures WHERE decision_id='bad-evidence'").fetchone() == ("INVALID_EVIDENCE",)


def test_corrupt_relationship_and_unknown_version_block_writes(contract_db):
    with closing(sqlite3.connect(contract_db)) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DELETE FROM assets")
        conn.execute("INSERT INTO allowlist VALUES ('missing', 999, 1, NULL)")
        conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="외래키"):
        advance_state(contract_db, 0, [], "", datetime.now(UTC))
    with closing(sqlite3.connect(contract_db)) as conn:
        conn.execute("DELETE FROM allowlist")
        conn.execute("INSERT INTO schema_version VALUES (99, 'future')")
        conn.commit()
    with pytest.raises(sqlite3.DatabaseError, match="버전"):
        advance_state(contract_db, 0, [], "", datetime.now(UTC))


def test_missing_audit_trigger_blocks_writes(contract_db):
    with closing(sqlite3.connect(contract_db)) as conn:
        conn.execute("DROP TRIGGER order_events_no_update")
        conn.commit()
    with pytest.raises(sqlite3.DatabaseError, match="정의 불일치"):
        save_intent(contract_db, make_intent(), 0, "event", datetime.now(UTC))
    with closing(sqlite3.connect(contract_db)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM order_intents").fetchone() == (0,)


def test_process_crash_rolls_back_uncommitted_state(tmp_path):
    path = tmp_path / "crash.db"
    create_contract_db(path)
    script = (
        "import os,sqlite3,sys; c=sqlite3.connect(sys.argv[1]); "
        "c.execute('BEGIN IMMEDIATE'); "
        "c.execute(\"INSERT INTO strategy_state VALUES (999,'t','[]','bad',NULL)\"); "
        "os._exit(23)"
    )
    result = subprocess.run([sys.executable, "-c", script, str(path)], check=False, timeout=15)
    assert result.returncode == 23
    assert load_state(path)[0] == 0
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_two_processes_only_one_can_advance(tmp_path):
    path = tmp_path / "process.db"
    create_contract_db(path)
    script = (
        "import sys; from datetime import UTC,datetime; "
        "from invest_agent.storage.contract_store import advance_state; "
        f"advance_state(sys.argv[1],0,[],{EMPTY_DIGEST!r},datetime.now(UTC))"
    )
    processes = [subprocess.Popen([sys.executable, "-c", script, str(path)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    results = [proc.communicate(timeout=15) for proc in processes]
    assert sorted(proc.returncode for proc in processes) == [0, 1]
    assert any(b"StaleStateError" in stderr for _, stderr in results)
    assert load_state(path)[0] == 1


def test_new_store_restart_thesis_history_and_stale_decisions(tmp_path):
    path = tmp_path / "new.db"
    ensure_contract_db(path)
    now = datetime.now(UTC)
    asset = AssetInput(asset_id="US:NASDAQ:AAPL:STOCK", market="US", venue="NASDAQ", symbol="AAPL",
                       asset_type="STOCK", currency="USD", leveraged=False, eligibility_status="UNVERIFIED")
    assert save_asset(path, asset, 0, now) == 1
    evidence = EvidenceInput(evidence_id="evidence", asset_ids=[asset.asset_id],
                             source_url="https://example.test", publisher="fixture", published_at_utc=now,
                             retrieved_at_utc=now, text_excerpt="fixture", content_hash="hash")
    assert save_evidence(path, evidence, 1, now) == 2
    thesis = ThesisInput(thesis_id="thesis", version=1, horizon_days=30, asset_id=asset.asset_id, status="ACTIVE",
                         premise="first hypothesis", invalidation=["condition"], evidence_ids=["evidence"])
    assert save_thesis(path, thesis, ["thesis"], 2, now) == 3
    run = RunInput(run_id="run", state_version=3, mode="OFFLINE_SIM", provider="fake", model="fixture",
                   input_hash="hash", started_utc=now)
    save_run(path, run)
    proposal = {"schema_version": "1.0", "run_id": "run", "state_version": 3,
                "as_of_utc": now.isoformat(), "action": "TRADE",
                "items": [{"asset_id": asset.asset_id, "side": "BUY", "target_weight_bps": 100,
                           "rationale": "fixture reason", "evidence_ids": ["evidence"]}],
                "rationale": "fixture reason", "evidence_ids": ["evidence"], "thesis_updates": []}
    save_decision(path, "decision", json.dumps(proposal))
    intent = make_intent()
    save_intent(path, intent, 3, "event", now)
    ensure_contract_db(path)
    assert load_asset(path, asset.asset_id) == asset
    assert load_evidence(path, "evidence") == evidence
    assert json.loads(load_decision(path, "decision")) == proposal
    assert load_intent(path, "intent") == (intent, "INTENT_CREATED")
    assert load_state(path)[0:2] == (3, ["thesis"])
    assert load_thesis(path, "thesis", 1) == thesis
    changed = thesis.model_copy(update={"version": 2, "premise": "second hypothesis"})
    assert save_thesis(path, changed, ["thesis"], 3, now) == 4
    assert load_thesis(path, "thesis", 1) == thesis
    assert load_thesis(path, "thesis", 2) == changed
    with pytest.raises(StaleStateError):
        save_intent(path, make_intent(intent_id="stale", idempotency_key="stale"), 3, "stale", now)
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM order_intents").fetchone() == (1,)
        assert conn.execute("SELECT COUNT(*) FROM order_events").fetchone() == (1,)


def test_asset_and_thesis_failures_roll_back_state(tmp_path):
    path = tmp_path / "new.db"
    ensure_contract_db(path)
    now = datetime.now(UTC)
    asset = AssetInput(asset_id="KRX:KRX:005930:STOCK", market="KRX", venue="KRX", symbol="005930",
                       asset_type="STOCK", currency="KRW", leveraged=False, eligibility_status="UNVERIFIED")
    save_asset(path, asset, 0, now)
    with pytest.raises(sqlite3.IntegrityError):
        save_asset(path, asset, 1, now)
    thesis = ThesisInput(thesis_id="thesis", version=1, horizon_days=30, asset_id=asset.asset_id, status="ACTIVE",
                         premise="hypothesis", invalidation=[], evidence_ids=[])
    with pytest.raises(ValueError, match="활성 가설"):
        save_thesis(path, thesis, ["missing"], 1, now)
    assert load_state(path)[0] == 1
    assert load_thesis(path, "thesis", 1) is None
    with pytest.raises(ValidationError):
        AssetInput(asset_id="US:AAPL", market="US", venue="NASDAQ", symbol="AAPL",
                   asset_type="STOCK", currency="USD", leveraged=False, eligibility_status="UNVERIFIED")


def test_evidence_validation_and_state_conflicts(tmp_path):
    path = tmp_path / "new.db"
    ensure_contract_db(path)
    now = datetime.now(UTC)
    asset = AssetInput(asset_id="US:NASDAQ:AAPL:STOCK", market="US", venue="NASDAQ", symbol="AAPL",
                       asset_type="STOCK", currency="USD", leveraged=False, eligibility_status="UNVERIFIED")
    save_asset(path, asset, 0, now)
    evidence = EvidenceInput(evidence_id="evidence", asset_ids=[asset.asset_id], source_url="https://example.test",
                             publisher="fixture", published_at_utc=now, retrieved_at_utc=now,
                             text_excerpt="fixture", content_hash="hash")
    with pytest.raises(StaleStateError):
        save_evidence(path, evidence, 0, now)
    with pytest.raises(ValueError, match="증거 자산"):
        save_evidence(path, evidence.model_copy(update={"asset_ids": ["US:NYSE:OTHER:STOCK"]}), 1, now)
    with pytest.raises(ValidationError):
        save_evidence(path, evidence.model_copy(update={"published_at_utc": now + timedelta(seconds=1)}), 1, now)
    with pytest.raises(ValidationError):
        EvidenceInput(evidence_id="numeric", asset_ids=[asset.asset_id], source_url="fixture", publisher="fixture",
                      published_at_utc=0, retrieved_at_utc=now, text_excerpt="", content_hash="hash")
    assert save_evidence(path, evidence, 1, now) == 2
    with pytest.raises(sqlite3.IntegrityError):
        save_evidence(path, evidence, 2, now)
    assert load_state(path)[0] == 2


def test_model_copy_cannot_bypass_validation(contract_db):
    invalid = make_intent().model_copy(update={"qty": -1})
    with pytest.raises(ValidationError):
        save_intent(contract_db, invalid, 0, "event", datetime.now(UTC))
    with pytest.raises(ValueError, match="상태 버전"):
        advance_state(contract_db, False, [], EMPTY_DIGEST, datetime.now(UTC))
