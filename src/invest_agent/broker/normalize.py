"""데이터 정규화 - KIS 응답을 내부 표준 형식으로 변환."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any


def to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    """문자열/숫자를 Decimal로 안전 변환."""
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        v = value.strip().replace(",", "")
        if not v:
            return default
        try:
            return Decimal(v)
        except Exception:
            return default
    return default


def to_int(value: Any, default: int = 0) -> int:
    """문자열/숫자를 int로 안전 변환."""
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        v = value.strip().replace(",", "")
        if not v:
            return default
        try:
            return int(float(v))
        except Exception:
            return default
    return default


def parse_kis_datetime(date_str: str, time_str: str | None = None) -> datetime:
    """KIS 날짜/시간 문자열을 UTC datetime으로 파싱.

    KIS 형식: YYYYMMDD, HHMMSS 또는 HHMMSSff
    """
    if not date_str:
        return datetime.now()

    ds = date_str.strip()
    ts = time_str.strip() if time_str else "000000"

    # 날짜 파싱: YYYYMMDD
    try:
        year = int(ds[0:4])
        month = int(ds[4:6])
        day = int(ds[6:8])
    except (ValueError, IndexError):
        return datetime.now()

    # 시간 파싱: HHMMSS 또는 HHMMSSff
    try:
        hour = int(ts[0:2]) if len(ts) >= 2 else 0
        minute = int(ts[2:4]) if len(ts) >= 4 else 0
        second = int(ts[4:6]) if len(ts) >= 6 else 0
    except (ValueError, IndexError):
        hour = minute = second = 0

    return datetime(year, month, day, hour, minute, second)


def normalize_asset_id(raw: str, market: str = "KRX") -> str:
    """자산 ID 정규화.

    KRX: 6자리 종목코드 (예: 005930) -> KRX:005930
    US: 심볼 그대로 (예: AAPL) -> US:AAPL
    """
    raw = raw.strip().upper()
    if market == "KRX":
        if not raw.startswith("KRX:"):
            return f"KRX:{raw.zfill(6)}"
        return raw
    elif market == "US":
        if not raw.startswith("US:"):
            return f"US:{raw}"
        return raw
    return raw


def parse_kis_balance(data: dict[str, Any]) -> dict[str, Any]:
    """KIS 잔고 응답 정규화."""
    return {
        "currency": "KRW",
        "total_cash": to_decimal(data.get("dnca_tot_amt") or data.get("tot_evlu_amt")),
        "available_cash": to_decimal(data.get("ord_psbl_cash") or data.get("nrcvb_buy_amt")),
        "total_equity": to_decimal(data.get("tot_evlu_amt")),
    }


def parse_kis_position(data: dict[str, Any]) -> dict[str, Any]:
    """KIS 보유 종목 응답 정규화."""
    qty = to_decimal(data.get("hldg_qty"))
    avg_price = to_decimal(data.get("pchs_avg_pric") or data.get("avg_prvs"))
    curr_price = to_decimal(data.get("prpr") or data.get("cur_prc"))

    return {
        "asset_id": normalize_asset_id(data.get("pdno") or data.get("shtn_pdno", "")),
        "quantity": qty,
        "avg_price": avg_price,
        "current_price": curr_price,
        "market_value": qty * curr_price,
        "unrealized_pnl": qty * (curr_price - avg_price),
        "currency": "KRW",
    }


def parse_kis_quote(data: dict[str, Any]) -> dict[str, Any]:
    """KIS 현재가 응답 정규화."""
    return {
        "asset_id": normalize_asset_id(data.get("mksc_shrn_iscd") or data.get("shtn_pdno", "")),
        "price": to_decimal(data.get("stck_prpr") or data.get("prpr")),
        "bid": to_decimal(data.get("stck_bidp") or data.get("bidp1")) if data.get("stck_bidp") or data.get("bidp1") else None,
        "ask": to_decimal(data.get("stck_askp") or data.get("askp1")) if data.get("stck_askp") or data.get("askp1") else None,
        "volume": to_int(data.get("acml_vol") or data.get("acml_tr_pbmn")),
        "timestamp": parse_kis_datetime(
            data.get("stck_bsop_date") or data.get("bsop_date", ""),
            data.get("stck_cntg_hour") or data.get("cntg_hour"),
        ),
    }


def parse_kis_order(data: dict[str, Any]) -> dict[str, Any]:
    """KIS 주문 응답 정규화."""
    return {
        "order_id": str(data.get("odno") or data.get("ord_no") or ""),
        "asset_id": normalize_asset_id(data.get("pdno") or data.get("shtn_pdno", "")),
        "side": "BUY" if (data.get("sll_buy_dvsn_cd") == "02" or data.get("sll_buy_dvsn") == "02") else "SELL",
        "order_type": "MARKET" if data.get("ord_dvsn_cd") in ("01", "1") else "LIMIT",
        "quantity": to_decimal(data.get("ord_qty") or data.get("ord_qty2")),
        "price": to_decimal(data.get("ord_unpr") or data.get("ord_prc")) if data.get("ord_unpr") or data.get("ord_prc") else None,
        "status": _normalize_order_status(data.get("ord_stt_cd") or data.get("ord_stts")),
        "filled_quantity": to_decimal(data.get("tot_ccld_qty") or data.get("ccld_qty")),
        "filled_price": to_decimal(data.get("avg_ccld_prc") or data.get("ccld_avg_prc")) if data.get("avg_ccld_prc") or data.get("ccld_avg_prc") else None,
        "created_at": parse_kis_datetime(
            data.get("ord_dt") or data.get("ord_date", ""),
            data.get("ord_tmd") or data.get("ord_time"),
        ),
        "updated_at": parse_kis_datetime(
            data.get("ccld_dt") or data.get("ccld_date", ""),
            data.get("ccld_tmd") or data.get("ccld_time"),
        ),
    }


def _normalize_order_status(raw: str | None) -> str:
    """KIS 주문 상태를 표준 상태로 매핑."""
    if not raw:
        return "UNKNOWN"
    status_map = {
        "01": "INTENT_CREATED",   # 접수
        "02": "SUBMITTING",       # 확인
        "03": "ACKNOWLEDGED",     # 체결
        "04": "PARTIALLY_FILLED", # 일부체결
        "05": "FILLED",           # 전부체결
        "06": "CANCELLED",        # 취소
        "07": "REJECTED",         # 거부
        "08": "UNKNOWN",
    }
    return status_map.get(str(raw).strip(), "UNKNOWN")
