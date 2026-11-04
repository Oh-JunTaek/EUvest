"""SQLite 스키마 정의 및 마이그레이션 관리."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 2

DDL_STATEMENTS = [
    # theses 테이블
    """
    CREATE TABLE IF NOT EXISTS theses (
        id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL,
        hypothesis TEXT NOT NULL,
        rationale TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        metadata TEXT NOT NULL DEFAULT '{}'
    )
    """,
    # evidence 테이블
    """
    CREATE TABLE IF NOT EXISTS evidence (
        id TEXT PRIMARY KEY,
        thesis_id TEXT NOT NULL,
        evidence_type TEXT NOT NULL,
        source TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        collected_at TEXT NOT NULL,
        content TEXT NOT NULL DEFAULT '{}',
        raw_ref TEXT NOT NULL DEFAULT '',
        metadata TEXT NOT NULL DEFAULT '{}',
        FOREIGN KEY (thesis_id) REFERENCES theses(id) ON DELETE RESTRICT
    )
    """,
    # decisions 테이블
    """
    CREATE TABLE IF NOT EXISTS decisions (
        id TEXT PRIMARY KEY,
        thesis_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        outcome TEXT NOT NULL,
        side TEXT,
        target_weight_bps INTEGER,
        current_weight_bps INTEGER,
        rationale TEXT NOT NULL,
        evidence_ids TEXT NOT NULL DEFAULT '[]',
        model_provider TEXT NOT NULL,
        model_name TEXT NOT NULL,
        execution_mode TEXT NOT NULL,
        decided_at TEXT NOT NULL,
        error TEXT,
        metadata TEXT NOT NULL DEFAULT '{}',
        FOREIGN KEY (thesis_id) REFERENCES theses(id) ON DELETE RESTRICT,
        FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE RESTRICT
    )
    """,
    # agent_runs 테이블
    """
    CREATE TABLE IF NOT EXISTS agent_runs (
        id TEXT PRIMARY KEY,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        status TEXT NOT NULL,
        execution_mode TEXT NOT NULL,
        schedule_id TEXT,
        thesis_ids TEXT NOT NULL DEFAULT '[]',
        decision_ids TEXT NOT NULL DEFAULT '[]',
        order_ids TEXT NOT NULL DEFAULT '[]',
        error TEXT,
        metadata TEXT NOT NULL DEFAULT '{}'
    )
    """,
    # orders 테이블
    """
    CREATE TABLE IF NOT EXISTS orders (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        decision_id TEXT NOT NULL,
        asset_id TEXT NOT NULL,
        side TEXT NOT NULL,
        order_type TEXT NOT NULL,
        quantity TEXT NOT NULL,
        price TEXT,
        status TEXT NOT NULL,
        broker_order_id TEXT,
        submitted_at TEXT,
        acknowledged_at TEXT,
        filled_at TEXT,
        filled_quantity TEXT NOT NULL DEFAULT '0',
        filled_price TEXT,
        commission TEXT NOT NULL DEFAULT '0',
        tax TEXT NOT NULL DEFAULT '0',
        error TEXT,
        metadata TEXT NOT NULL DEFAULT '{}',
        FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE RESTRICT,
        FOREIGN KEY (decision_id) REFERENCES decisions(id) ON DELETE RESTRICT
    )
    """,
    # handoffs 테이블
    """
    CREATE TABLE IF NOT EXISTS handoffs (
        id TEXT PRIMARY KEY,
        from_run_id TEXT NOT NULL,
        to_run_id TEXT NOT NULL,
        thesis_id TEXT NOT NULL,
        previous_decision_id TEXT NOT NULL,
        previous_outcome TEXT NOT NULL,
        new_outcome TEXT NOT NULL,
        changed INTEGER NOT NULL,
        change_reason TEXT NOT NULL,
        model_provider_from TEXT NOT NULL,
        model_provider_to TEXT NOT NULL,
        model_name_from TEXT NOT NULL,
        model_name_to TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (from_run_id) REFERENCES agent_runs(id) ON DELETE RESTRICT,
        FOREIGN KEY (to_run_id) REFERENCES agent_runs(id) ON DELETE RESTRICT,
        FOREIGN KEY (thesis_id) REFERENCES theses(id) ON DELETE RESTRICT,
        FOREIGN KEY (previous_decision_id) REFERENCES decisions(id) ON DELETE RESTRICT
    )
    """,
    # equity_snapshots 테이블
    """
    CREATE TABLE IF NOT EXISTS equity_snapshots (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        total_equity TEXT NOT NULL DEFAULT '0',
        cash_balance TEXT NOT NULL DEFAULT '0',
        positions TEXT NOT NULL DEFAULT '{}',
        unrealized_pnl TEXT NOT NULL DEFAULT '0',
        realized_pnl TEXT NOT NULL DEFAULT '0',
        metadata TEXT NOT NULL DEFAULT '{}',
        FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE RESTRICT
    )
    """,
    # 인덱스
    "CREATE INDEX IF NOT EXISTS idx_theses_asset_id ON theses(asset_id)",
    "CREATE INDEX IF NOT EXISTS idx_theses_active ON theses(is_active)",
    "CREATE INDEX IF NOT EXISTS idx_evidence_thesis_id ON evidence(thesis_id)",
    "CREATE INDEX IF NOT EXISTS idx_decisions_thesis_id ON decisions(thesis_id)",
    "CREATE INDEX IF NOT EXISTS idx_decisions_run_id ON decisions(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON agent_runs(status)",
    "CREATE INDEX IF NOT EXISTS idx_agent_runs_started_at ON agent_runs(started_at)",
    "CREATE INDEX IF NOT EXISTS idx_orders_run_id ON orders(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_orders_decision_id ON orders(decision_id)",
    "CREATE INDEX IF NOT EXISTS idx_handoffs_thesis_id ON handoffs(thesis_id)",
    "CREATE INDEX IF NOT EXISTS idx_handoffs_from_run ON handoffs(from_run_id)",
    "CREATE INDEX IF NOT EXISTS idx_handoffs_to_run ON handoffs(to_run_id)",
    "CREATE INDEX IF NOT EXISTS idx_equity_snapshots_run_id ON equity_snapshots(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_equity_snapshots_timestamp ON equity_snapshots(timestamp)",
    # 스키마 버전 테이블
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
]

def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """SQLite 연결 생성 (외래키 활성화, WAL 모드)."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path) -> None:
    """데이터베이스 초기화 (스키마 생성 + 버전 기록)."""
    conn = get_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1").fetchone():
            raise sqlite3.DatabaseError("기존 DB는 초기화할 수 없습니다")
        for ddl in DDL_STATEMENTS:
            conn.execute(ddl)
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, datetime.now(UTC).isoformat()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_schema_version(db_path: str | Path) -> int:
    """현재 스키마 버전 조회."""
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def _backup_db(conn: sqlite3.Connection, db_path: Path) -> Path:
    """마이그레이션 전 백업 생성."""
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    backup_path = db_path.with_suffix(f".bak.{stamp}")
    fd = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with closing(sqlite3.connect(str(backup_path))) as backup:
        conn.backup(backup)
        if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise sqlite3.DatabaseError("백업 DB 무결성 검사 실패")
        if backup.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise sqlite3.IntegrityError("백업 DB 외래키 무결성 검사 실패")
    return backup_path


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """v1(CASCADE FK) -> v2(RESTRICT FK) 마이그레이션.

    SQLite는 FK 변경 시 테이블 재생성이 필요하므로:
    1. 모든 새 테이블(_v2) 생성 (RESTRICT FK) - DDL_STATEMENTS의 스키마 사용
    2. 모든 데이터 복사
    3. 기존 테이블 삭제
    4. 새 테이블 이름 변경
    """
    # FK가 있는 테이블들 (마이그레이션 순서 중요: 자식 테이블 먼저 - CASCADE 삭제 방지)
    # 1. orders (자식: agent_runs, decisions 참조)
    # 2. handoffs (자식: agent_runs, theses, decisions 참조)
    # 3. evidence (자식: theses 참조)
    # 4. equity_snapshots (자식: agent_runs 참조)
    # 5. decisions (부모: orders, handoffs 참조 / 자식: theses, agent_runs 참조)
    tables_with_fk = [
        "orders",
        "handoffs",
        "evidence",
        "equity_snapshots",
        "decisions",
    ]

    index_names = {
        ddl.split()[5]
        for ddl in DDL_STATEMENTS
        if ddl.strip().upper().startswith("CREATE INDEX IF NOT EXISTS")
    }
    for table in tables_with_fk:
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = ?", (f"{table}_v2",)
        ).fetchone():
            raise sqlite3.DatabaseError(f"임시 테이블 이름이 이미 존재함: {table}_v2")
        dependent = conn.execute(
            "SELECT type, name FROM sqlite_master "
            "WHERE tbl_name = ? AND (type = 'trigger' OR (type = 'index' AND sql IS NOT NULL))",
            (table,),
        ).fetchall()
        for object_type, name in dependent:
            if object_type == "trigger" or name not in index_names:
                raise sqlite3.DatabaseError(f"보존할 사용자 정의 객체가 있음: {name}")
        if any(row[3] == "u" for row in conn.execute(f"PRAGMA index_list({table})")):
            raise sqlite3.DatabaseError(f"추가 UNIQUE 제약을 자동 변환할 수 없음: {table}")

    existing_tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for (table,) in existing_tables:
        if table in tables_with_fk:
            continue
        references = conn.execute('SELECT "table" FROM pragma_foreign_key_list(?)', (table,))
        if any(row[0] in tables_with_fk for row in references):
            raise sqlite3.DatabaseError(f"마이그레이션 대상에 대한 외부 참조가 있음: {table}")

    # 1단계: 모든 새 테이블(_v2) 생성
    new_tables = {}
    for table in tables_with_fk:
        new_table = f"{table}_v2"

        # 기존 테이블 존재 확인
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()

        if not exists:
            raise sqlite3.DatabaseError(f"마이그레이션 대상 테이블 없음: {table}")

        print(f"Creating {new_table}...")

        # 새 테이블 생성 (DDL_STATEMENTS에서 해당 테이블의 CREATE 문 사용)
        create_ddl = None
        for ddl in DDL_STATEMENTS:
            if ddl.strip().upper().startswith("CREATE TABLE") and f"{table} (" in ddl:
                create_ddl = ddl
                break

        if not create_ddl:
            raise sqlite3.DatabaseError(f"스키마 정의 없음: {table}")

        # 테이블명 변경하여 새 테이블 생성
        new_sql = create_ddl.replace(f"CREATE TABLE {table}", f"CREATE TABLE {new_table}")
        new_sql = new_sql.replace(f"CREATE TABLE IF NOT EXISTS {table}", f"CREATE TABLE IF NOT EXISTS {new_table}")

        conn.execute(new_sql)
        source_columns = [
            (row[1], row[2].upper(), row[3], row[5])
            for row in conn.execute(f"PRAGMA table_info({table})")
        ]
        target_columns = [
            (row[1], row[2].upper(), row[3], row[5])
            for row in conn.execute(f"PRAGMA table_info({new_table})")
        ]
        if source_columns != target_columns:
            raise sqlite3.DatabaseError(f"마이그레이션 열 구성 또는 순서 불일치: {table}")
        new_tables[table] = new_table

    # 2단계: 모든 데이터 복사 (자식 -> 부모 순서로 복사)
    for table in tables_with_fk:
        if table not in new_tables:
            continue
        new_table = new_tables[table]

        print(f"Migrating table: {table}")
        src_count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"Source {table} has {src_count} rows")

        print(f"Copying data from {table} to {new_table}...")
        conn.execute(f"INSERT INTO {new_table} SELECT * FROM {table}")

        count = conn.execute(f"SELECT COUNT(*) FROM {new_table}").fetchone()[0]
        print(f"Copied {count} rows to {new_table}")

        if count != src_count:
            raise RuntimeError(f"데이터 복사 실패: {table} 원본 {src_count}건, 복사본 {count}건")

    # 3단계: 기존 테이블 삭제
    for table in tables_with_fk:
        if table not in new_tables:
            continue
        conn.execute(f"DROP TABLE {table}")
        print(f"Dropped {table}")

    # 4단계: 새 테이블 이름 변경
    for table in tables_with_fk:
        if table not in new_tables:
            continue
        new_table = new_tables[table]
        conn.execute(f"ALTER TABLE {new_table} RENAME TO {table}")
        print(f"Renamed {new_table} to {table}")

    # 인덱스 재생성 (인덱스는 DROP TABLE 시 자동 삭제됨)
    index_ddls = [ddl for ddl in DDL_STATEMENTS if ddl.strip().upper().startswith("CREATE INDEX")]
    for ddl in index_ddls:
        conn.execute(ddl)



def migrate(db_path: str | Path, target_version: int = SCHEMA_VERSION) -> None:
    """마이그레이션 실행 (현재 버전 -> 타겟 버전)."""
    if target_version != SCHEMA_VERSION:
        raise ValueError(f"지원하지 않는 스키마 버전: {target_version} (최대: {SCHEMA_VERSION})")

    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    conn = get_connection(path)
    try:
        current_row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        current = current_row[0]
        if current == target_version:
            return
        if current != 1:
            raise ValueError(f"지원하지 않는 기존 스키마 버전: {current}")
        data_version = conn.execute("PRAGMA data_version").fetchone()[0]
        _backup_db(conn, path)
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("PRAGMA data_version").fetchone()[0] != data_version:
            raise sqlite3.OperationalError("백업 중 DB가 변경됨: 마이그레이션 중단")
        if conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] != current:
            raise sqlite3.OperationalError("스키마 버전이 변경됨: 마이그레이션 중단")
        _migrate_v1_to_v2(conn)
        conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                     (target_version, datetime.now(UTC).isoformat()))
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise sqlite3.IntegrityError("마이그레이션 후 외래키 무결성 검증 실패")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_db(db_path: str | Path) -> None:
    """기존 호환 저장소 초기화. 과거 DB는 자동 변환하지 않는다."""
    path = Path(db_path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        init_db(path)
    else:
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        if row is None or row[0] != SCHEMA_VERSION:
            raise sqlite3.DatabaseError("기존 DB 자동 변환 금지: 읽기 전용 조회를 사용하세요")
