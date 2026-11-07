"""요청 속도 제한 - 토큰 버킷 기반 레이트 리미터."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class TokenBucket:
    """토큰 버킷 알고리즘 구현.

    초당 요청 수 제한과 버스트 허용을 동시에 처리.
    """
    rate: float  # 초당 토큰 생성률
    burst: int   # 최대 버스트 토큰 수
    _tokens: float
    _last_update: float
    _lock: threading.Lock

    def __init__(self, rate: float, burst: int):
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)
        self._last_update = time.monotonic()
        self._lock = threading.Lock()

    def take(self, tokens: int = 1, timeout: float | None = None) -> bool:
        """토큰 획득 시도.

        Args:
            tokens: 필요한 토큰 수
            timeout: 최대 대기 시간(초), None이면 즉시 반환

        Returns:
            토큰 획득 성공 여부
        """
        deadline = time.monotonic() + timeout if timeout is not None else None

        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_update
                self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
                self._last_update = now

                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True

                if timeout is not None:
                    # 다음 토큰이 생길 때까지 예상 대기 시간
                    needed = tokens - self._tokens
                    wait_time = needed / self.rate
                    if deadline is not None and now + wait_time > deadline:
                        return False
                    # 잠깐 대기 후 재시도
                    time.sleep(min(wait_time, 0.1))
                else:
                    return False

    def available_tokens(self) -> int:
        """현재 사용 가능한 토큰 수 (정수)."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_update
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            self._last_update = now
            return int(self._tokens)


class RateLimiter:
    """다중 엔드포인트/계정 지원 레이트 리미터."""

    def __init__(self):
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def get_bucket(self, key: str, rate: float, burst: int) -> TokenBucket:
        """버킷 획득 (없으면 생성)."""
        with self._lock:
            if key not in self._buckets:
                self._buckets[key] = TokenBucket(rate, burst)
            return self._buckets[key]

    def acquire(self, key: str, rate: float, burst: int, tokens: int = 1, timeout: float | None = None) -> bool:
        """토큰 획득."""
        bucket = self.get_bucket(key, rate, burst)
        return bucket.take(tokens, timeout)

    def try_acquire(self, key: str, rate: float, burst: int, tokens: int = 1) -> bool:
        """즉시 토큰 획득 시도 (대기 없음)."""
        return self.acquire(key, rate, burst, tokens, timeout=0)

    def wait_for_token(self, key: str, rate: float, burst: int, tokens: int = 1, timeout: float | None = None) -> bool:
        """토큰이 생길 때까지 대기 후 획득."""
        return self.acquire(key, rate, burst, tokens, timeout)


# 전역 레이트 리미터 인스턴스
_global_limiter = RateLimiter()


def get_global_limiter() -> RateLimiter:
    """전역 레이트 리미터 반환."""
    return _global_limiter


# KIS API 기본 제한 설정
KIS_RATE_LIMITS = {
    # (rate_per_sec, burst)
    "token": (0.1, 1),      # 토큰 발급: 10초당 1회, 버스트 1
    "price": (20, 30),      # 현재가 조회: 초당 20회, 버스트 30
    "balance": (5, 10),     # 잔고 조회: 초당 5회, 버스트 10
    "order": (10, 15),      # 주문 조회: 초당 10회, 버스트 15
    "default": (10, 20),    # 기본값
}


def acquire_kis_token(limiter: RateLimiter, env: str, timeout: float | None = None) -> bool:
    """KIS 토큰 발급용 토큰 획득."""
    return limiter.acquire(f"kis:{env}:token", *KIS_RATE_LIMITS["token"], timeout=timeout)


def acquire_kis_price(limiter: RateLimiter, env: str, timeout: float | None = None) -> bool:
    """KIS 현재가 조회용 토큰 획득."""
    return limiter.acquire(f"kis:{env}:price", *KIS_RATE_LIMITS["price"], timeout=timeout)


def acquire_kis_balance(limiter: RateLimiter, env: str, timeout: float | None = None) -> bool:
    """KIS 잔고 조회용 토큰 획득."""
    return limiter.acquire(f"kis:{env}:balance", *KIS_RATE_LIMITS["balance"], timeout=timeout)


def acquire_kis_order(limiter: RateLimiter, env: str, timeout: float | None = None) -> bool:
    """KIS 주문 조회용 토큰 획득."""
    return limiter.acquire(f"kis:{env}:order", *KIS_RATE_LIMITS["order"], timeout=timeout)
