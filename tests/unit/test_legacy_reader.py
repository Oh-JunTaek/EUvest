"""기존 DB 읽기 전용 경로 검증."""

import sqlite3
from contextlib import closing

import pytest

from invest_agent.storage.legacy_reader import read_legacy_snapshot
from invest_agent.storage.schema import init_db


def test_read_preserves_existing_values_and_db(tmp_path):
    path = tmp_path / "legacy.db"
    init_db(path)
    with closing(sqlite3.connect(path)) as conn:
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
    init_db(path)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("INSERT INTO schema_version VALUES (99, 'future')")
        conn.commit()
    before = path.read_bytes()
    with pytest.raises(ValueError, match="버전"):
        read_legacy_snapshot(path)
    assert path.read_bytes() == before
