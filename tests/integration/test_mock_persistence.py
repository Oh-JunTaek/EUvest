"""OFFLINE_SIM 모의계좌 영속화 전용 테스트.

- 최초 계좌 생성 및 초기 현금 확인
- 매수 후 새 MockBroker 인스턴스에서 잔고·포지션 복원
- 0원 현금 유지
- 전량 매도 후 재시작
- 중복 체결 이벤트 재처리 방지
- 저장 중 오류 발생 시 롤백
"""

import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from invest_agent.broker.mock_broker import MockBroker
from invest_agent.storage.schema import ensure_db


def _create_mock_broker_with_db(db_path: str, initial_cash: Decimal = Decimal("100000000"), fx_rate_usd_krw: Decimal = Decimal("1300")) -> MockBroker:
    """DB 경로를 가진 MockBroker 생성 헬퍼."""
    return MockBroker(initial_cash=initial_cash, fx_rate_usd_krw=fx_rate_usd_krw, db_path=db_path)


class TestMockAccountPersistence:
    """MockBroker 계좌 영속화 테스트."""

    def test_initial_account_creation_and_cash(self):
        """최초 계좌 생성 시 초기 현금이 설정되고 initialized=1로 저장되는지 확인."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            initial_cash = Decimal("50000000")

            broker = _create_mock_broker_with_db(db_path, initial_cash=initial_cash)

            balance = broker.get_balance()
            assert balance.total_cash == initial_cash
            assert balance.available_cash == initial_cash

            import sqlite3
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT cash_krw, initialized FROM mock_account WHERE id = 'default'").fetchone()
            conn.close()

            assert row["cash_krw"] == str(initial_cash)
            assert row["initialized"] == 1

            broker.close()

    def test_migration_created_account_restores_initial_cash(self):
        """마이그레이션으로 생성된 계좌(initialized=0)는 초기 현금으로 복원되는지 확인."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")

            # Create a v2 database first (simulate pre-migration state)
            import sqlite3
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT)")
            conn.execute("INSERT INTO schema_version VALUES (2, '2024-01-01')")
            # Create v2 tables (simplified)
            conn.execute("CREATE TABLE theses (id TEXT PRIMARY KEY, asset_id TEXT, hypothesis TEXT, rationale TEXT, created_at TEXT, updated_at TEXT, is_active INTEGER, metadata TEXT)")
            conn.execute("CREATE TABLE evidence (id TEXT PRIMARY KEY, thesis_id TEXT, evidence_type TEXT, source TEXT, observed_at TEXT, collected_at TEXT, content TEXT, raw_ref TEXT, metadata TEXT)")
            conn.execute("CREATE TABLE agent_runs (id TEXT PRIMARY KEY, started_at TEXT, completed_at TEXT, status TEXT, execution_mode TEXT, schedule_id TEXT, thesis_ids TEXT, decision_ids TEXT, order_ids TEXT, error TEXT, metadata TEXT)")
            conn.execute("CREATE TABLE decisions (id TEXT PRIMARY KEY, thesis_id TEXT, run_id TEXT, outcome TEXT, side TEXT, target_weight_bps INTEGER, current_weight_bps INTEGER, rationale TEXT, evidence_ids TEXT, model_provider TEXT, model_name TEXT, execution_mode TEXT, decided_at TEXT, error TEXT, metadata TEXT)")
            conn.execute("CREATE TABLE orders (id TEXT PRIMARY KEY, run_id TEXT, decision_id TEXT, asset_id TEXT, side TEXT, order_type TEXT, quantity TEXT, price TEXT, status TEXT, broker_order_id TEXT, submitted_at TEXT, acknowledged_at TEXT, filled_at TEXT, filled_quantity TEXT, filled_price TEXT, commission TEXT, tax TEXT, error TEXT, metadata TEXT)")
            conn.execute("CREATE TABLE handoffs (id TEXT PRIMARY KEY, from_run_id TEXT, to_run_id TEXT, thesis_id TEXT, previous_decision_id TEXT, previous_outcome TEXT, new_outcome TEXT, changed INTEGER, change_reason TEXT, model_provider_from TEXT, model_provider_to TEXT, model_name_from TEXT, model_name_to TEXT, created_at TEXT)")
            conn.execute("CREATE TABLE equity_snapshots (id TEXT PRIMARY KEY, run_id TEXT, timestamp TEXT, total_equity TEXT, cash_balance TEXT, positions TEXT, unrealized_pnl TEXT, realized_pnl TEXT, metadata TEXT)")
            conn.commit()
            conn.close()

            # Now migrate to v3 (this creates mock_account with initialized=0)
            from invest_agent.storage.schema import migrate
            migrate(db_path)

            # Verify migration created mock_account with initialized=0
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT cash_krw, initialized FROM mock_account WHERE id = 'default'").fetchone()
            conn.close()
            assert row["cash_krw"] == "0"
            assert row["initialized"] == 0

            initial_cash = Decimal("75000000")
            broker = _create_mock_broker_with_db(db_path, initial_cash=initial_cash)

            balance = broker.get_balance()
            assert balance.total_cash == initial_cash

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT cash_krw, initialized FROM mock_account WHERE id = 'default'").fetchone()
            conn.close()

            assert row["cash_krw"] == str(initial_cash)
            assert row["initialized"] == 1

            broker.close()

    def test_explicit_zero_balance_restored_as_is(self):
        """명시적으로 0원으로 초기화된 계좌(initialized=1, cash=0)는 0원으로 복원되는지 확인."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            ensure_db(db_path)

            import sqlite3
            conn = sqlite3.connect(db_path)
            conn.execute("""
                INSERT OR REPLACE INTO mock_account (id, cash_krw, cash_usd, fx_rate_usd_krw, updated_at, initialized)
                VALUES ('default', '0', '0', '1300', datetime('now'), 1)
            """)
            conn.commit()
            conn.close()
            conn.close()

            broker = _create_mock_broker_with_db(db_path, initial_cash=Decimal("100000000"))

            balance = broker.get_balance()
            assert balance.total_cash == Decimal("0")

            broker.close()

    def test_buy_then_restore_balance_and_position(self):
        """매수 후 새 MockBroker 인스턴스에서 잔고와 포지션이 복원되는지 확인."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            initial_cash = Decimal("100000000")

            broker1 = _create_mock_broker_with_db(db_path, initial_cash=initial_cash)
            broker1.set_quote("KRX:005930", Decimal("70000"))

            order_id = broker1.add_order("KRX:005930", "BUY", "LIMIT", Decimal("10"), Decimal("70000"))
            broker1.fill_order(order_id, Decimal("10"), Decimal("70000"))

            balance1 = broker1.get_balance()
            positions1 = broker1.get_positions()

            expected_cash_after_buy = initial_cash - Decimal("10") * Decimal("70000")
            assert balance1.total_cash == expected_cash_after_buy
            assert len(positions1) == 1
            assert positions1[0].asset_id == "KRX:005930"
            assert positions1[0].quantity == Decimal("10")

            broker1.close()

            broker2 = _create_mock_broker_with_db(db_path, initial_cash=Decimal("999999999"))
            balance2 = broker2.get_balance()
            positions2 = broker2.get_positions()

            assert balance2.total_cash == expected_cash_after_buy
            assert len(positions2) == 1
            assert positions2[0].asset_id == "KRX:005930"
            assert positions2[0].quantity == Decimal("10")
            assert positions2[0].avg_price == Decimal("70000")

            broker2.close()

    def test_zero_cash_persists_across_restart(self):
        """0원 현금이 재시작 후에도 유지되는지 확인."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")

            broker1 = _create_mock_broker_with_db(db_path, initial_cash=Decimal("700000"))
            broker1.set_quote("KRX:005930", Decimal("70000"))

            order_id = broker1.add_order("KRX:005930", "BUY", "LIMIT", Decimal("10"), Decimal("70000"))
            broker1.fill_order(order_id, Decimal("10"), Decimal("70000"))

            balance1 = broker1.get_balance()
            assert balance1.total_cash == Decimal("0")

            broker1.close()

            broker2 = _create_mock_broker_with_db(db_path, initial_cash=Decimal("100000000"))
            balance2 = broker2.get_balance()
            assert balance2.total_cash == Decimal("0")

            broker2.close()

    def test_full_sell_position_removed_on_restart(self):
        """전량 매도 후 포지션이 메모리와 DB에서 모두 삭제되고 재시작 시 복원되지 않는지 확인."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            initial_cash = Decimal("100000000")

            broker1 = _create_mock_broker_with_db(db_path, initial_cash=initial_cash)
            broker1.set_quote("KRX:005930", Decimal("70000"))

            buy_order = broker1.add_order("KRX:005930", "BUY", "LIMIT", Decimal("10"), Decimal("70000"))
            broker1.fill_order(buy_order, Decimal("10"), Decimal("70000"))

            sell_order = broker1.add_order("KRX:005930", "SELL", "LIMIT", Decimal("10"), Decimal("70000"))
            broker1.fill_order(sell_order, Decimal("10"), Decimal("70000"))

            positions1 = broker1.get_positions()
            assert len(positions1) == 0

            import sqlite3
            conn = sqlite3.connect(db_path)
            rows = conn.execute("SELECT * FROM mock_positions WHERE asset_id = 'KRX:005930'").fetchall()
            conn.close()
            assert len(rows) == 0

            broker1.close()

            broker2 = _create_mock_broker_with_db(db_path, initial_cash=initial_cash)
            positions2 = broker2.get_positions()
            assert len(positions2) == 0

            broker2.close()

    def test_duplicate_fill_prevention(self):
        """동일한 체결 이벤트가 두 번 전달되어도 잔고·보유 수량이 한 번만 변경되는지 확인."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            initial_cash = Decimal("100000000")

            broker = _create_mock_broker_with_db(db_path, initial_cash=initial_cash)
            broker.set_quote("KRX:005930", Decimal("70000"))

            order_id = broker.add_order("KRX:005930", "BUY", "LIMIT", Decimal("10"), Decimal("70000"))

            result1 = broker.fill_order(order_id, Decimal("10"), Decimal("70000"))
            assert result1 is True

            balance1 = broker.get_balance()
            expected_cash = initial_cash - Decimal("10") * Decimal("70000")
            assert balance1.total_cash == expected_cash

            result2 = broker.fill_order(order_id, Decimal("10"), Decimal("70000"))
            assert result2 is False

            balance2 = broker.get_balance()
            assert balance2.total_cash == expected_cash

            positions = broker.get_positions()
            assert len(positions) == 1
            assert positions[0].quantity == Decimal("10")

            import sqlite3
            conn = sqlite3.connect(db_path)
            rows = conn.execute("SELECT * FROM processed_fills").fetchall()
            conn.close()
            assert len(rows) == 1

            broker.close()

    def test_fill_atomicity_rollback_on_error(self):
        """체결 저장 중 오류 발생 시 모든 변경사항이 롤백되는지 확인."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            initial_cash = Decimal("100000000")

            broker = _create_mock_broker_with_db(db_path, initial_cash=initial_cash)
            broker.set_quote("KRX:005930", Decimal("70000"))

            order_id = broker.add_order("KRX:005930", "BUY", "LIMIT", Decimal("10"), Decimal("70000"))

            broker._conn.close()
            broker._conn = None

            with pytest.raises(Exception):
                broker.fill_order(order_id, Decimal("10"), Decimal("70000"))

            import sqlite3
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row

            row = conn.execute("SELECT cash_krw FROM mock_account WHERE id = 'default'").fetchone()
            assert row["cash_krw"] == str(initial_cash)

            rows = conn.execute("SELECT * FROM mock_positions").fetchall()
            assert len(rows) == 0

            rows = conn.execute("SELECT * FROM processed_fills").fetchall()
            assert len(rows) == 0

            conn.close()

            broker.close()



class TestMockBrokerPersistenceIntegration:
    """MockBroker 영속화 통합 테스트."""

    def test_multiple_buys_and_sells_persist(self):
        """여러 번 매수/매도 후 재시작 시 상태가 정확히 복원되는지 확인."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            initial_cash = Decimal("100000000")

            broker1 = _create_mock_broker_with_db(db_path, initial_cash=initial_cash)
            broker1.set_quote("KRX:005930", Decimal("70000"))
            broker1.set_quote("KRX:000660", Decimal("120000"))

            o1 = broker1.add_order("KRX:005930", "BUY", "LIMIT", Decimal("10"), Decimal("70000"))
            broker1.fill_order(o1, Decimal("10"), Decimal("70000"))

            o2 = broker1.add_order("KRX:000660", "BUY", "LIMIT", Decimal("5"), Decimal("120000"))
            broker1.fill_order(o2, Decimal("5"), Decimal("120000"))

            o3 = broker1.add_order("KRX:005930", "SELL", "LIMIT", Decimal("3"), Decimal("72000"))
            broker1.fill_order(o3, Decimal("3"), Decimal("72000"))

            balance1 = broker1.get_balance()
            positions1 = {p.asset_id: p for p in broker1.get_positions()}

            assert positions1["KRX:005930"].quantity == Decimal("7")
            assert positions1["KRX:000660"].quantity == Decimal("5")

            expected_cash = initial_cash \
                - Decimal("10") * Decimal("70000") \
                - Decimal("5") * Decimal("120000") \
                + Decimal("3") * Decimal("72000")
            assert balance1.total_cash == expected_cash

            broker1.close()

            broker2 = _create_mock_broker_with_db(db_path, initial_cash=Decimal("999999999"))
            balance2 = broker2.get_balance()
            positions2 = {p.asset_id: p for p in broker2.get_positions()}

            assert balance2.total_cash == expected_cash
            assert positions2["KRX:005930"].quantity == Decimal("7")
            assert positions2["KRX:005930"].avg_price == Decimal("70000")
            assert positions2["KRX:000660"].quantity == Decimal("5")
            assert positions2["KRX:000660"].avg_price == Decimal("120000")

            broker2.close()

    def test_usd_stock_fx_rate_persists(self):
        """USD 주식 매수 시 환율이 적용되어 KRW 현금이 차감되고 복원되는지 확인."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            initial_cash = Decimal("100000000")
            fx_rate = Decimal("1300")

            broker1 = _create_mock_broker_with_db(db_path, initial_cash=initial_cash, fx_rate_usd_krw=fx_rate)
            broker1.set_quote("US:AAPL", Decimal("150"))

            o1 = broker1.add_order("US:AAPL", "BUY", "LIMIT", Decimal("10"), Decimal("150"))
            broker1.fill_order(o1, Decimal("10"), Decimal("150"))

            expected_cash = initial_cash - Decimal("10") * Decimal("150") * fx_rate
            balance1 = broker1.get_balance()
            assert balance1.total_cash == expected_cash

            positions1 = broker1.get_positions()
            assert len(positions1) == 1
            assert positions1[0].asset_id == "US:AAPL"
            assert positions1[0].quantity == Decimal("10")

            broker1.close()

            broker2 = _create_mock_broker_with_db(db_path, initial_cash=Decimal("999999999"), fx_rate_usd_krw=fx_rate)
            balance2 = broker2.get_balance()
            assert balance2.total_cash == expected_cash

            positions2 = broker2.get_positions()
            assert len(positions2) == 1
            assert positions2[0].asset_id == "US:AAPL"
            assert positions2[0].quantity == Decimal("10")

            broker2.close()
