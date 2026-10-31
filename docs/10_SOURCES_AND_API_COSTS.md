# 10 — 검증된 공식 자료 / 재사용 우선순위 / 이용조건 / 비용 통제

- 검색 기준일: **2026-10-31**. 외부 서비스 변경 가능. 사용자 계정·API 키로 실제 테스트한 것은 **아직 없음**.
- `VERIFIED_DOCUMENT`은 공식 웹에서 문서를 확인했다는 의미이며 해당 사용자 계정의 동작을 검증했다는 뜻이 아님.

## A. 한국투자증권 공식 자료
| 문서/서비스 | 확인된 용도 | 링크 |
|---|---|---|
| 개인용 Open API 서비스 소개 | 본인 자산으로 자동매매 가능 이용 경로 | https://apiportal.koreainvestment.com/about |
| API 신청·키 안내 | API 신청, token(24h), 모의계좌 | https://apiportal.koreainvestment.com/about-howto |
| API 개요·REST 호스트 | live/paper 별도 호스트 | https://apiportal.koreainvestment.com/apiservice-summary |
| KIS 공식 샘플 저장소 | 종목별 조회·주문·잔고, Python 예제 | https://github.com/koreainvestment/open-trading-api |
| LLM 탐색 guide | `examples_llm`/`examples_user` 사용 안내 | https://github.com/koreainvestment/open-trading-api/blob/main/llms.txt |
| Strategy Builder | 기술지표/시그널/모의·실전 주문 예시 | https://github.com/koreainvestment/open-trading-api/blob/main/strategy_builder/README.md |
| Backtester | LEAN/Docker 기반 전략 검증 | https://github.com/koreainvestment/open-trading-api/blob/main/backtester/README.md |
| API 호출 유량 공지 | REST 실전 18/s, 모의 1/s(2026-04-20 기준) | https://apiportal.koreainvestment.com/community/10000000-0000-0011-0000-000000000001/post/d0d1a83f-6f8d-4437-9700-6d26702fd989 |
| 최근 공지 | 신규 계정 제한/모의투자/유량/시장제도 변경 확인 | https://apiportal.koreainvestment.com/community/10000000-0000-0011-0000-000000000001 |
| Trading MCP | MCP API 검색·참고, 실거래 도구 직접 연결은 보안상 금지 | https://apiportal.koreainvestment.com/tools-trading |

**중요한 서비스 변경:** KIS 국내주식 재무분석 API 7종(대차대조표, 손익계산서, 재무비율, 수익성, 기타주요비율, 안정성, 성장성)은 **2026-11-11 16:00 종료 예정**. 새로운 의존성 작성 금지. https://apiportal.koreainvestment.com/intro

## B. 시장·공시·거래 비용
- 국내 상장기업 공식 공시: **OpenDART** https://opendart.fss.or.kr/ (인증키/사용 제한 별도 확인).
- 해외 뉴스/SEC filings 등: 실제 도입 전 개별 API/공시 제공 범위·라이선스·요청 제한 확인. 처음엔 KIS 시세 + OpenDART 등 검증 가능한 출처만 사용.
- 불특정 뉴스 본문 무단 복사·크롤링 및 장기 원문 저장 금지. 제공 API 규정의 caching/상업·비상업 조항 확인.
- KIS API 호출 자체의 무료/유료 여부와 **거래 수수료, 유관기관 제비용, 세금, FX 비용, 해외 시세 이용권, 야간 환전** 등은 별도 확인. ‘API 무료=투자 비용 0원’ 아님.
- 거래 비용은 프로그램에 0원 하드코딩하지 말고 수수료표·거래일·시장에 따라 설정. 모르면 `COST_UNKNOWN` 차단.

## C. 외부 무료 LLM 공급자
| 공급자 후보 | 계약 | 확인/제약 |
|---|---|---|
| NVIDIA NIM API Catalog | OpenAI 호환 Chat Completions | 무료 개발·시험용 접근. **공식 FAQ에 운영/실제 상거래 목적은 별도 enterprise 라이선스 필요하다고 안내**. 실제 거래 운영용으로 자동 허용 불가. |
| 기타 무료 OpenAI-compatible LLM API | 같은 `AIProvider` | 모델별 무료 요청량·보존·학습·계속 지원 여부·실거래 이용권 확인 필요 |
| Ollama 로컬 | 로컬 HTTP | API 요금 없음. 로컬 PC 전력·장치 성능·모델 라이선스 확인. 운영 PC 켜짐 필요 |
| Android Gemma E2B | 후속 | Android에서 모델 추론 가능해도 기존 앱을 외부 자동화 API로 호출할 수 있는지는 별도 PoC 필요 |

NVIDIA 공식 FAQ: https://docs.api.nvidia.com/nim/docs/product
NVIDIA Chat API Reference: https://docs.api.nvidia.com/nim/reference/llm-apis

**개발 규칙**: 공급자별 `prototyping_allowed`, `live_use_allowed`, `personal_data_policy_checked_at`, `free_quota_assessed_at`, `status` 기록. `live_use_allowed`를 공식 약관으로 확인하지 못하면 `UNKNOWN`이고 해당 Provider는 **LIVE에서 선택 불가**. 사용자 무료 비용 선호를 이유로 이용조건을 무시하지 않는다.

## D. 벤치마킹 코드
- Freqtrade protections: https://docs.freqtrade.io/en/2026.5.1/plugins/ ; 참고 가능한 설계는 cooldown, MaxDrawdown, StoplossGuard 등. 암호화폐 API를 주식 주문 엔진으로 직접 채택하지 않음.
- KIS Backtester(LEAN/Docker)는 유용하지만 설치·실행 비용 복잡성이 있으므로 기본 DB·CLI/Mock 엔진 완성 후 검토.

## E. API·LLM 운영 비용 통제 원칙
- 모델 호출은 이벤트/필요 데이터 업데이트 기반. 고정 10분 분석 시간과 매시간 매매 강제 금지.
- 설정: `max_model_calls_per_run`, `max_model_calls_per_day`, `max_research_rounds`, `max_input_tokens`, `max_output_tokens`, `max_latency_sec`, `timeout_sec`, `fallback_enabled`.
- 캐시: 같은 시장 시점·종목·시세·근거 hash가 같다면 근거 데이터 재사용 가능. **최신 주문 판단**은 KIS 현금·미체결 재조회 없이는 캐시 결과를 재사용하지 않는다.
- 뉴스 중복 제거와 지표 계산 Python 처리. 동일한 기사를 AI에게 반복 요약시키지 않음.
- 무료 API의 rate-limit/약관 변화에 대비한 공급자 교체. 실패하면 NO_TRADE(시스템 중단 사유는 BLOCKED로 기록) 및 재시도 상한.
- 테스트에서는 FakeProvider 우선, 실호출은 별도 승인·실험 예산 설정.

## F. 조사 상태를 정확히 기록하는 법
`docs/API_VERIFICATION_LOG.md`에 아래 열을 작성:
`service | market | asset_type | operation | official_url | repo_commit | exact_file_function | mode | status | tested_at | proof | notes`
- `mode`: OFFLINE_SIM/KIS_PAPER/LIVE
- `status`: DOCUMENTED/VERIFIED_READ/VERIFIED_PAPER/VERIFIED_LIVE/UNSUPPORTED/UNVERIFIED
- 임의 추측이나 유사한 API에 근거한 지원 확정 금지.
