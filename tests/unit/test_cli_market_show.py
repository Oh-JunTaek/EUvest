"""CLI market show 명령 테스트."""

from __future__ import annotations

import tempfile
from pathlib import Path

from typer.testing import CliRunner

from invest_agent.cli import app
from invest_agent.market.market_data import OHLCV, Market
from invest_agent.storage.repositories import OHLCVRepository
from invest_agent.storage.schema import ensure_db


def _make_ohlcv(
    asset_id: str = "KRX:005930",
    market: Market = Market.KRX,
    date: str = "2024-01-02",
    open_price: str = "78200",
    high_price: str = "79000",
    low_price: str = "77500",
    close_price: str = "78500",
    volume: int = 1000000,
) -> OHLCV:
    from datetime import UTC, datetime
    from decimal import Decimal
    return OHLCV(
        timestamp=datetime.fromisoformat(date).replace(tzinfo=UTC),
        open=Decimal(open_price),
        high=Decimal(high_price),
        low=Decimal(low_price),
        close=Decimal(close_price),
        volume=volume,
        asset_id=asset_id,
        market=market,
    )


class TestMarketShowCLI:
    """market show CLI 명령 테스트."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        ensure_db(self.db_path)

        # 테스트 데이터 저장
        repo = OHLCVRepository(self.db_path)
        repo.save(_make_ohlcv(date="2024-01-02"), provider="TestProvider")
        repo.save(_make_ohlcv(date="2024-01-03"), provider="TestProvider")
        repo.save(_make_ohlcv(date="2024-01-04"), provider="TestProvider")
        repo.save(_make_ohlcv(date="2024-01-05"), provider="TestProvider")
        repo.save(_make_ohlcv(date="2024-01-06"), provider="TestProvider")

    def teardown_method(self):
        import gc
        import shutil
        gc.collect()
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except PermissionError:
                pass
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_show_basic(self):
        """기본 조회 테스트."""
        runner = CliRunner()
        result = runner.invoke(app, ["market", "show", "--asset", "KRX:005930", "--db", str(self.db_path)])

        assert result.exit_code == 0
        assert "OHLCV Data: KRX:005930" in result.output
        assert "TestProvider" in result.output
        # 테이블에 5개 행이 있어야 함 (박스 그리기 문자 확인)
        assert result.output.count("│") >= 10  # 헤더 + 5행 * 7컬럼

    def test_show_with_limit(self):
        """limit 옵션 테스트."""
        runner = CliRunner()
        result = runner.invoke(app, ["market", "show", "--asset", "KRX:005930", "--db", str(self.db_path), "--limit", "2"])

        assert result.exit_code == 0
        assert "OHLCV Data: KRX:005930" in result.output
        # limit=2면 데이터 행 2개 + 헤더 = 3줄의 박스 그리기
        # 각 행은 7개의 "│" 구분자
        assert result.output.count("│") >= 6  # 최소 2행 * (7-1) 구분자

    def test_show_nonexistent_asset(self):
        """존재하지 않는 자산 조회."""
        runner = CliRunner()
        result = runner.invoke(app, ["market", "show", "--asset", "KRX:999999", "--db", str(self.db_path)])

        assert result.exit_code == 0
        assert "해당 자산의 저장된 데이터가 없습니다" in result.output

    def test_show_nonexistent_db(self):
        """존재하지 않는 DB 파일."""
        runner = CliRunner()
        result = runner.invoke(app, ["market", "show", "--asset", "KRX:005930", "--db", "/nonexistent/path.db"])

        assert result.exit_code == 1
        assert "DB 파일이 없습니다" in result.output

    def test_show_invalid_asset_format(self):
        """잘못된 자산 ID 형식."""
        runner = CliRunner()
        result = runner.invoke(app, ["market", "show", "--asset", "INVALID", "--db", str(self.db_path)])

        assert result.exit_code == 1
        assert "지원하지 않는 자산 ID 형식" in result.output

    def test_show_us_market(self):
        """US 시장 데이터 조회."""
        # US 데이터 추가
        repo = OHLCVRepository(self.db_path)
        repo.save(
            _make_ohlcv(asset_id="US:AAPL", market=Market.US, date="2024-01-02", open_price="150.00", close_price="153.00"),
            provider="TestProvider",
        )

        runner = CliRunner()
        result = runner.invoke(app, ["market", "show", "--asset", "US:AAPL", "--db", str(self.db_path)])

        assert result.exit_code == 0
        assert "OHLCV Data: US:AAPL" in result.output
        assert "153.00" in result.output or "150.00" in result.output
