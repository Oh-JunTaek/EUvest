"""실행 잠금 - 중복 실행 방지."""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path


class ExecutionLock:
    """SQLite 기반 실행 잠금 (파일 시스템 + DB 이중 보호)."""

    def __init__(self, db_path: str | Path, lock_name: str = "run_once"):
        self.db_path = Path(db_path)
        self.lock_name = lock_name
        self._local_lock = threading.Lock()
        self._acquired = False
        self._ensure_lock_table()

    def _ensure_lock_table(self) -> None:
        """잠금 테이블 생성."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS execution_locks (
                    lock_name TEXT PRIMARY KEY,
                    acquired_at TEXT NOT NULL,
                    pid INTEGER NOT NULL,
                    run_id TEXT
                )
            """)
            conn.commit()

    def acquire(self, run_id: str, timeout_seconds: int = 0) -> bool:
        """잠금 획득 시도.

        Args:
            run_id: 실행 식별자
            timeout_seconds: 대기 시간 (0 = 즉시 실패)

        Returns:
            True if acquired, False if already locked
        """
        start_time = time.time()

        while True:
            with self._local_lock:
                if self._try_acquire(run_id):
                    self._acquired = True
                    return True

            if timeout_seconds == 0:
                return False

            if time.time() - start_time >= timeout_seconds:
                return False

            time.sleep(0.1)

    def _try_acquire(self, run_id: str) -> bool:
        """잠금 즉시 획득 시도 (로컬 락 내에서 호출)."""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute("PRAGMA busy_timeout = 100")
                cursor = conn.execute(
                    "SELECT lock_name FROM execution_locks WHERE lock_name = ?",
                    (self.lock_name,)
                )
                if cursor.fetchone():
                    return False

                conn.execute(
                    "INSERT INTO execution_locks (lock_name, acquired_at, pid, run_id) VALUES (?, datetime('now'), ?, ?)",
                    (self.lock_name, threading.get_ident(), run_id)
                )
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            return False
        except sqlite3.OperationalError:
            return False

    def release(self) -> None:
        """잠금 해제."""
        with self._local_lock:
            if not self._acquired:
                return
            try:
                with sqlite3.connect(str(self.db_path)) as conn:
                    conn.execute(
                        "DELETE FROM execution_locks WHERE lock_name = ?",
                        (self.lock_name,)
                    )
                    conn.commit()
            finally:
                self._acquired = False

    @contextmanager
    def hold(self, run_id: str, timeout_seconds: int = 0):
        """컨텍스트 매니저로 잠금 유지."""
        acquired = self.acquire(run_id, timeout_seconds)
        if not acquired:
            raise RuntimeError(f"Another execution is already running (lock: {self.lock_name})")
        try:
            yield True
        finally:
            self.release()

    def is_locked(self) -> bool:
        """현재 잠금 상태 확인."""
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute(
                "SELECT lock_name FROM execution_locks WHERE lock_name = ?",
                (self.lock_name,)
            )
            return cursor.fetchone() is not None


class RunStatusTracker:
    """실행 상태 추적 - DB 기반."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def mark_started(self, run_id: str, status: str = "RUNNING") -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "UPDATE agent_runs SET status = ?, started_at = datetime('now') WHERE id = ?",
                (status, run_id)
            )
            conn.commit()

    def mark_completed(self, run_id: str, status: str, error: str | None = None) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "UPDATE agent_runs SET status = ?, completed_at = datetime('now'), error = ? WHERE id = ?",
                (status, error, run_id)
            )
            conn.commit()

    def get_status(self, run_id: str) -> str | None:
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute(
                "SELECT status FROM agent_runs WHERE id = ?", (run_id,)
            )
            row = cursor.fetchone()
            return row[0] if row else None
