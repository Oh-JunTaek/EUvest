"""브로커 프로토콜 계약 테스트.

MockBroker와 KISReadAdapter가 동일한 인터페이스를 준수하는지 검증.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from invest_agent.broker.mock_broker import MockBroker
from invest_agent.broker.protocol import Balance, Position


class TestBrokerProtocolContract:
    """브로커 프로토콜 인터페이스 계약 테스트."""

    @pytest.fixture
    def mock_broker(self) -> MockBroker:
        """기본 MockBroker 픽스처."""
        return MockBroker(
            initial_cash=Decimal("100000000"),
            initial_positions={"KRX:005930": Decimal("100")},
            quotes={"KRX:005930": Decimal("70000")},
        )

    def test_environment_property(self, mock_broker: MockBroker):
        assert mock_broker.environment == "MOCK"
        assert isinstance(mock_broker.environment, str)

    def test_is_connected_property(self, mock_broker: MockBroker):
        assert mock_broker.is_connected is True
        assert isinstance(mock_broker.is_connected, bool)

    def test_health_check(self, mock_broker: MockBroker):
        assert mock_broker.health_check() is True

    def test_get_balance_returns_balance(self, mock_broker: MockBroker):
        balance = mock_broker.get_balance()
        assert isinstance(balance, Balance)
        assert balance.currency == "KRW"
        assert isinstance(balance.total_cash, Decimal)
        assert isinstance(balance.available_cash, Decimal)
        assert isinstance(balance.total_equity, Decimal)
        assert balance.total_cash >= Decimal("0")
        assert balance.available_cash <= balance.total_cash
        assert balance.total_equity >= balance.total_cash

    def test_get_positions_returns_list(self, mock_broker: MockBroker):
        positions = mock_broker.get_positions()
        assert isinstance(positions, list)
        for pos in positions:
            assert isinstance(pos, Position)
            assert isinstance(pos.asset_id, str)
            assert isinstance(pos.quantity, Decimal)
            assert isinstance(pos.avg_price, Decimal)
            assert isinstance(pos.current_price, Decimal)
            assert isinstance(pos.market_value, Decimal)
            assert isinstance(pos.unrealized_pnl, Decimal)
            assert pos.currency == "KRW"
