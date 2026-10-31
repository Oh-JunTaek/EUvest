# 03 — 외부 API 인터페이스, 도메인 스키마, DB 계약

## A. 절대 지켜야 할 도메인 정규화
- 자산 식별자 = `{market}:{venue}:{symbol}:{asset_type}` 형태의 불변 문자열. 예: `KRX:KRX:005930:STOCK`, `US:NASDAQ:AAPL:STOCK`, `US:ARCA:VOO:ETF` (거래소는 API 실제 지원값에 맞춰 매핑 검증). `ticker`만 기본키로 사용 금지.
- 시세: `price: Decimal` 양수, `currency` ISO 코드, `as_of_utc` timezone aware, `source`, `is_adjusted`. `0`/음수/미확인 값은 주문용으로 무효.
- 현금/가격/수량: `Decimal` 객체, SQLite TEXT 형식 문자열 저장. KRW/USD 통화 구분 없이 합산 금지. 환율은 관측 시각, 스프레드, 기준통화 명시.
- 주문: 실제 브로커 주문 ID, 로컬 intent ID, status가 서로 다름. 주문 요청 성공 ≠ 체결 완료.
- `state_version`은 원자적으로 증가하는 정수. 새 판단 이전에 상태가 변경되면 stale 판단 주문 거부.
- UTC ISO8601(예: `2026-10-31T08:00:00Z`) 저장. 한국과 미국 시장의 현지 시간은 `zoneinfo`로 변환. 미국 서머타임을 고정 UTC 오프셋으로 추정 금지.
- 실시간 시세의 무료 제공 지연 가능성, 거래소 데이터 라이선스, 가격 적시성을 구별. 지연 시세로 ‘실시간 의사결정’ 표시 금지.

## B. Protocol 계약: 구현 방식이 달라도 호출 이름은 통일

```python
from typing import Protocol, Sequence
from decimal import Decimal

class BrokerRead(Protocol):
    def get_balances(self, mode: str) -> "PortfolioSnapshot": ...
    def get_open_orders(self, mode: str) -> Sequence["BrokerOrder"]: ...
    def get_order(self, broker_order_id: str, mode: str) -> "BrokerOrder": ...
    def get_quote(self, asset_id: str, mode: str) -> "Quote": ...
    def get_market_capabilities(self, mode: str) -> "BrokerCapabilities": ...

class BrokerTrade(BrokerRead, Protocol):
    def submit_order(self, order: "ValidatedOrder", mode: str) -> "SubmissionReceipt": ...
    def cancel_order(self, broker_order_id: str, mode: str) -> "CancelReceipt": ...

class AIProvider(Protocol):
    def analyze(self, context: "ContextEnvelope") -> "RawModelResponse": ...
    def healthcheck(self) -> "ProviderStatus": ...

class EvidenceSource(Protocol):
    def fetch(self, asset_ids: Sequence[str], as_of_utc: str) -> Sequence["EvidenceItem"]: ...
```

`BrokerTrade`는 LLM으로 전달·노출하지 않는다. 구현 시 도메인 값 클래스, typed exceptions, DB 저장 형식은 실제 Pydantic v2 모델로 정의하고 스키마 테스트를 둔다.

## C. 주요 DTO 정의
| DTO | 필수 필드 | 검증 포인트 |
|---|---|---|
| `Asset` | asset_id, symbol, market, venue, type, currency, is_leveraged, trading_enabled | 카테고리 검증과 거래소 코드 매핑 |
| `Quote` | asset_id, bid, ask, last, as_of_utc, source, is_delayed | bid<=ask, 양수, freshness, 장 상태 |
| `PortfolioSnapshot` | snapshot_id, observed_at_utc, cash_by_ccy, positions, cash_available_by_ccy, account_alias, source | KIS 원본·모드, 원장과 불일치 시 차단 |
| `Position` | asset_id, quantity_decimal, cost_basis_decimal, ccy | 보유수량과 평가금액 구분 |
| `EvidenceItem` | id, asset_ids, source_url, publisher, published_at_utc, retrieved_at_utc, text_excerpt, content_hash | 출처·사실과 요약 구분, 중복 제거 |
| `InvestmentThesis` | id, asset_id, version, horizon_days, premise, invalidation, status, last_evidence_ids | 변경 전 원본 영구 보존 |
| `AgentRun` | run_id, mode, started_utc, state_version, provider, model, completed_utc, result_status | 중복/중단/오류 상태 |
| `ContextEnvelope` | schema_version, run_id, state_version, as_of_utc, mode, allowed_universe, normalized_portfolio, active_theses, evidence, constraints | 계좌번호·키 금지, schema 버전 검사 |
| `DecisionProposal` | schema_version, run_id, state_version, as_of_utc, action, items, rationale, evidence_ids | 액션 enum/근거/허용 유니버스/비율 |
| `OrderIntent` | intent_id, decision_id, asset_id, side, desired_qty, limit_price, currency, mode, idempotency_key | AI가 직접 생성 불가, 금액·수량 검증 완료 이후 생성 |
| `BrokerOrder` | broker_order_id, intent_id, order_status, ordered_qty, filled_qty, remaining_qty, last_update_utc | 체결 상태 확인/부분체결 |
| `CashFlow` | type(DEPOSIT/WITHDRAWAL/FX/FEE/DIVIDEND/etc), value, currency, timestamp, external_id | 수익률 계산에서 입금 제외 |

## D. 모델 입력·출력 JSON
- 원문 예시는 `schemas/context_envelope.schema.json`, `schemas/decision_proposal.schema.json`을 **유일한 기계 검증 원본**으로 사용.
- `NO_TRADE`는 종목별 `HOLD`와 달라 **이번 실행에서 어떤 신규 주문도 하지 않는 전역 판단**이다.
- `TRADE`일 때 `items[].side`는 BUY/SELL, `target_weight_bps`는 해당 종목의 목표 포트폴리오 비중(0~10000 basis points). SELL 0이면 전량 매도 의도. 현재 보유를 유지하려면 해당 종목을 `items`에서 생략. 나머지 100%는 현금/기존 보유로 남음. **미표시 종목을 자동 전량 매도하지 않는다.**
- BUY/SELL은 위험 검증기에서 원화/달러 가용 현금, 환전 상태, lot size, 수수료를 반영해 정량 `OrderIntent`로 변환. 목표보다 현재 보유비중이 큰데 BUY인 제안 등 모순은 거부.
- `items`에 없는 종목은 명시적으로 `HOLD`와 동일. 모델이 없는 자산을 주문하지 못하도록 allowlist 검사.
- 여러 종목을 포함한 경우 주문별 수량 결정 전에 전체 주문 예상 현금 예약(보유 현금 공유)이 필요. BUY 주문이 여러 개여도 총한도 초과 금지.
- `confidence`는 모델 자기평가일 뿐 확률로 표현/검증하지 않음. schema에는 자율 판단 근거가 명확하도록 `rationale`, `thesis_updates`, `evidence_ids` 기록.

## E. SQLite 최소 테이블과 키
구현은 `migrations/001_init.sql`, `002_ai_state.sql`로 나눔. 아래 필드는 초기 필수이며 후속 확장은 마이그레이션으로만 변경.

| 테이블 | PK/유니크 | 핵심 필드 |
|---|---|---|
| `app_config_versions` | version | config_hash, updated_at, changed_by |
| `assets` | asset_id | market, venue, symbol, type, currency, leveraged, eligibility_status |
| `allowlist` | (asset_id, config_version) | enabled, verified_at |
| `account_snapshots` | snapshot_id | mode, as_of_utc, data_json, external_hash |
| `quotes` | (asset_id, as_of_utc, source) | bid, ask, last, delayed |
| `evidence` | evidence_id | asset_ids_json, source_url, published_at, fetched_at, source_hash |
| `theses` | (thesis_id, version) | asset_id, status, premise, invalidation_json, evidence_ids_json |
| `strategy_state` | version | created_at, active_thesis_ids_json, hypothesis_digest, last_run_id |
| `handoffs` | snapshot_id | state_version, provider, run_id, context_json, checksum |
| `agent_runs` | run_id | state_version, mode, provider, model, input_hash, result, failure_reason, timestamps |
| `decisions` | decision_id | run_id, proposal_json, evidence_ids_json, state_version, schema_valid |
| `risk_checks` | id | decision_id, check_code, passed, actual, limit_value, reason |
| `order_intents` | intent_id | decision_id, mode, asset_id, qty, ccy, idempotency_key UNIQUE, status |
| `broker_orders` | local_order_id | intent_id, broker_order_id, mode, status, created_utc, updated_utc |
| `fills` | (broker_order_id, fill_id) | qty, price, ccy, fee, tax, filled_at |
| `cashflows` | cashflow_id | type, amount, currency, timestamp, broker_ref |
| `model_usage` | run_id/provider/model/seq | latency, input_tokens, output_tokens, call_count, failure, estimated_cost |
| `evaluations` | eval_id | start, end, baseline, twr, mdd, cost, method_version |
| `runtime_locks` | singleton | acquired_at, pid, heartbeat (선택적 OS 락 병행) |

`order_intents.idempotency_key`는 중복 재시도 방지. SQLite WAL + foreign_keys ON + transaction 사용. 모든 주문 상태 전이는 append-only 감사 기록 (`order_events`)에도 적는다.

## F. 데이터 보안·비밀관리
- `.env`/`settings.local.yaml`/`data/`는 `.gitignore`에 포함.
- DB에 **실제 계좌번호와 인증 토큰 저장 금지**. 계좌 별칭(예: `KIS_PRIMARY`)만 저장. 계좌 매핑은 로컬 보호 설정에만 존재.
- 원격 LLM에는 가격, 뉴스·공시, 익명화한 포트폴리오 비중 등만. 정확한 원화/달러 잔고·실보유 주식수·HTS ID·인증 메타데이터 제거.
- 로그/리포트에 계좌정보, 원문 HTTP 인증 header 기록 금지. `doctor`에서도 단지 `configured: true/false`만 표시.
- 뉴스·공시 텍스트는 신뢰할 수 없는 외부 콘텐츠. 시스템 프롬프트나 주문 도구 설정을 바꾸는 명령으로 처리하면 안 된다.
