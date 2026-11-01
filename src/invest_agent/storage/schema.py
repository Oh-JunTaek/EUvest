"""SQLite 스키마 정의 및 마이그레이션 관리."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

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
        changed INTEGER NOT NULL DEFAULT 0,
        change_reason TEXT NOT NULL,
        model_provider_from TEXT NOT NULL,
        model_provider_to TEXT NOT NULL,
        model_name_from TEXT NOT NULL,
        model_name_to TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (from_run_id) REFERENCES agent_runs(id) ON DELETE RESTRICT,
        FOREIGN KEY (to_run_id) REFERENCES agent_runs(id) ON DELETE RESTRICT,
        FOREIGN KEY (thesis_id) REFERENCES theses(id) ON DELETE RESTRICT
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

INITIAL_VERSION_DDL = """
INSERT OR IGNORE INTO schema_version (version) VALUES (1)
"""
INITIAL_VERSION_DDL = """
INSERT OR IGNORE INTO schema_version (version) VALUES (1)
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


def migrate(db_path: str | Path, target_version: int = SCHEMA_VERSION) -> None:
    """마이그레이션 실행 (현재 버전 → 타겟 버전)."""
    current = get_schema_version(db_path)
    if current >= target_version:
        return

    conn = get_connection(db_path)
    try:
        # 향후 버전별 마이그레이션 로직 추가 위치
        # 예: if current < 2: run_migration_v2(conn)
        conn.execute("UPDATE schema_version SET version = ?", (target_version,))
        conn.commit()
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
