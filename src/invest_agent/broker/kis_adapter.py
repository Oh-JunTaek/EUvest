"""KIS 읽기 전용 어댑터 - 공식 예제 래핑.

주의: 이 어댑터는 READ 전용 API만 제공한다.
주문 전송 등 쓰기 작업은 별도 승인 후 구현한다.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import httpx

from invest_agent.broker.protocol import BrokerProtocol
from invest_agent.broker.rate_limiter import (
    RateLimiter,
    acquire_kis_token,
    get_global_limiter,
)
from invest_agent.domain.enums import BrokerEnvironment

# KIS API 호스트 설정
KIS_HOSTS = {
    BrokerEnvironment.PAPER: "https://openapivts.koreainvestment.com:29443",
    BrokerEnvironment.LIVE: "https://openapi.koreainvestment.com:9443",
}


class KISReadAdapter(BrokerProtocol):
    """KIS REST API 읽기 전용 어댑터.

    - 토큰 자동 갱신
    - 레이트 리밋 준수
    - 모의/실전 호스트 분리
    - 응답 정규화
    """

    def __init__(
        self,
        environment: BrokerEnvironment,
        app_key: str | None = None,
        app_secret: str | None = None,
        account_no: str | None = None,
        rate_limiter: RateLimiter | None = None,
    ):
        self._environment = environment
        self._app_key = app_key or os.getenv("KIS_APP_KEY")
        self._app_secret = app_secret or os.getenv("KIS_APP_SECRET")
        self._account_no = account_no or os.getenv("KIS_ACCOUNT_NO", "")
        self._rate_limiter = rate_limiter or get_global_limiter()

        self._host = KIS_HOSTS.get(environment)
        if not self._host:
            raise ValueError(f"지원하지 않는 환경: {environment}")

        self._access_token: str | None = None
        self._token_expires_at: datetime | None = None
        self._client = httpx.Client(timeout=30.0)
        self._connected = False

    @property
    def environment(self) -> str:
        return self._environment.value

    @property
    def is_connected(self) -> bool:
        return self._connected

    def health_check(self) -> bool:
        try:
            self._ensure_token()
            return True
        except Exception:
            return False

    def _get_headers(self, tr_id: str, extra: dict | None = None) -> dict:
        """공통 요청 헤더 생성."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token}",
            "AppKey": self._app_key,
            "AppSecret": self._app_secret,
            "Tr_Id": tr_id,
        }
        if extra:
            headers.update(extra)
        return headers

    def _ensure_token(self) -> str:
        """액세스 토큰 확보 (필요시 발급/갱신)."""
        now = datetime.now(UTC)
        if self._access_token and self._token_expires_at and now < self._token_expires_at:
            return self._access_token

        # 레이트 리밋: 토큰 발급
        acquire_kis_token(self._rate_limiter, self.environment, timeout=30.0)

        url = f"{self._host}/oauth2/tokenP"
        data = {
            "grant_type": "client_credentials",
            "appkey": self._app_key,
            "appsecret": self._app_secret,
        }

        resp = self._client.post(url, json=data)
        resp.raise_for_status()
        token_data = resp.json()

        self._access_token = token_data["access_token"]
        # 토큰 유효기간 (보통 24시간, 여유분 1시간)
        expires_in = token_data.get("expires_in", 86400)
        self._token_expires_at = now.replace(second=now.second + expires_in - 3600)
        self._connected = True

        return self._access_token
