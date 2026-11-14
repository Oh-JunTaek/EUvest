"""MockBroker 체결 트랜잭션 원자성 및 롤백 테스트.

OFFLINE_SIM 전용 테스트.
"""

import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from invest_agent.broker.mock_broker import MockBroker


class TestMockBrokerAtomicFill:
    """체결 트랜잭션 원자성 및 롤백 테스트."""

    def test_normal_buy_then_sell_persists(self):
        """정상 매수·매도 후 저장 성공 확인."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            initial_cash = Decimal("100000000")

            broker = MockBroker(initial_cash=initial_cash, db_path=db_path)
            broker.set_quote("KRX:005930", Decimal("70000"))

            buy_order = broker.add_order("KRX:005930", "BUY", "LIMIT", Decimal("10"), Decimal("70000"))
            result = broker.fill_order(buy_order, Decimal("10"), Decimal("70000"))
            assert result is True

            sell_order = broker.add_order("KRX:005930", "SELL", "LIMIT", Decimal("10"), Decimal("72000"))
            result = broker.fill_order(sell_order, Decimal("10"), Decimal("72000"))
            assert result is True

            balance = broker.get_balance()
            assert balance.total_cash == Decimal("100020000")
            positions = broker.get_positions()
            assert len(positions) == 0

            broker.close()

            broker2 = MockBroker(initial_cash=Decimal("999999999"), db_path=db_path)
            balance2 = broker2.get_balance()
            assert balance2.total_cash == Decimal("100020000")
            positions2 = broker2.get_positions()
            assert len(positions2) == 0
            broker2.close()

    def test_rollback_on_db_error(self):
        """DB 오류 발생 시 전체 롤백 (연결 끊기 시뮬레이션)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            initial_cash = Decimal("100000000")

            broker = MockBroker(initial_cash=initial_cash, db_path=db_path)
            broker.set_quote("KRX:005930", Decimal("70000"))

            buy_order = broker.add_order("KRX:005930", "BUY", "LIMIT", Decimal("10"), Decimal("70000"))

            broker._conn.close()
            broker._conn = None

            with pytest.raises(Exception):
                broker.fill_order(buy_order, Decimal("10"), Decimal("70000"))

            balance = broker.get_balance()
            assert balance.total_cash == initial_cash
            positions = broker.get_positions()
            assert len(positions) == 0

            broker.close()

            broker2 = MockBroker(initial_cash=Decimal("999999999"), db_path=db_path)
            balance2 = broker2.get_balance()
            assert balance2.total_cash == initial_cash
            positions2 = broker2.get_positions()
            assert len(positions2) == 0
            broker2.close()

    def test_memory_state_unchanged_after_error(self):
        """오류 직후 메모리 잔고·포지션 불변 확인."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            initial_cash = Decimal("100000000")

            broker = MockBroker(initial_cash=initial_cash, db_path=db_path)
            broker.set_quote("KRX:005930", Decimal("70000"))

            broker.set_position("KRX:000660", Decimal("5"), Decimal("120000"))

            buy_order = broker.add_order("KRX:005930", "BUY", "LIMIT", Decimal("10"), Decimal("70000"))

            broker._conn.close()
            broker._conn = None

            with pytest.raises(Exception):
                broker.fill_order(buy_order, Decimal("10"), Decimal("70000"))

            balance = broker.get_balance()
            assert balance.total_cash == initial_cash
            positions = broker.get_positions()
            assert len(positions) == 1
            assert positions[0].asset_id == "KRX:000660"
            assert positions[0].quantity == Decimal("5")

            broker.close()

    def test_duplicate_fill_prevention(self):
        """동일 체결 이벤트 중복 반영 방지."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            initial_cash = Decimal("100000000")

            broker = MockBroker(initial_cash=initial_cash, db_path=db_path)
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

    def test_rollback_persists_across_new_instance(self):
        """오류 후 새 MockBroker 인스턴스 생성해도 롤백 상태 유지."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            initial_cash = Decimal("100000000")

            broker1 = MockBroker(initial_cash=initial_cash, db_path=db_path)
            broker1.set_quote("KRX:005930", Decimal("70000"))

            buy_order = broker1.add_order("KRX:005930", "BUY", "LIMIT", Decimal("10"), Decimal("70000"))

            broker1._conn.close()
            broker1._conn = None

            with pytest.raises(Exception):
                broker1.fill_order(buy_order, Decimal("10"), Decimal("70000"))

            broker1.close()

            broker2 = MockBroker(initial_cash=Decimal("999999999"), db_path=db_path)
            balance2 = broker2.get_balance()
            assert balance2.total_cash == initial_cash
            positions2 = broker2.get_positions()
            assert len(positions2) == 0
            broker2.close()

    def test_partial_fill_atomicity(self):
        """부분 체결도 원자적으로 처리."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            initial_cash = Decimal("100000000")

            broker = MockBroker(initial_cash=initial_cash, db_path=db_path)
            broker.set_quote("KRX:005930", Decimal("70000"))

            order_id = broker.add_order("KRX:005930", "BUY", "LIMIT", Decimal("20"), Decimal("70000"))
            result = broker.fill_order(order_id, Decimal("10"), Decimal("70000"))
            assert result is True

            balance = broker.get_balance()
            assert balance.total_cash == initial_cash - Decimal("10") * Decimal("70000")

            positions = broker.get_positions()
            assert len(positions) == 1
            assert positions[0].quantity == Decimal("10")

            broker._conn.close()
            broker._conn = None

            with pytest.raises(Exception):
                broker.fill_order(order_id, Decimal("10"), Decimal("70000"))

            balance2 = broker.get_balance()
            assert balance2.total_cash == initial_cash - Decimal("10") * Decimal("70000")
            positions2 = broker.get_positions()
            assert len(positions2) == 1
            assert positions2[0].quantity == Decimal("10")

            broker.close()

            broker2 = MockBroker(initial_cash=Decimal("999999999"), db_path=db_path)
            balance3 = broker2.get_balance()
            assert balance3.total_cash == initial_cash - Decimal("10") * Decimal("70000")
            positions3 = broker2.get_positions()
            assert len(positions3) == 1
            assert positions3[0].quantity == Decimal("10")
            broker2.close()
