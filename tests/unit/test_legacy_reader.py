"""기존 DB 읽기 전용 경로 검증."""

import sqlite3
from contextlib import closing

import pytest

from invest_agent.storage.legacy_reader import read_legacy_snapshot, LEGACY_TABLES
from invest_agent.storage.schema import init_db


def test_read_preserves_existing_values_and_db(tmp_path):
    path = tmp_path / "legacy.db"
    # Create a v2 database (since legacy reader only supports v1/v2)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT)")
        conn.execute("INSERT INTO schema_version VALUES (2, '2024-01-01')")
        
        # Create all legacy tables
        conn.execute("""CREATE TABLE theses (
            id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL,
            hypothesis TEXT NOT NULL,
            rationale TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            metadata TEXT NOT NULL DEFAULT '{}'
        )""")
        conn.execute("""CREATE TABLE evidence (
            id TEXT PRIMARY KEY,
            thesis_id TEXT NOT NULL,
            evidence_type TEXT NOT NULL,
            source TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            collected_at TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '{}',
            raw_ref TEXT NOT NULL DEFAULT '',
            metadata TEXT NOT NULL DEFAULT '{}'
        )""")
        conn.execute("""CREATE TABLE decisions (
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
            metadata TEXT NOT NULL DEFAULT '{}'
        )""")
        conn.execute("""CREATE TABLE agent_runs (
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
        )""")
        conn.execute("""CREATE TABLE orders (
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
            metadata TEXT NOT NULL DEFAULT '{}'
        )""")
        conn.execute("""CREATE TABLE handoffs (
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
            created_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE equity_snapshots (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            total_equity TEXT NOT NULL DEFAULT '0',
            cash_balance TEXT NOT NULL DEFAULT '0',
            positions TEXT NOT NULL DEFAULT '{}',
            unrealized_pnl TEXT NOT NULL DEFAULT '0',
            realized_pnl TEXT NOT NULL DEFAULT '0',
            metadata TEXT NOT NULL DEFAULT '{}'
        )""")
        conn.execute("INSERT INTO theses (id, asset_id, hypothesis, rationale, created_at, updated_at) VALUES ('old', 'US:AAPL', 'premise', 'reason', 'naive', 'naive')")
        conn.commit()
    before = path.read_bytes()
    snapshot = read_legacy_snapshot(path)
    assert snapshot["theses"][0]["asset_id"] == "US:AAPL"
    assert snapshot["theses"][0]["created_at"] == "naive"
    assert path.read_bytes() == before


def test_missing_or_unsupported_database_is_not_created_or_changed(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        read_legacy_snapshot(missing)
    assert not missing.exists()
    path = tmp_path / "future.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT)")
        conn.execute("INSERT INTO schema_version VALUES (99, 'future')")
        conn.commit()
    before = path.read_bytes()
    with pytest.raises(ValueError, match="버전"):
        read_legacy_snapshot(path)
    assert path.read_bytes() == before
