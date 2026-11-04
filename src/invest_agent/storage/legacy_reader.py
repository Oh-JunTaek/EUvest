"""기존 DB를 변경하지 않고 읽는다. 반환 데이터에는 민감정보가 있을 수 있다."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

LEGACY_TABLES = (
    "theses", "evidence", "decisions", "agent_runs", "orders", "handoffs", "equity_snapshots",
)


def read_legacy_snapshot(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    """v1/v2 전체 행을 읽기 트랜잭션에서 반환한다.

    미지원 버전은 ValueError, 손상·참조 오류는 sqlite3.DatabaseError 계열이다.
    결과는 로컬 메모리에서만 다뤄야 하며 로그나 외부 API에 전달하면 안 된다.
    """
    uri = f"{Path(path).resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        conn.execute("BEGIN")
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise sqlite3.DatabaseError("기존 DB 무결성 검사 실패")
        versions = conn.execute("SELECT version FROM schema_version ORDER BY version").fetchall()
        if [row[0] for row in versions] not in ([1], [2], [1, 2]):
            raise ValueError("지원하지 않는 기존 DB 버전")
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise sqlite3.IntegrityError("기존 DB 외래키 무결성 검사 실패")
        return {
            table: [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
            for table in LEGACY_TABLES
        }
