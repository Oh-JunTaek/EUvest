"""SQLite 스키마 정의 및 마이그레이션 관리."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
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

INITIAL_VERSION_DDL = f"""
INSERT OR IGNORE INTO schema_version (version) VALUES ({SCHEMA_VERSION})
"""


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
        for ddl in DDL_STATEMENTS:
            conn.execute(ddl)
        conn.execute(INITIAL_VERSION_DDL)
        conn.commit()
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


def _backup_db(db_path: Path) -> Path:
    """마이그레이션 전 백업 생성."""
    backup_path = db_path.with_suffix(f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(db_path, backup_path)
    return backup_path


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """v1(CASCADE FK) -> v2(RESTRICT FK) 마이그레이션.

    SQLite는 FK 변경 시 테이블 재생성이 필요하므로:
    1. 새 테이블(_v2) 생성 (RESTRICT FK) - DDL_STATEMENTS의 스키마 사용
    2. 데이터 복사
    3. 기존 테이블 삭제
    4. 새 테이블 이름 변경
    """
    # FK가 있는 테이블들 (마이그레이션 순서 중요: 부모 테이블 먼저)
    tables_with_fk = [
        "evidence",
        "decisions",
        "orders",
        "handoffs",
        "equity_snapshots",
    ]

    # 각 테이블별로 재생성
    for table in tables_with_fk:
        # 임시 테이블명
        new_table = f"{table}_v2"

        # 기존 테이블 존재 확인
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()

        if not exists:
            print(f"Table {table} does not exist, skipping")
            continue

        print(f"Migrating table: {table}")

        # 새 테이블 생성 (DDL_STATEMENTS에서 해당 테이블의 CREATE 문 사용)
        # DDL_STATEMENTS에서 테이블 생성문 찾기
        create_ddl = None
        for ddl in DDL_STATEMENTS:
            if ddl.strip().upper().startswith("CREATE TABLE") and f"{table} (" in ddl:
                create_ddl = ddl
                break

        if not create_ddl:
            print(f"No CREATE DDL found for {table}")
            continue

        print(f"Found DDL for {table}: {create_ddl[:100]}")

        # 테이블명 변경하여 새 테이블 생성
        new_sql = create_ddl.replace(f"CREATE TABLE {table}", f"CREATE TABLE {new_table}")
        new_sql = new_sql.replace(f"CREATE TABLE IF NOT EXISTS {table}", f"CREATE TABLE IF NOT EXISTS {new_table}")

        print(f"Creating {new_table}...")
        conn.execute(new_sql)

        # 데이터 복사 전 소스 테이블 확인
        src_count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"Source {table} has {src_count} rows")

        # 데이터 복사
        print(f"Copying data from {table} to {new_table}...")
        conn.execute(f"INSERT INTO {new_table} SELECT * FROM {table}")

        # 복사된 데이터 확인
        count = conn.execute(f"SELECT COUNT(*) FROM {new_table}").fetchone()[0]
        print(f"Copied {count} rows to {new_table}")

        # 기존 테이블 삭제
        conn.execute(f"DROP TABLE {table}")
        print(f"Dropped {table}")

        # 새 테이블 이름 변경
        conn.execute(f"ALTER TABLE {new_table} RENAME TO {table}")
        print(f"Renamed {new_table} to {table}")

        # 인덱스 재생성 (인덱스는 DROP TABLE 시 자동 삭제됨)
        # 인덱스 생성문은 DDL_STATEMENTS에 있으므로 init_db 시 재생성됨

    # 인덱스 재생성
    index_ddls = [ddl for ddl in DDL_STATEMENTS if ddl.strip().upper().startswith("CREATE INDEX")]
    for ddl in index_ddls:
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass  # 이미 존재할 수 있음



def migrate(db_path: str | Path, target_version: int = SCHEMA_VERSION) -> None:
    """마이그레이션 실행 (현재 버전 -> 타겟 버전)."""
    current = get_schema_version(db_path)
    if current >= target_version:
        return

    if target_version > SCHEMA_VERSION:
        raise ValueError(f"지원하지 않는 스키마 버전: {target_version} (최대: {SCHEMA_VERSION})")

    path = Path(db_path)
    backup_path = _backup_db(path)

    conn = get_connection(path)
    try:
        # 버전별 마이그레이션
        if current < 2 and target_version >= 2:
            _migrate_v1_to_v2(conn)

        # 버전 기록 업데이트 (최신 버전 추가)
        conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                     (target_version, datetime.now().isoformat()))
        conn.commit()
    except Exception:
        # 실패 시 백업에서 복구
        conn.close()
        shutil.copy2(backup_path, path)
        raise
    finally:
        conn.close()


def ensure_db(db_path: str | Path) -> None:
    """DB가 없으면 초기화, 있으면 마이그레이션."""
    path = Path(db_path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        init_db(path)
    else:
        migrate(path)
