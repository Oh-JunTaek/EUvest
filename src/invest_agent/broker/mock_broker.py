"""MockBroker - 키 없이 동작하는 테스트용 브로커 구현."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from invest_agent.broker.protocol import (
    Balance,
    BrokerProtocol,
    OrderSummary,
    Position,
    Quote,
)
from invest_agent.storage.schema import ensure_db


class MockBroker(BrokerProtocol):
    """테스트/개발용 Mock 브로커.

    KIS API 키 없이도 동작하며, 설정된 시나리오 데이터를 반환한다.
    OFFLINE_SIM 모드에서 상태를 SQLite에 영속화한다.
    """

    def __init__(
        self,
        initial_cash: Decimal = Decimal("100000000"),
        initial_positions: dict[str, Decimal] | None = None,
        quotes: dict[str, Decimal] | None = None,
        fx_rate_usd_krw: Decimal = Decimal("1300"),
        db_path: str | Path | None = None,
    ):
        self._environment = "MOCK"
        self._connected = True

        # Store initial_cash for use when DB has default/zero values
        self._initial_cash = initial_cash

        # DB 경로 설정 및 초기화
        self._db_path: Path | None = None
        self._conn: sqlite3.Connection | None = None
        self._fx_rate_usd_krw = fx_rate_usd_krw
        self._quotes: dict[str, Decimal] = {}
        self._orders: dict[str, dict] = {}

        if db_path is not None:
            self._db_path = Path(db_path)
            ensure_db(self._db_path)
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.row_factory = sqlite3.Row
            # Load state from DB
            self._load_state()
        else:
            # No DB - use defaults
            self._cash_krw = initial_cash
            self._cash_usd = Decimal("0")
            self._positions: dict[str, dict] = {}

        # 초기 설정
        if initial_positions:
            for asset_id, qty in initial_positions.items():
                price = self._quotes.get(asset_id, Decimal("10000"))
                self._positions[asset_id] = {
                    "quantity": qty,
                    "avg_price": price,
                    "current_price": price,
                    "currency": "USD" if asset_id.startswith("US:") else "KRW",
                }
        elif not hasattr(self, '_positions'):
            self._positions = {}

        # Load quotes from DB if available
        if self._db_path:
            self._load_quotes()
            # Load fx_rate from DB
            self._load_fx_rate()

    def _load_state(self) -> None:
        """DB에서 계좌 상태와 포지션 로드."""
        cursor = self._conn.cursor()

        # Load mock_account (including initialized flag)
        row = cursor.execute(
            "SELECT cash_krw, cash_usd, fx_rate_usd_krw, initialized FROM mock_account WHERE id = 'default'"
        ).fetchone()
        if row:
            loaded_cash_krw = Decimal(row["cash_krw"])
            initialized = row["initialized"]
            # If account was created by migration (initialized=0), use initial_cash
            # If explicitly initialized (initialized=1), restore as-is even if 0
            if initialized == 0:
                self._cash_krw = self._initial_cash
            else:
                self._cash_krw = loaded_cash_krw
            self._cash_usd = Decimal(row["cash_usd"])
            self._fx_rate_usd_krw = Decimal(row["fx_rate_usd_krw"])
            # Persist the initial cash and mark as initialized if migrated
            if initialized == 0:
                self._save_account()
        else:
            # Initialize default record
            self._cash_krw = self._initial_cash
            self._cash_usd = Decimal("0")
            self._fx_rate_usd_krw = Decimal("1300")
            self._save_account()

        # Load positions
        rows = self._conn.execute("SELECT * FROM mock_positions").fetchall()
        self._positions = {}
        for row in rows:
            self._positions[row["asset_id"]] = {
                "quantity": Decimal(row["quantity"]),
                "avg_price": Decimal(row["avg_price"]),
                "current_price": Decimal(row["current_price"]),
                "currency": row["currency"],
            }

    def _load_quotes(self) -> None:
        """DB에서 시세 로드 (mock_positions의 current_price 기준)."""
        pass

    def _load_fx_rate(self) -> None:
        """DB에서 환율 로드."""
        pass

    def _save_account(self, commit: bool = True) -> None:
        """계좌 상태 저장 (cash_krw, cash_usd, fx_rate, initialized)."""
        if not self._db_path:
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO mock_account (id, cash_krw, cash_usd, fx_rate_usd_krw, updated_at, initialized) VALUES ('default', ?, ?, ?, ?, 1)",
            (str(self._cash_krw), str(self._cash_usd), str(self._fx_rate_usd_krw), datetime.now(UTC).isoformat())
        )
        if commit:
            self._conn.commit()

    def _save_position(self, asset_id: str, commit: bool = True) -> None:
        """포지션 저장."""
        if not self._db_path or asset_id not in self._positions:
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO mock_positions (asset_id, quantity, avg_price, current_price, currency, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (asset_id, str(self._positions[asset_id]["quantity"]), str(self._positions[asset_id]["avg_price"]), str(self._positions[asset_id]["current_price"]), self._positions[asset_id]["currency"], datetime.now(UTC).isoformat())
        )
        if commit:
            self._conn.commit()

    def _delete_position(self, asset_id: str, commit: bool = True) -> None:
        """포지션 삭제 (전량 매도 시)."""
        if not self._db_path:
            return
        self._conn.execute("DELETE FROM mock_positions WHERE asset_id = ?", (asset_id,))
        if commit:
            self._conn.commit()

    def _save_fill(self, fill_id: str, order_id: str, asset_id: str, side: str, filled_qty: Decimal, filled_price: Decimal, commit: bool = True) -> None:
        """체결 기록 저장 (중복 방지용)."""
        if not self._db_path:
            return
        self._conn.execute(
            "INSERT OR IGNORE INTO processed_fills (fill_id, order_id, asset_id, side, filled_qty, filled_price, processed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (fill_id, order_id, asset_id, side, str(filled_qty), str(filled_price), datetime.now(UTC).isoformat())
        )
        if commit:
            self._conn.commit()

    def _is_fill_processed(self, fill_id: str) -> bool:
        """체결이 이미 처리되었는지 확인."""
        if not self._db_path:
            return False
        row = self._conn.execute("SELECT 1 FROM processed_fills WHERE fill_id = ?", (fill_id,)).fetchone()
        return row is not None

    def set_fx_rate(self, fx_rate: Decimal) -> None:
        """환율 설정."""
        self._fx_rate_usd_krw = fx_rate
        self._save_account()

    def _convert_usd_to_krw(self, usd_amount: Decimal) -> Decimal:
        """USD를 KRW로 환산."""
        return usd_amount * self._fx_rate_usd_krw

    def _convert_krw_to_usd(self, krw_amount: Decimal) -> Decimal:
        """KRW를 USD로 환산."""
        if self._fx_rate_usd_krw == 0:
            return Decimal("0")
        return krw_amount / self._fx_rate_usd_krw

    @property
    def environment(self) -> str:
        return self._environment

    @property
    def is_connected(self) -> bool:
        return self._connected

    def health_check(self) -> bool:
        return self._connected

    def get_balance(self) -> Balance:
        total_equity = self._cash_krw
        for pos in self._positions.values():
            qty = pos["quantity"]
            curr_price = pos["current_price"]
            currency = pos.get("currency", "KRW")
            if currency == "USD":
                total_equity += qty * curr_price * self._fx_rate_usd_krw
            else:
                total_equity += qty * curr_price

        return Balance(
            currency="KRW",
            total_cash=self._cash_krw,
            available_cash=self._cash_krw,
            total_equity=total_equity,
            updated_at=datetime.now(UTC),
        )

    def get_positions(self) -> list[Position]:
        result = []
        for asset_id, pos in self._positions.items():
            qty = pos["quantity"]
            avg_price = pos["avg_price"]
            curr_price = pos["current_price"]
            currency = pos.get("currency", "KRW")
            market_value = qty * curr_price
            if currency == "USD":
                market_value = market_value * self._fx_rate_usd_krw
            result.append(Position(
                asset_id=asset_id,
                quantity=qty,
                avg_price=avg_price,
                current_price=curr_price,
                market_value=market_value,
                unrealized_pnl=qty * (curr_price - avg_price) * (self._fx_rate_usd_krw if currency == "USD" else Decimal("1")),
                currency=currency,
            ))
        return result

    def get_quote(self, asset_id: str) -> Quote:
        price = self._quotes.get(asset_id, Decimal("10000"))
        if asset_id in self._positions:
            price = self._positions[asset_id]["current_price"]
        return Quote(
            asset_id=asset_id,
            price=price,
            bid=price - Decimal("10"),
            ask=price + Decimal("10"),
            volume=100000,
            timestamp=datetime.now(UTC),
        )

    def get_orders(self, status_filter: str | None = None) -> list[OrderSummary]:
        orders = list(self._orders.values())
        if status_filter:
            orders = [o for o in orders if o["status"] == status_filter]

        return [
            OrderSummary(
                order_id=o["order_id"],
                asset_id=o["asset_id"],
                side=o["side"],
                order_type=o["order_type"],
                quantity=o["quantity"],
                price=o["price"],
                status=o["status"],
                filled_quantity=o["filled_quantity"],
                filled_price=o["filled_price"],
                created_at=o["created_at"],
                updated_at=o["updated_at"],
            )
            for o in orders
        ]

    def get_order(self, order_id: str) -> OrderSummary | None:
        o = self._orders.get(order_id)
        if not o:
            return None
        return OrderSummary(
            order_id=o["order_id"],
            asset_id=o["asset_id"],
            side=o["side"],
            order_type=o["order_type"],
            quantity=o["quantity"],
            price=o["price"],
            status=o["status"],
            filled_quantity=o["filled_quantity"],
            filled_price=o["filled_price"],
            created_at=o["created_at"],
            updated_at=o["updated_at"],
        )

    # 테스트 헬퍼 메서드들
    def set_quote(self, asset_id: str, price: Decimal) -> None:
        """시세 설정."""
        self._quotes[asset_id] = price
        if asset_id in self._positions:
            self._positions[asset_id]["current_price"] = price
            self._save_position(asset_id)
        else:
            self._quotes[asset_id] = price

    def set_position(self, asset_id: str, quantity: Decimal, avg_price: Decimal) -> None:
        """포지션 설정."""
        self._positions[asset_id] = {
            "quantity": quantity,
            "avg_price": avg_price,
            "current_price": self._quotes.get(asset_id, avg_price),
            "currency": "USD" if asset_id.startswith("US:") else "KRW",
        }
        self._save_position(asset_id)

    def add_order(
        self,
        asset_id: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Decimal | None = None,
    ) -> str:
        """주문 추가 (테스트용)."""
        order_id = str(uuid4())
        now = datetime.now(UTC)
        self._orders[order_id] = {
            "order_id": order_id,
            "asset_id": asset_id,
            "side": side,
            "order_type": order_type,
            "quantity": quantity,
            "price": price,
            "status": "ACKNOWLEDGED",
            "filled_quantity": Decimal("0"),
            "filled_price": None,
            "created_at": now,
            "updated_at": now,
        }
        return order_id

    def fill_order(self, order_id: str, filled_qty: Decimal, filled_price: Decimal) -> bool:
        """주문 체결 처리 (테스트용)."""
        if order_id not in self._orders:
            return False
        o = self._orders[order_id]

        # Check for duplicate fill using stable fill_id (order_id + filled_qty + filled_price)
        fill_id = f"{order_id}-{filled_qty}-{filled_price}"
        if self._is_fill_processed(fill_id):
            return False  # Already processed

        # Save pre-state for potential rollback
        prev_cash_krw = self._cash_krw
        prev_cash_usd = self._cash_usd
        prev_positions = {k: v.copy() for k, v in self._positions.items()}

        o["filled_quantity"] = filled_qty
        o["filled_price"] = filled_price
        o["status"] = "FILLED" if filled_qty >= o["quantity"] else "PARTIALLY_FILLED"
        o["updated_at"] = datetime.now(UTC)

        asset_id = o["asset_id"]
        is_usd = asset_id.startswith("US:")

        if self._db_path:
            self._conn.execute("BEGIN IMMEDIATE")

        try:
            if o["side"] == "BUY":
                if is_usd:
                    cost_krw = filled_qty * filled_price * self._fx_rate_usd_krw
                    self._cash_krw -= cost_krw
                else:
                    cost_krw = filled_qty * filled_price
                    self._cash_krw -= cost_krw

                if asset_id in self._positions:
                    pos = self._positions[asset_id]
                    pos["quantity"] += filled_qty
                    total_qty = pos["quantity"]
                    pos["avg_price"] = (
                        (pos["avg_price"] * (total_qty - filled_qty)) + (filled_price * filled_qty)
                    ) / total_qty
                else:
                    self._positions[asset_id] = {
                        "quantity": filled_qty,
                        "avg_price": filled_price,
                        "current_price": filled_price,
                        "currency": "USD" if is_usd else "KRW",
                    }
            else:  # SELL
                if is_usd:
                    proceeds_krw = filled_qty * filled_price * self._fx_rate_usd_krw
                    self._cash_krw += proceeds_krw
                else:
                    proceeds_krw = filled_qty * filled_price
                    self._cash_krw += proceeds_krw

                if asset_id in self._positions:
                    pos = self._positions[asset_id]
                    pos["quantity"] -= filled_qty
                    if pos["quantity"] <= 0:
                        del self._positions[asset_id]
                        if self._db_path:
                            self._delete_position(asset_id, commit=False)
                else:
                    pass

            if self._db_path:
                self._save_account(commit=False)
                if asset_id in self._positions:
                    self._save_position(asset_id, commit=False)
                self._save_fill(fill_id, order_id, asset_id, o["side"], filled_qty, filled_price, commit=False)
                self._conn.commit()
        except Exception:
            # Restore in-memory state on rollback
            self._cash_krw = prev_cash_krw
            self._cash_usd = prev_cash_usd
            self._positions = prev_positions
            if self._db_path:
                self._conn.rollback()
            raise

        return True

    def cancel_order(self, order_id: str) -> bool:
        """주문 취소 (테스트용)."""
        if order_id in self._orders:
            self._orders[order_id]["status"] = "CANCELLED"
            self._orders[order_id]["updated_at"] = datetime.now(UTC)
            return True
        return False

    def close(self) -> None:
        """DB 연결 종료."""
        if self._conn:
            self._conn.close()
            self._conn = None
            self._db_path = None
