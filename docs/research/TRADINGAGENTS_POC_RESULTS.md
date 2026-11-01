# TradingAgents POC 결과 (TRADINGAGENTS_POC_RESULTS.md)

> **작성일**: 2026-11-01  
> **실행 환경**: Windows 11, Python 3.11.9, Ollama `qwen3.5:9b`  
> **TradingAgents 버전**: v0.7.1 (commit `c454491`)  

---

## 1. 실행 요약

| 테스트 케이스 | 종목 | 티커 | 날짜 | 제공자 | 상태 | 최종 결정 | 소요시간 |
|--------------|------|------|------|--------|------|-----------|----------|
| TC-01 | Apple | AAPL | 2026-11-01 | Ollama | ✅ 성공 | **Hold** | ~5분 |
| TC-02 | 삼성전자 | 005930.KS | 2026-11-01 | Ollama | ✅ 성공 | **Hold** | ~7분 |
| TC-03 | 모델 비교 | AAPL | 2026-11-01 | Ollama only | 부분 완료 | - | - |

---

## 2. 상세 실행 결과

### TC-01: AAPL 분석 (Ollama)

**실행 명령**:
```powershell
cd experiments\tradingagents_poc
.venv\Scripts\python run_analysis.py AAPL --provider ollama
```

**데이터 가용성**:
| 데이터 소스 | 상태 | 비고 |
|------------|------|------|
| 가격/지표 (yfinance) | ✅ 22일치 (10/1~10/30) | 종가 330~349 범위 |
| 재무제표 (SEC EDGAR/yfinance) | ✅ 완전 | 손익/현금흐름/대차대조표 |
| 기업 뉴스 (Yahoo) | ✅ 다수 | 내부자 거래, 실적 등 |
| 글로벌 매크로 뉴스 | ✅ | 암호화폐/기술 섹터 중심 |
| FRED 매크로 | ❌ | API 키 미설정 |
| Polymarket | ❌ | 네트워크 오류 |

**분석 품질**:
- Market Analyst: 기술적 지표 기반 분석 (OHLCV, 볼륨, 이동평균)
- News Analyst: 글로벌 매크로/암호화폐 뉴스 중심, AAPL 특화 뉴스 제한적
- Fundamentals Analyst: SEC EDGAR 재무데이터 기반 분석
- Research Manager: 구조화 출력 실패 → 자유 텍스트로 폴백
- Risk Debate: Aggressive/Conservative/Neutral 3자 토론 수행
- Trader: Hold 액션 제안
- Portfolio Manager: Hold 레이팅 확정

**최종 결정**: **Hold** - "구체적인 가격 데이터와 변동성 트리거가 정의될 때까지 현재 포지션 유지"

**구조화 출력 이슈**: `structured-output invocation failed` 다수 발생 → `qwen3.5:9b` function calling 미지원으로 자유 텍스트 폴백

---

### TC-02: 삼성전자 분석 (Ollama)

**실행 명령**:
```powershell
.venv\Scripts\python run_analysis.py 005930.KS --provider ollama
```

**데이터 가용성**:
| 데이터 소스 | 상태 | 비고 |
|------------|------|------|
| 가격/지표 (yfinance) | ✅ 22일치 | yfinance `005930.KS` 지원 |
| 재무제표 (yfinance 경유) | ✅ 완전 | 손익/현금흐름/대차대조표 조회 성공 |
| 기업 뉴스 (Yahoo) | ❌ 없음 | 한국 기업 뉴스 태깅 미지원 → 글로벌 뉴스 대체 |
| 글로벌 매크로 뉴스 | ✅ | Binance 해킹, SEC 규제, 기술주 비교 등 |
| FRED 매크로 | ❌ | API 키 미설정 |
| Polymarket | ❌ | 네트워크 오류 |

**한국 주식 특이사항**:
- `005930.KS` 티커로 yfinance에서 정상 조회
- SEC EDGAR 대신 yfinance 재무데이터 활용 (삼성전자 미국 예탁증권 기준)
- 벤치마크: `^KS11` (KOSPI) 자동 매핑 (`benchmark_map[".KS"]`)

**분석 품질**:
- Market Analyst: 가격/지표 스냅샷 제공
- Fundamentals Analyst: 삼성전자 재무제표 상세 분석 (매출, 영업이익, 현금흐름 등)
- News Analyst: 한국 특화 뉴스 없음, 글로벌 기술 섹터 뉴스로 대체
- 구조화 출력 동일하게 실패 → 자유 텍스트 폴백

**최종 결정**: **Hold** - "삼성전자에 대한 실질적 분석 내용 없이 실증적 증거 부족으로 관망"

---

### TC-03: 모델 비교 (Ollama only)

NVIDIA NIM API 키 미설정으로 Ollama 단일 테스트만 수행.
`run_compare.py`는 Ollama 단일 제공자만 실행하도록 구성됨.

---

## 3. 메모리 통합 테스트

**실행 결과**: `test_memory_integration.py` 미완료 (시간 부족)
**예상 결과**: EUvest SQLite ↔ TradingAgents 브리지 구조 검증 필요

---

## 4. 발견된 이슈 및 제한사항

### 4.1 구조화 출력 실패 (Critical)
- **현상**: `Research Manager: structured-output invocation failed (structured output returned no parsed result); retrying once as free text`
- **원인**: `qwen3.5:9b` 모델이 OpenAI function calling 미지원
- **영향**: Pydantic 스키마 파싱 실패 → 자유 텍스트로 폴백 → 파싱 로직 복잡도 증가
- **대응**: `LocalCompatibleChatOpenAI`가 `tool_choice=None`으로 우회 구현됨

### 4.2 한국 주식 뉴스 부재 (Major)
- Yahoo Finance API가 한국 기업(`005930.KS`) 뉴스를 태깅하지 않음
- 글로벌 매크로/암호화폐 뉴스로 대체되어 한국 기업 특화 분석 어려움
- **대안**: 네이버 금융/다음 금융 RSS, OpenDART 공시 연동 필요

### 4.3 FRED/Polymarket 불가 (Minor)
- FRED_API_KEY 미설정 → 매크로 지표(GDP, 실업률, 금리 등) 조회 불가
- Polymarket 네트워크 오류 → 예측 시장 데이터 불가
- **대응**: 선택적 카테고리로 분류되어 분석 중단 없음

### 4.4 한국 재무제표 SEC EDGAR 미지원 (Major)
- 삼성전자 등 한국 기업은 SEC EDGAR 공시 의무 없음
- yfinance가 제공하는 재무데이터는 미국 예탁증권(ADR) 기준일 가능성
- **대안**: OpenDART API 연동 필수

### 4.5 분석 시간 (5-7분/종목)
- 병렬 애널리스트 실행에도 불구하고 순차적 토론/의사결정 단계로 시간 소요
- 실시간 운영 시 스케줄러 간격 고려 필요 (최소 10분 간격 권장)

---

## 5. EUvest 통합 시 검증 필요 항목

| 검증 항목 | 현재 상태 | 필요 조치 |
|-----------|-----------|-----------|
| ContextEnvelope → TA State 변환 | 미구현 | `TradingAgentsAdapter._build_ta_state()` 구현 |
| TA Result → DecisionProposal 변환 | 미구현 | `TradingAgentsAdapter._convert_ta_result()` 구현 |
| EUvest SQLite ↔ TA 메모리 브리지 | 미구현 | `MemoryBridge` 클래스 구현 (`storage/repositories.py`) |
| 구조화 출력 파싱 (로컬 모델) | 실패 확인 | 자유 텍스트 파싱 로직 또는 비구조화 출력 허용 |
| 한국 뉴스/공시 데이터 소스 | 부재 | `market/filings_dart.py`, `market/evidence.py` 구현 |
| 비용/토큰 추적 | 미구현 | LangChain callback 핸들러 추가 |
| 타임아웃/취소 처리 | 미검증 | 비동기 실행 + 타임아웃 래퍼 구현 |

---

## 6. 최종 판정 및 권고

### 종합 판정: **PARTIAL** (일부 모듈/구조 재사용)

**채택 권장 패턴/모듈**:
1. `llm_clients/factory.py` → EUvest `ai/router.py` 공급자 팩토리
2. `dataflows/router.py` → EUvest `market/evidence.py` 벤더 체인/폴백
3. `agents/schemas.py` → EUvest `DecisionProposal` 매핑 로직
4. `default_config.py` → EUvest `settings.py` 환경변수 오버라이드
5. `graph/trading_graph.py` 구조 → EUvest `runtime/orchestrator.py` 상태 기계

**별도 구현 필요 (TradingAgents 미제공)**:
1. KIS API 연동 (`market/market_data.py`, `broker/kis_adapter.py`)
2. OpenDART 공시 연동 (`market/filings_dart.py`)
3. 한국 뉴스 수집 (`market/evidence.py`)
4. 리스크 게이트/주문 실행 (`execution/risk_gate.py`, `execution/order_engine.py`)
5. EUvest SQLite 영속 메모리 (`storage/repositories.py`)
6. 비용/토큰 추적 (`ai/router.py` callback 핸들러)

**채택하지 않을 것**:
- TradingAgents 전체 의존성 추가 (langchain/langgraph 의존성 과다)
- TradingAgents 내부 메모리 로그를 EUvest DB로 대체 (프레임워크 종속성 방지)

---

## 7. 다음 단계 (P0-02 이후 반영)

| Phase | 작업 | 담당 모듈 | 예상 공수 |
|-------|------|-----------|-----------|
| P0-07 | `TradingAgentsAdapter` 구현 | `ai/router.py`, `ai/protocol.py` | 2-3일 |
| P0-08 | `MemoryBridge` 구현 | `storage/repositories.py` | 1-2일 |
| P0-04 | KIS 데이터 소스 추가 | `market/market_data.py` | 2-3일 |
| P0-05 | OpenDART/한국 뉴스 연동 | `market/filings_dart.py`, `market/evidence.py` | 2-3일 |
| P0-06 | 리스크 게이트/주문 엔진 | `execution/risk_gate.py`, `execution/order_engine.py` | 3-5일 |

---

## 8. 부록: 실행 로그 위치

```
experiments/tradingagents_poc/
├── results/
│   ├── ollama/
│   │   ├── AAPL/2026-11-01/analysis_result.json
│   │   └── 005930.KS/2026-11-01/analysis_result.json
│   └── memory_test/ (예정)
├── run_analysis.py
├── run_compare.py
├── test_memory_integration.py (미완료)
├── config_poc.yaml
├── .env (Ollama 설정)
└── .venv/ (격리 환경)
```

---

**작성 완료**: 2026-11-01  
**작성자**: EUvest POC Agent