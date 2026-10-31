# 개인용 AI 자율투자 시스템 — 마스터 개발 명세서

- 문서 버전: 1.1
- 기준일: 2026-10-31
- 상태: 설계 기준 / 실제 API 및 실거래 검증 필요
- 대상 독자: OpenRouter 기반 코딩 에이전트 및 프로젝트 소유자

## 0. 에이전트에게 가장 중요한 지시

1. **OpenRouter는 개발을 수행하는 코딩 에이전트 환경**이다. 실제 투자 AI는 특정 기업에 고정하지 않으며, NVIDIA NIM 등 여러 무료 추론 API 및 로컬 Ollama 중 선택한다. 투자 기억·정책·전략 상태는 LLM 공급자가 아닌 로컬 저장소가 소유한다.
2. 개인 1인용 **로컬 Windows 투자 실험 프로젝트**다. 회원가입, 공개 배포, 구독, 광고, 화려한 웹 프런트엔드는 불필요하다.
3. 구현 우선순위: 올바른 주문/체결/자금 관리 > 재시작과 오류 복구 > 기록과 평가 > 투자 AI > UI.
4. **국내/미국 시장 선택**은 반드시 구현한다. 상품 종류별 API의 실제 지원·모의투자 가능 범위는 검증 전까지 임의로 가정하지 않는다.
5. 자율적 투자를 목표로 한다. AI는 매수, 매도, 유지, 아무 거래도 하지 않음, 현금 100% 보유를 선택할 수 있다. 사용자가 고정 투자 비중·매매 빈도를 강요하지 않는다.
6. **신용·미수·대출·차입 주문은 불허**한다. 파생상품 주문은 초기 실거래 구현 범위에서 제외한다. 레버리지 ETF는 향후 지원 가능한 상품 분류로 두되 초기 기본 차단, 수동 허용 설정과 적합성 검토 없이는 거래 불가.
7. AI 출력은 **주문 권한이 없는 구조화된 제안**이다. 실주문은 안전검증기와 주문 엔진만 실행할 수 있다. LLM에 API 키·인증 토큰·계좌번호를 전송하지 않는다.
8. 실거래는 **기본 비활성화**. `BACKTEST` → `PAPER` → `LIVE`의 분리된 모드를 구현한다. 라이브 전환은 소유자의 명시적 로컬 조작과 통합 테스트 완료를 요구한다. 자동 승격 금지.
9. 기존 KIS 공식 코드와 테스트 검증된 라이브러리를 재사용하되, 샘플의 실주문 경로를 검토 없이 실행하지 않는다.
10. 이전 설계나 코드와 충돌하면 이 문서를 우선 적용하고 충돌을 `docs/OPEN_QUESTIONS.md`에 기록한다. 외부 계정 자격증명 또는 실제 주문에 관해 임의로 가정하지 말 것.

## 1. 목표와 범위

### 목표
- 사용자가 허용한 투자 시장 및 종목 목록 내에서 AI가 스스로 시장 정보 수집, 분석, 투자 가설 구성, 보유/매수/매도 의사결정을 수행한다.
- 거래는 **입금되어 사용 가능한 현금 및 실제 보유 자산** 범위에서만 시행한다. 수익 보장이나 거래 횟수 목표는 없다.
- 모든 판단을 저장하고 KOSPI/KOSDAQ 및 적절한 미국 시장 지표/ETF 단순 보유 전략 등과 동일 기간·통화·비용 가정하에 비교한다.
- 특정 추론 API에 종속되지 않는 모델-중립 실행 구조를 우선하며, NVIDIA NIM 등 무료 원격 API·로컬 Ollama를 공통 인터페이스로 교체한다. 모바일 Gemma는 후속 확장이다.

### 비목표
- 타인 자산 운용, 신호 판매, 배포용 SaaS, 대시보드 디자인 고도화
- 자동으로 투자자 성향을 모방하거나 모든 현금을 강제로 투자하는 전략
- 실거래 전 고빈도 매매 / 초단타 / 마진 / 선물옵션 / 레버리지 주문 기본 허용
- API 데이터가 없는 자산을 허위로 지원 표시

## 2. 확인된 공식 기반 및 조사 결과

- KIS Developer Portal: https://apiportal.koreainvestment.com/intro
- KIS 공식 저장소: https://github.com/koreainvestment/open-trading-api
- KIS LLM용 탐색 문서: https://github.com/koreainvestment/open-trading-api/blob/main/llms.txt
- KIS 통합 예제: `examples_user/`; 단일 API 예제: `examples_llm/`
- KIS Strategy Builder: https://github.com/koreainvestment/open-trading-api/tree/main/strategy_builder
- KIS Backtester (QuantConnect Lean + Docker): https://github.com/koreainvestment/open-trading-api/tree/main/backtester
- KIS 공식 도구는 국내/해외 주식과 장내채권·ETF 관련 API를 분류해 제공한다. **각 상품에 대한 실주문·모의주문 지원을 개별 검증**할 것.
- 한국투자증권 일부 국내주식 재무분석 API 7종은 2026-11-11 종료 예정. 이에 의존하는 신규 구현 금지.
- 무료 원격 LLM 후보 중 하나인 NVIDIA NIM: https://docs.api.nvidia.com/nim/docs/product , https://docs.api.nvidia.com/nim/docs/run-anywhere . API별 무료 한도·지속성·데이터 처리 정책·모델 제공 여부는 각각 확인한다. 특정 공급자는 기본 필수 의존성이 아니다.
- Freqtrade protections 참고: https://github.com/freqtrade/freqtrade/blob/develop/docs/includes/protections.md . Cooldown, StoplossGuard, MaxDrawdown 등 설계만 벤치마킹하며 암호화폐 코드를 주식 거래에 무단 전용하지 않는다.

## 3. 기술 스택

- Python 3.11+, `uv` 또는 표준 venv, `pytest`, `ruff`, type hints, `pydantic`/dataclasses, `httpx`, `pandas`, `sqlite3`(초기), YAML/TOML 설정.
- 로컬 Windows: Windows Task Scheduler 또는 안정적인 단일 프로세스 스케줄러. 중복 인스턴스 실행 방지용 프로세스 락 필요.
- Broker: `KisBroker` (공식 KIS 인증/시세/잔고/주문 예제 재사용).
- LLM: 공통 `AIProvider` 프로토콜과 `NvidiaNimProvider`, `OpenAICompatibleProvider`(지원되는 무료 API별 설정), `OllamaProvider`, 추후 `AndroidGemmaProvider`. API URL·모델·제약은 구성 파일로 선택한다. 투자 상태는 어떠한 Provider에도 저장하지 않는다.
- UI: 기본 CLI, 로그, `status`/`orders`/`portfolio`/`runs` 명령. 필요 시 최소 Streamlit 로컬 UI를 2차 구현. 외부 인터넷에 포트 노출 금지.
- 비밀정보: OS 사용자 계정의 안전한 비밀 저장소 또는 환경변수/깃 제외 파일. 콘솔·LLM 프롬프트·DB 로그에 secret 절대 기록 금지. 공식 샘플 YAML에 키를 평문 커밋하지 말 것.

## 4. 구성 모듈

```text
main.py / cli.py
config/                     # 사용자 정책, 시장 및 AI 공급자 설정
src/broker/base.py          # Broker 인터페이스
src/broker/kis.py           # KIS 운영·모의 계정 별도 설정
src/data/market.py          # 종목/가격/거래시간/통화
src/data/news.py            # 공개뉴스·공시, 출처·수집시각 추적
src/analysis/indicators.py  # Python 정량 지표
src/ai/base.py              # 모델 독립 호출 및 구조화 출력
src/ai/nvidia.py            # 선택형 NVIDIA NIM API
src/ai/openai_compatible.py # 다른 호환 무료 추론 API
src/agent/context.py        # 모델 중립 투자 상태/컨텍스트 생성
src/agent/handoff.py        # 모델 교체 인수인계 및 상태 버전 확인
src/storage/state.py        # 영속 전략/가설/미결 과제 저장
src/ai/ollama.py            # 로컬 LLM
src/agent/research.py       # 조사 계획, 출처, 증거
src/agent/decision.py       # 투자 가설과 의사결정
src/risk/validator.py       # AI 외부 독립 안전 검증
src/execution/orders.py     # 주문·취소·체결 확인·재시도
src/runtime/scheduler.py   # 정기 실행·중복 실행 방지
src/storage/database.py     # SQLite, 트랜잭션 기록
src/evaluation/metrics.py  # 성과 비교
src/monitoring/status.py    # 실행 상태·오류·킬스위치
scripts/                   # 진단/모의 실행/리포트
 tests/                     # 단위·통합·모의 API·장애주입 테스트
 docs/                      # 개발 로그, API 지원 매트릭스, 미결사항
```

## 5. 핵심 데이터 모델 (제안)

- `assets`: ticker, venue(KRX/US), asset_type(stock/ETF/bond), currency, tradable, leverage_flag, eligibility_verified_at.
- `universe`: 사용자 허용 시장, 거래 허용 종목, 거래 불허 종목, 실험별 설정 버전.
- `portfolio_snapshots`: timestamp, account_alias, currency, cash, positions, FX rate, source, data_freshness.
- `market_snapshots`: OHLCV, quote timestamp, source, timezone, split/dividend adjustment, price freshness.
- `research_items`: url/source, published_at, fetched_at, market, ticker, factual_summary, dedup_key.
- `agent_runs`: run_id, scheduled_for, started_at, completed_at, AI provider/model/version, input fingerprint, mode, status, errors.
- `investment_theses`: ticker, horizon, rationale, entry assumptions, invalidate_conditions, created_at, version, status, last_reviewed_at.
- `strategy_state`: strategy_id, version, investment_objective, eligible_universe, cash_policy, risk_budget, active_thesis_ids, open_questions, last_decision_id, updated_at. AI의 비전략 안전 제약과 구분.
- `handoff_snapshots`: snapshot_id, schema_version, state_version, created_at, source_run_id, context_digest, snapshot_json, checksum.
- `provider_evaluations`: provider, model, run_id, schema_valid, groundedness, disagreement, latency_ms, estimated_cost, handoff_success, status.
- `decisions`: run_id, ticker, action(BUY/SELL/HOLD/NO_TRADE), target_allocation_or_quantity, confidence_not_guaranteed, evidence refs, analysis_timestamp, reason.
- `risk_checks`: decision_id, pass/fail, constraint, actual_value, threshold, reason.
- `orders`: idempotency_key, environment, client_order_id, broker_order_id, status, requested_qty, filled_qty, average_fill, fees, currency, retries, timestamps.
- `transactions`: fills, fees, taxes, FX, cash flows, broker reconciliation status.
- `evaluations`: model, scenario, baseline, interval, return, max_drawdown, cost, volatility, error classification.

### 출력 포맷

모든 AI 출력은 JSON schema 검사; 허용된 enum·범위 외 출력 시 신규 주문 금지. 필드 예:

```json
{
  "market": "KRX",
  "ticker": "005930",
  "action": "NO_TRADE",
  "target_weight_pct": 0,
  "horizon_days": 30,
  "thesis": "정보 불충분으로 신규 진입 보류",
  "evidence_ids": ["market_snapshot_001"],
  "invalidation_conditions": ["new_earnings_data"],
  "data_as_of": "2026-10-30T15:30:00+09:00"
}
```

`target_weight_pct`는 판단 제안일 뿐 현금이나 수량의 권한이 아니다. 주문 가능 수량은 주문 검증기에서 계산.

## 6. 사용자 설정 및 시장 구분

```yaml
mode: PAPER                 # BACKTEST | PAPER | LIVE ; 기본 PAPER
markets:
  KRX: true
  US: true                  # 두 시장 독립 거래 캘린더 및 시간대
asset_types:
  stocks: true
  etfs: true
  domestic_bonds: false    # KIS 주문/모의 지원 검증 후 활성화
  foreign_bonds: false
account:
  broker: KIS
  cash_only: true
  allow_margin: false
  allow_short: false
  allow_derivatives: false
  allow_leveraged_products: false
universe:
  allowed: []              # 비어 있으면 신규 매매 없음
  allow_ai_new_assets_without_approval: false
scheduler:
  enabled: false           # 설정·인증·테스트 완료 후 사용자 활성화
  max_runtime_minutes: 10
  interval_minutes: 60
ai:
  provider: choose_at_runtime   # nvidia / compatible_free_api / ollama
  fallback_provider: ollama     # 사용자가 활성화한 경우에만
  model: "SET_AFTER_ACCOUNT_VALIDATION"
  max_requests_per_day: 20
  max_retries: 1
execution:
  allow_live_orders: false
  no_auto_upgrade_from_paper: true
  require_fresh_quote: true
  kill_switch: true
  max_new_order_notional: null  # 필수 사용자 확인 후 live 설정
  max_daily_loss: null         # 실거래 활성화 전 정책 확정
```

- `KRX`/`US`는 on/off 각각 가능하며 둘 다 켜면 개장 시간, 거래일, 휴장, 서머타임, 정규장·시간외 주문 정책을 따로 계산한다.
- 유동성 부족, 주문 불가능 최소 수량, 해당 증권사 소수점 주문 미지원, 환전비용이 예산을 초과하면 거래하지 않는다.
- `allowed: []`은 AI가 모든 종목을 거래할 권한을 의미하지 않는다.
- 계좌 현금과 외부 입금은 별도 분리하여 성과 평가에 반영한다. 손익과 추가 입금이 혼동되지 않도록 시간가중수익률(TWR), 현금흐름과 연동한 지표를 기록한다.

## 7. 조사→판단→주문 상태 기계

1. `SCHEDULED` — 실행 시각 도래; 단일 실행 락 확보.
2. `SYNC_ACCOUNT` — 증권사 실제 계좌/미체결 주문 상태와 DB 대조. 불일치하면 신규 주문 중지.
3. `CHECK_MARKET` — 시장별 개장·거래 가능 여부; 해당 환경의 상품 지원 확인.
4. `COLLECT` — 시세·뉴스·공시 등 출처·시점 포함 데이터 확보. 기사 원문 재배포 및 무허가 크롤링 지양.
5. `ANALYZE` — 정량지표를 Python으로 계산; LLM은 명시적으로 제공받은 사실만 이용하여 투자 가설·행동 후보 생성.
6. `VALIDATE_DECISION` — JSON 검증, 기사 지시문(prompt injection) 방어, 근거 유효성 검증, 데이터 신선도.
7. `RISK_GATE` — 사용자 허용 종목, 현금·기존 포지션, 중복주문, 제한 상품, 손실·노출 한도, 수수료·슬리피지 검증.
8. `PLACE_ORDER` — PAPER 모의주문 먼저, LIVE는 별도 활성화. 주문 요청 전에 idempotency key 저장.
9. `RECONCILE` — 주문 조회로 상태 확인, 미체결·부분체결·취소·거절 처리. 네트워크 타임아웃 시 무조건 재주문 금지.
10. `JOURNAL` — 조사·판단·검증·주문 결과·비용·예외 모두 기록.
11. `EVALUATE` — 사후 성과 및 벤치마크 비교, 과거 가설 재검토.
12. `WAIT` — 다음 예약. 중복 예약은 병렬 실행 대신 건너뛰거나 큐잉 정책에 따라 처리.

#### 장애 상태 원칙
- AI API 실패·JSON 오류·비정상 데이터·시장 미개장·미체결 확인 불가: 신규 주문 `NO_TRADE` 또는 `BLOCKED`.
- 별도 손실 방어 모듈이 활성화된 경우 이 모듈은 AI 스케줄과 무관하게 동작하며, PC 종료 시 보호가 지속되는지 KIS 주문 API 지원 확인 필수.
- 로컬 모델 자동 fallback은 가능하나 **대체 모델이 이전 AI의 주문을 무비판적으로 반복하지 않도록** 현재 잔고·미체결 재조회 수행.
- 프로그램이 PC 재부팅 뒤 실행되면 중단됐던 주문을 재생하지 않고 증권사 주문 상태 조회로 복구.

## 8. 리스크 제약: 자율성과 안전의 분리

### 필수 비전략 제약
- 현금 범위 내 현물 주문만, 신용·미수·차입 금지.
- 종목 허용 목록 및 상품 허용 분류.
- 주문 가능 금액·보유 수량·통화·환전·수수료·세금·거래 단위 검증.
- 중복 주문 방지, stale quote 방지, 주문 확인 오류 시 fail closed.
- LIVE 활성화와 긴급 중지, 로그 감사 추적, KIS 비밀정보 격리.
- 연쇄 오류·일일 손실 등 실거래 보호 한도를 사용자와 확정하기 전에는 실거래 활성화 금지.

### AI 자율 전략 결정
- 매매 횟수, 조사 주제, 매수/매도/보유/거래 없음, 현금 비중 0~100%, 투자 가설 및 포지션 보유 기간.
- 거래 비용을 고려한 판단은 AI에게도 제공하되 프로그램이 주문 경제성/정상성 검증.
- 고정 RSI 문턱 등 특정 알파 전략 강제 금지. 지표는 참고 정보로 제공.

### 소액 실험 중요 조건
- 최소 주문 가능 수량, 소수점 주문 지원, 환전 비용, 시장별 거래시간에 따라 특정 자산은 실질적으로 구매 불가할 수 있음.
- 소액에서는 수수료와 최소 거래금액이 수익을 압도할 수 있으므로 수수료/비용이 큰 주문은 거부하도록 구성.
- 당일 실거래 손실 한도를 두더라도 갭하락/시장 급변에서 그 한도 내 손실을 보장할 수는 없음.

## 9. 공급자 중립 AI 추론과 로컬 추론

- NVIDIA NIM은 **여러 선택 가능한 무료 API 중 하나**일 뿐이다. 특정 무료 API의 무제한·지속 제공 또는 동일 모델의 지속 가용성을 가정하지 않는다.
- `AIProvider`는 공급자 독립 인터페이스 `analyze(context_envelope) -> decision_proposal`만 제공한다. API 키, 모델, 타임아웃, 호출량 및 무료 한도는 Provider 설정에서 분리 관리한다.
- `NvidiaNimProvider`, `OpenAICompatibleProvider`, `OllamaProvider`는 동일한 입력 컨텍스트와 동일 출력 JSON Schema를 사용한다.
- API/모델 교체는 **기존 투자 기억과 전략을 초기화하는 이벤트가 아니다**. 교체 시 현재 계좌·미체결주문·시장데이터를 재조회하고, 로컬 상태 스냅샷과 활동 중인 투자 가설을 새 모델에 전달한다.
- Provider별 모델의 강약에 따른 판단 차이는 있을 수 있으므로 **행동의 완전 동일성은 보장할 수 없다**. 변경 전후 모델명·입력 버전·결정·차이·성과를 기록한다.
- 제공 경로 비교시 모델 이름/버전/입력 시점/컨텍스트·지표·생성 응답 저장; 사후 수정하지 않는다.
- API 제공자에게 계좌번호·본명·토큰·주문 인증 데이터 금지. 외부 모델에는 공개 시장 데이터 및 개인을 식별할 수 없는 포지션 비중만 제공.
- 시장에 영향을 주는 공시·뉴스는 기사 본문을 직접 명령으로 취급하지 않고 출처가 표시된 자료로만 취급한다.
- `AndroidGemmaProvider`: 후속 탐색/플러그인 단계. Android 백그라운드 제약과 앱 간 모델 접근 가능 여부 검증 전까지 자동 주문 실행 경로에 연결 금지.


## 9A. 모델 교체와 인수인계 — 필수 설계 원칙

### 9A-1. 모델과 투자자의 상태를 분리

- LLM API는 **일회성 판단 엔진**으로 취급한다. 이전 호출을 기억한다고 기대하지 않는다.
- **프로그램과 로컬 DB가 지속되는 투자자 상태의 유일한 기준(source of truth)**이다. 어떤 Provider가 변경돼도 전략, 포지션, 미결 주문, 과거 가설, 실험 설정은 유지된다.
- `AIProvider`는 계좌·주문을 직접 읽거나 변경하지 못한다. 로컬 `ContextBuilder`가 최소 필요 데이터만 선택하여 전달한다.
- 구독형 모델의 `conversation_id`, 캐시 또는 공급자 고유 기억에 투자 연속성을 의존하지 않는다.

### 9A-2. 매 호출에 제공하는 표준 컨텍스트 봉투 (`ContextEnvelope`)

```json
{
  "schema_version": "1.0",
  "run_id": "example_run",
  "mode": "PAPER",
  "state_version": 17,
  "as_of": "2026-10-31T09:00:00+09:00",
  "policy": {"allowed_markets": ["KRX", "US"], "cash_only": true},
  "portfolio": {"cash_ratio": 0.55, "positions": []},
  "open_orders": [],
  "active_theses": [],
  "previous_decisions": [],
  "new_market_evidence": [],
  "unresolved_questions": [],
  "allowed_actions": ["BUY", "SELL", "HOLD", "NO_TRADE"]
}
```

- `as_of`, 시세 및 근거의 관측시각, `state_version`, 근거 ID 필수. 사용자 식별자·계좌번호·키는 전달 금지.
- 과거 대화 전문이 아니라 **현재 검증된 상태 + 활성 가설 + 필요한 최근 이력 + 새로운 시장 사실**을 제공한다. 오래된 요약은 원본과 연결되도록 ID/출처를 보존한다.
- 중요한 투자 가설/무효화 조건/열린 과제는 단순 요약 중에 삭제하지 않는다. DB에는 원본과 변경 이력을 유지한다.

### 9A-3. 판단 결과·상태 변경 절차

1. 스케줄러는 로컬 상태를 읽고 한국투자증권 잔고·미체결 주문을 재확인한다.
2. `ContextBuilder`는 동일 스키마의 컨텍스트를 만들어 어느 모델에나 전송한다.
3. 모델은 `DecisionProposal`(행동 제안, 근거 ID, 기존 가설 유지/수정/폐기 제안, 불확실성)을 반환한다.
4. 스키마·상태 버전·근거·안전 검증 통과 전에는 상태를 확정하거나 주문하지 않는다.
5. `StateReducer`가 **트랜잭션 안에서** 버전 충돌을 확인하고 투자 가설과 활동 로그를 갱신한다. 실행된 주문과 실제 체결은 별도 원장에 기록한다.
6. 모델을 바꾼 직후 `handoff_snapshots`와 실제 계좌 상태를 대조한다. 충돌 시 신규 주문 없이 검토 상태로 둔다.

### 9A-4. 장애 및 변경 정책

- 무료 API가 한도 초과·중단되면 사용자가 설정한 다른 Provider로 **동일한 상태 버전**을 전달할 수 있다. 대체 모델이 없으면 `NO_TRADE`.
- 전략 변경은 공급자 교체만으로 자동 발생하지 않는다. 판단이 바뀌면 변경 근거, 신규 사실, 이전 가설과의 관계를 명시한다. **AI 자체의 자율적 전략 수정은 허용**하되, 추적 가능해야 한다.
- 오래된 상태 스냅샷으로 주문 실행 금지. 가격·잔고·미체결 주문은 실행 직전에 다시 검증한다.
- 가상환경에서 모델 A→B→A 교체, API 실패 후 복구, 요약 압축, 긴 문맥 잘림, 재시작, DB 버전 충돌을 자동 테스트한다.

### 9A-5. 모델 품질과 일관성 검증

- 동일 시장 상태 스냅샷을 여러 모델에 주고, 출력 스키마 통과율, 근거 충실도, 이전 가설과의 정합성, 주문 유효성, 재현성, 호출 비용을 기록한다.
- **같은 생각을 강제하지 않는다**. 서로 다른 모델은 다른 전략을 제안할 수 있으며, 그 차이는 가설·근거·성과로 비교한다.
- 평가 점수가 낮은 Provider는 자동으로 실거래에 투입하지 않는다. Provider 교체가 실제 자본에 영향을 줄 때는 모의환경 검증을 우선한다.

## 10. 성능 검증·백테스트

- 초기 기준선: 동일 상품 단순 보유, 정기매수 또는 시장별 대표지수/ETF. 비교 기간·통화·현금흐름 동일하게 맞춘다.
- 기록: 수익률, TWR, MDD, 샤프 또는 변동성, 실현/미실현 손익, 환전/세금/수수료/슬리피지, 승률, 평균 보유기간, 거래 횟수, 거래 없는 이유, LLM 호출량, 실패율.
- 과거 데이터 백테스트 시 미래 정보 유출, 생존편향, 뉴스 발표 시점 오류, 거래비용 누락 금지. AI가 과거에 실제 접근할 수 없던 뉴스/LLM 지식을 소급하여 사용한 성과는 실전 예측력 증거로 보지 않는다.
- PAPER 여러 주 검증, 비정상주문=0, 복구테스트 통과, 장중/장마감 주문 구분, 명시적 한도 설정 후에만 LIVE 활성화.
- 라이브 성과는 시장 가격뿐 아니라 실제 거래 체결 자료와 입출금 기록 기준으로 계산.

## 11. 기능 우선순위와 수용 기준

### Phase 0 — API/라이선스 사실 확인
- KIS 공식 주문 API별 상품 및 모의투자 지원, 인증, 조회, 주문 가능 시간 문서 확인.
- 무료 API 후보(NVIDIA 포함)의 지원 모델·한도·약관·데이터 정책 확인. 해당 공급자는 선택 사항이며 미확인 사항은 `NEEDS_USER_VERIFICATION` 표시.
- 프로젝트 README에 확인 날짜/근거 URL/미확정 사항을 남긴다.

### Phase 1 — READ-ONLY
- KRX/US 선택, 허용 종목 목록, 계좌 잔고, 시세 조회, SQLite 저장.
- 주문 API는 코드 실행 경로에서 완전히 비활성화.
- 수용 기준: 한국·미국 데이터 구분, UTC+시장 현지시각, API 실패시 오류 표기, 로그에 비밀 미출력.

### Phase 2 — SIMULATION
- MockKisBroker, 주문 상태 기계, 오류/부분체결/재시작 복원, 현금 원장, 신용/미수 주문 거부.
- CLI에서 `simulate`로 가상 거래. 모든 경우 동일 현금을 이중 지출하지 않아야 함.
- 수용 기준: 중복 주문·timeout·partial fill·중복 스케줄 테스트 자동 통과.

### Phase 3 — AI ANALYSIS
- 임의의 지원 Provider → 공통 상태 컨텍스트 → 정형 AI 결정 JSON → 스키마 검증 → 가상 거래.
- 동일 계좌 상태·시장 스냅샷·투자 가설을 그대로 유지하며 모델을 교체할 수 있어야 한다. AI 결정은 HOLD/NO_TRADE를 정상 결과로 인정.
- 모델 교체 직후 상태 누락/전략 재설정/기존 판단의 이유 없는 역전 여부를 모의 테스트로 검증한다.
- 수용 기준: 잘못된 JSON/프롬프트 인젝션/모델 실패에서 신규 주문 0건.

### Phase 4 — KIS PAPER
- 공식 KIS 모의환경과 조회/주문/체결 재확인. 모의 지원 종목을 별도 목록으로 유지.
- 수용 기준: 모의 주문·조회·취소 및 재시작 후 동기화 검증.

### Phase 5 — REPORTING & SCHEDULER
- Windows 스케줄러, 단일 인스턴스, 시장 개장 캘린더, 최소 CLI 상태 보기, 일일 리포트.
- 수용 기준: PC 재시작 뒤 중복 주문 없음; 새 입금이 손익으로 계산되지 않음.

### Phase 6 — LIVE GATE (승인 필요)
- 사용자 설정 `max_new_order_notional`, 손실/노출 보호 정책, 실거래 전환 절차, 실주문 확인.
- 수용 기준: 명시적 실제 주문 테스트 승인 없으면 실거래 주문 0건. **이 문서만으로 실거래를 자동 활성화하지 않는다.**

### Phase 7 — EXTENSIONS
- 국내채권, 해외채권(실제 API 확인), 선택적 레버리지 ETF, Android Gemma E2B, 최소 로컬 UI.

## 12. 에이전트 구현·검수 규칙

- **코딩 에이전트는 각 Phase마다** 계획 → 소규모 구현 → 자동 테스트 → 변경파일·미해결문제 보고.
- 공식 예제의 경로·버전·사용 API·오류코드와 근거를 명시하고 근거 없는 API 필드/거래소 코드/모의주문 지원을 만들어내지 않는다.
- 모든 거래 코드는 모의/실거래 구현을 구분하는 명시적 타입·설정과 통합 테스트가 있어야 한다.
- 테스트 결과를 생성하거나 성공했다고 허위 보고하지 않는다. API 인증이 없으면 Mock으로만 검증하고 `not verified`라고 기록한다.
- Git 로컬 커밋은 테스트 통과 뒤 수행 가능. 원격 push/실제 거래 실행/실거래 활성화는 사용자 승인이 필요.
- 코드와 문서는 최신 단일 기준으로 유지. 날짜별 변경 노트는 archive 가능.
- 초기에는 React/Next.js·로그인·회원가입·결제·클라우드 서버를 구현하지 않는다.

## 13. 미확정 및 검증 필요

1. 한국투자증권 API 사용자 인증키 발급, 모의 계좌 사용 가능 여부, 해당 계좌 거래 권한.
2. KRX/US 각 상품별 최소 주문 단위, 소수점 주문 가능 범위, 환전 및 수수료 산정.
3. 국내 장내채권과 해외 개별채권의 실주문/모의거래 지원 여부.
4. 실거래 허용 손실 한도와 최대 신규 주문 금액의 구체적인 값(실거래 전 결정 필수).
5. 선택할 무료 추론 API들(NVIDIA 포함)의 무료 모델·요청 한도·서비스 지속성·데이터 정책.
6. 사용할 공개 뉴스·공시 제공자 및 이용 약관. 공식 공시/기관 자료 우선.
7. 휴대폰 Gemma E2B의 앱 간 API 및 안정적인 백그라운드 호출 가능 여부.
8. PC 전원 종료 중 기존 주문 보호 정책 및 증권사 서버단 주문 지원 여부.
9. 투자 가능 상품을 사용자가 선택할지, 이후 AI의 후보 발굴을 제안 목록으로만 둘지.

## 14. 초기 CLI 명령안

```text
invest doctor                  # 환경/설정/키 존재 여부 확인 (키 값 출력 금지)
invest markets                 # 시장별 개장 여부
invest portfolio               # 잔고와 포지션
invest universe list           # 거래 허용 종목 목록
invest universe add KRX 005930
invest universe add US VOO
invest run --mode research     # 조사/분석만
invest run --mode simulate     # 가상 주문
invest run --mode paper        # KIS 모의 환경 주문
invest report --days 30       # 성과/모델/수수료 비교
invest status                  # 현재 실행 상태
invest stop                    # 신규 주문 비활성화
# LIVE는 별도 승인 절차 구현 후에만 가능
```

## 15. 코딩 에이전트에게 첫 번째 작업 요청

> 이 문서 내용을 기준으로 **Phase 0과 Phase 1만 먼저 구현**한다. 공식 KIS 저장소의 `llms.txt`, `examples_llm`, `examples_user`를 우선 조사한다. 시장선택(KRX/US), 자산 허용 목록, 모의/실전 환경 분리, 읽기전용 계좌·시세조회, SQLite, 기본 CLI 및 테스트를 만든다. 실주문 코드는 실행하지 않는다. 특정 무료 모델에 종속시키지 말고 `AIProvider`와 상태 인수인계 계층의 인터페이스 및 Mock부터 준비한다. 마지막에 공식 API별 확인된 지원 범위, 실행한 테스트와 결과, 후속 Phase 계획, 검증되지 않은 사항을 정확히 보고한다.
