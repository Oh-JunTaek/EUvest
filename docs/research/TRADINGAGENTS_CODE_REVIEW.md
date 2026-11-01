# TradingAgents 코드 리뷰 (TRADINGAGENTS_CODE_REVIEW.md)

> **작성일**: 2026-11-01  
> **기준 저장소**: https://github.com/TauricResearch/TradingAgents  
> **커밋**: `c454491` (2026-10-31, v0.7.1)  
> **라이선스**: Apache-2.0  

---

## 1. 전체 아키텍처

### 1.1 멀티 에이전트 구조 (LangGraph 기반)

```
TradingAgentsGraph
├── Analysts (병렬)
│   ├── Market Analyst      → 가격/지표/스냅샷
│   ├── News Analyst        → 기업 뉴스/글로벌 뉴스
│   ├── Social Analyst      → StockTwits/Reddit 감성 (선택)
│   └── Fundamentals Analyst → 재무제표/SEC EDGAR/인사이더
├── Research Manager → 투자 계획 수립 (5단계 레이팅)
├── Risk Debate (Aggressive/Conservative/Neutral)
├── Trader → 3단계 액션 (Buy/Hold/Sell) + 사이징
└── Portfolio Manager → 최종 5단계 레이팅 결정
```

### 1.2 핵심 모듈 매핑

| 모듈 | 파일 | 주요 기능 | EUvest 재사용 가능성 |
|------|------|-----------|---------------------|
| 그래프 오케스트레이션 | `graph/trading_graph.py` | LangGraph 상태 기계, 체크포인트, 스트리밍 | 높음 (분석 파이프라인 구조 참조) |
| LLM 공급자 팩토리 | `llm_clients/factory.py` | 공급자별 클라이언트 생성, 티어(deep/quick) 분리 | 높음 (공급자 교체 패턴 채택) |
| 데이터 라우터 | `dataflows/router.py` | 벤더 체인(yfinance→Alpha Vantage), 폴백, 에러 처리 | 높음 (데이터 소스 추상화 패턴) |
| 메모리 로그 | `memory/log.py` | 마크다운 기반 결정 로그, 정산(settlement) | 중간 (EUvest SQLite와 별도 운영 필요) |
| 에이전트 스키마 | `agents/schemas.py` | Pydantic 구조화 출력 (ResearchPlan, TransactionProposal) | 높음 (EUvest DecisionProposal 매핑 가능) |
| 기본 설정 | `default_config.py` | 환경변수 오버라이드, 벤더 설정, 벤치마크 맵 | 높음 (설계 패턴 채택) |
---

## 2. LLM 공급자 지원 현황

### 2.1 지원 공급자 (factory.py 기준)

| 공급자 | 클래스 | Base URL | API 키 필요 | 비고 |
|--------|--------|----------|-------------|------|
| OpenAI | OpenAIClient | api.openai.com | O | Responses API 지원 |
| Anthropic | AnthropicClient | api.anthropic.com | O | tool_use 구조화 출력 |
| Google | GoogleClient | generativelanguage.googleapis.com | O | response_schema 지원 |
| Azure OpenAI | AzureOpenAIClient | 커스텀 | O | 엔터프라이즈 |
| Bedrock | BedrockClient | AWS | O | 선택적 의존성 |
| **OpenAI Compatible** | OpenAIClient (provider=*) | 커스텀 | 선택 | **Ollama, vLLM, LM Studio, OpenRouter, NVIDIA NIM, xAI, DeepSeek, Qwen, GLM, MiniMax, Groq, Mistral, Kimi** |
| ChatGPT | ChatGPTAuth | chat.openai.com | 쿠키 | 브라우저 인증 |

### 2.2 로컬 모델 (Ollama) 지원 확인

```python
# tradingagents/llm_clients/openai_client.py
OPENAI_COMPATIBLE_PROVIDERS["ollama"] = ProviderSpec(
    chat_class=LocalCompatibleChatOpenAI,  # tool_choice=None 강제
    base_url="http://localhost:11434/v1",
    base_url_env="OLLAMA_BASE_URL",
    key_optional=True,  # API 키 불필요
    placeholder_key="ollama",
    credential=None,
)
```

**검증 결과**: `qwen3.5:9b` 모델로 AAPL, 005930.KS 분석 성공 (2026-11-01 수행)

---

## 3. 데이터 소스 및 한국 주식 지원

### 3.1 데이터 벤더 체인 (router.py)

| 카테고리 | 기본 벤더 | 폴백 벤더 | API 키 필요 |
|----------|-----------|-----------|-------------|
| core_stock_apis (OHLCV) | yfinance | alpha_vantage | N / Y |
| technical_indicators | yfinance | alpha_vantage | N / Y |
| fundamental_data | sec_edgar | yfinance | N / N |
| news_data | yfinance | alpha_vantage | N / Y |
| macro_data | fred | - | Y (FRED_API_KEY) |
| prediction_markets | polymarket | - | N |

### 3.2 한국 주식 (KRX) 지원 현황

| 데이터 | 지원 여부 | 티커 형식 | 비고 |
|--------|-----------|-----------|------|
| **가격/지표 (OHLCV)** | ✅ | `005930.KS` | yfinance 지원 |
| **재무제표 (SEC EDGAR)** | ⚠️ 제한적 | - | 미국 상장사만 EDGAR 공시, 한국 기업은 제한적 |
| **기업 뉴스** | ❌ | - | Yahoo Finance 한국 뉴스 태깅 없음 |
| **글로벌 매크로 (FRED)** | ⚠️ 키 필요 | - | FRED_API_KEY 미설정 시 불가 |
| **벤치마크** | ✅ | `^KS11` (KOSPI) | `benchmark_map[".KS"] = "^KS11"` |

**검증 결과** (2026-11-01):
- `005930.KS` (삼성전자): 가격/지표/재무제표(손익계산서/현금흐름/대차대조표) 조회 성공
- 뉴스: Yahoo Finance에서 한국 기업 뉴스 없음 (글로벌 뉴스로 대체)
- FRED 매크로 데이터: API 키 미설정으로 불가
- Polymarket 예측 시장: 네트워크 오류로 불가
---

## 4. 메모리/상태 관리

### 4.1 TradingAgents 내부 메모리

| 저장소 | 형식 | 내용 | 용도 |
|--------|------|------|------|
| **Memory Log** | 마크다운 파일 (`memory_log.md`) | 결정(tag: date|ticker|rating|pending), 반성(reflection) | 백테스트 정산, 과거 결정 컨텍스트 주입 |
| **Checkpoint** | SQLite (langgraph-checkpoint-sqlite) | 그래프 중간 상태 | 중단 시 재개, 동일 run_id로 재실행 시 스킵 |
| **Results** | JSON/HTML (`results/{ticker}/`) | 전체 상태, 리포트 | 감사, 백테스트 평가 |

### 4.2 EUvest SQLite와의 연동 전략

| EUvest 테이블 | TradingAgents 데이터 | 연동 방향 |
|---------------|---------------------|-----------|
| `theses` | Research Manager의 투자 계획, 애널리스트 보고서 | EUvest ← TA (주입) |
| `decisions` | Trader/Portfolio Manager의 최종 결정 | EUvest ← TA (기록) |
| `agent_runs` | 실행 메타데이터, 시그널, 설정 | EUvest ← TA (기록) |
| `handoffs` | 모델 교체 시 컨텍스트 스냅샷 | EUvest → TA (주입) |
| `evidence` | 애널리스트 도구 호출 결과 | EUvest ← TA (기록) |

**핵심 원칙**: TradingAgents 메모리를 EUvest DB로 **대체하지 않음**. EUvest가 마스터, TA는 분석 엔진으로만 동작.

---

## 5. 출력 스키마 (agents/schemas.py)

### 5.1 주요 스키마

```python
# 투자 액션 (Trader)
class TraderAction(StrEnum):
    BUY = "Buy"
    HOLD = "Hold"  
    SELL = "Sell"

# 포트폴리오 레이팅 (Research Manager / Portfolio Manager)
class PortfolioRating(StrEnum):
    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"

# 구조화 출력 모델
class TransactionProposal(BaseModel):
    action: TraderAction
    symbol: str
    quantity: Optional[float]
    limit_price: Optional[float]
    rationale: str
    confidence: Literal["low", "medium", "high"]
```

### 5.2 EUvest DecisionProposal 매핑

| TradingAgents | EUvest | 변환 로직 |
|---------------|--------|-----------|
| `TraderAction.BUY/SELL` | `side: BUY/SELL` | 1:1 매핑 |
| `TraderAction.HOLD` | `NO_TRADE` 또는 items 생략 | HOLD = 관망 |
| `PortfolioRating` (5단계) | `confidence` 참고 | Overweight→매수비중↑, Underweight→매도비중↑ |
| `rationale` + `confidence` | `rationale` + `evidence_ids` | 원문 저장, 근거 ID 별도 관리 |

---

## 6. 의존성 및 환경

### 6.1 핵심 의존성 (pyproject.toml)

```toml
dependencies = [
    "langchain-core>=1.6.5",
    "langchain-anthropic>=1.7.4",
    "langchain-google-genai>=4.4.0",
    "langchain-openai>=1.6.6",
    "langgraph>=1.2.12",
    "langgraph-checkpoint-sqlite>=3.1.1",
    "yfinance>=1.7.0",
    "stockstats>=0.6.5",
    "pandas>=3.0.6",
    "pydantic>=2.7.4",
    "python-dotenv>=1.0.0",
    "rich>=14.0.0",
    "typer>=0.21.0",
]
```

**충돌 가능성**: EUvest도 `pydantic>=2,<3`, `pandas`, `rich`, `typer` 사용 → 버전 호환 필요

### 6.2 격리 환경 필요성

- TradingAgents는 `langgraph`, `langchain-*` 등 무거운 의존성 보유
- EUvest 메인 프로젝트(`src/invest_agent/`)와 **완전 분리** 필수
- `experiments/tradingagents_poc/.venv` 별도 구성 완료
---

## 7. 실행 검증 결과 (2026-11-01)

### 7.1 테스트 환경

| 항목 | 값 |
|------|-----|
| Python | 3.11.9 |
| Ollama | 실행 중 (localhost:11434) |
| 모델 | `qwen3.5:9b` (6.6 GB) |
| TradingAgents | v0.7.1 (commit c454491) |
| 격리 환경 | `experiments/tradingagents_poc/.venv` |

### 7.2 분석 실행 결과

| 종목 | 티커 | 날짜 | 제공자 | 상태 | 최종 결정 | 소요시간 |
|------|------|------|--------|------|-----------|----------|
| Apple | AAPL | 2026-11-01 | Ollama | ✅ 성공 | **Hold** | ~5분 |
| 삼성전자 | 005930.KS | 2026-11-01 | Ollama | ✅ 성공 | **Hold** | ~7분 |

### 7.3 데이터 가용성 상세

| 데이터 소스 | AAPL | 005930.KS |
|-------------|------|-----------|
| 가격/지표 (yfinance) | ✅ 22일치 | ✅ 22일치 |
| 재무제표 (SEC EDGAR/yfinance) | ✅ 완전 | ✅ 완전 (yfinance 경유) |
| 기업 뉴스 (Yahoo) | ✅ 다수 | ❌ 없음 (글로벌 뉴스로 대체) |
| 글로벌 매크로 뉴스 | ✅ | ✅ |
| FRED 매크로 | ❌ 키 없음 | ❌ 키 없음 |
| Polymarket | ❌ 네트워크 오류 | ❌ 네트워크 오류 |

### 7.4 구조화 출력 이슈

- `structured-output invocation failed` 경고 다수 발생
- 원인: `qwen3.5:9b` 모델이 OpenAI function calling 미지원
- 대응: `LocalCompatibleChatOpenAI`가 `tool_choice=None`으로 우회 → 자유 텍스트로 재시도
- 영향: 파싱 실패 시 자유 텍스트로 폴백, 분석 품질 저하 가능성

---

## 8. EUvest 통합 시 수정/구현 필요 사항

| 영역 | 현재 상태 | 필요 작업 | 우선순위 |
|------|-----------|-----------|----------|
| **공급자 추상화** | TradingAgents 자체 팩토리 | EUvest `AIProvider` 프로토콜에 어댑터 구현 | 높음 |
| **데이터 소스** | yfinance/SEC EDGAR 중심 | KIS API + OpenDART 연동 어댑터 구현 | 높음 |
| **한국 뉴스** | 미지원 | 네이버 금융/다음 금융 RSS 또는 공식 공시 연동 | 중간 |
| **메모리 연동** | 마크다운 파일 기반 | EUvest SQLite ↔ TA 브리지 구현 (`test_memory_integration.py` 참조) | 높음 |
| **출력 스키마** | Pydantic 독자 스키마 | EUvest `DecisionProposal` ↔ TA `TransactionProposal` 변환기 | 높음 |
| **설정 관리** | 환경변수 + default_config | EUvest `settings.yaml`과 통합 | 중간 |
| **비용 추적** | 토큰 사용량 미측정 | `callbacks`로 토큰/호출 횟수 측정 후 EUvest `model_usage` 기록 | 중간 |

---

## 9. 비용 추정 (Ollama 로컬)

| 항목 | 값 |
|------|-----|
| 모델 로드 메모리 | ~6.6 GB (qwen3.5:9b) |
| 단일 분석 시간 | 5-7분 |
| 분석당 토큰 (추정) | 입력 ~8k, 출력 ~4k |
| 하드웨어 | CPU/GPU 공유 (전용 GPU 권장) |
| 전기료 | 무시 가능 (로컬 실행) |

---

## 10. 결론 및 권고

### 코드 리뷰 요약

| 평가 항목 | 점수 (1-5) | 비고 |
|-----------|------------|------|
| 아키텍처 완성도 | 4 | LangGraph 기반 견고한 멀티 에이전트 |
| 공급자 추상화 | 5 | 팩토리 패턴, 티어 분리, OpenAI-compatible 완비 |
| 데이터 소스 추상화 | 4 | 벤더 체인, 폴백, 에러 처리 잘 설계됨 |
| 한국 주식 지원 | 2 | 가격/재무만 가능, 뉴스/공시 미지원 |
| 메모리 관리 | 3 | 파일 기반, SQLite 체크포인트, EUvest 연동 별도 필요 |
| 구조화 출력 | 3 | 로컬 모델 미지원 시 자유 텍스트 폴백 |
| 의존성 무게 | 2 | langchain/langgraph 의존성 큼 (격리 필수) |
| 문서화 | 4 | README, 스키마, 설정 잘 정리됨 |

### 최종 권고: **PARTIAL** (일부 모듈/구조 재사용)

**재사용 권장**:
1. `llm_clients/factory.py` → EUvest `ai/router.py` 공급자 팩토리 패턴 채택
2. `dataflows/router.py` → EUvest `market/evidence.py` 벤더 체인/폴백 패턴 채택
3. `agents/schemas.py` → EUvest `DecisionProposal` ↔ TA `TransactionProposal` 매핑 로직 구현
4. `default_config.py` → EUvest `settings.py` 환경변수 오버라이드 패턴 채택
5. `graph/trading_graph.py` 구조 → EUvest `runtime/orchestrator.py` 상태 기계 설계 참조

**별도 구현 필요**:
1. KIS API 연동 데이터 소스 (`market/market_data.py`, `market/filings_dart.py`)
2. EUvest SQLite 영속 메모리 브리지 (`storage/repositories.py` 확장)
3. 한국 뉴스/공시 수집기 (`market/filings_dart.py`, `market/evidence.py`)
4. 비용/토큰 추적 콜백 (`ai/router.py`에 통합)

**채택하지 않을 것**:
- TradingAgents 전체를 의존성으로 추가 (의존성 과다, 아키텍처 침투)
- TradingAgents 내부 메모리 로그를 EUvest DB로 대체 (프레임워크 종속성 방지)