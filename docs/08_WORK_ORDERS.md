# 08 — 코딩 에이전트 발주 티켓 (순서 변경 금지)

## 공통 실행 계약
- **절대 전체 서비스를 한 번에 구현하라는 지시로 해석하지 않는다.** 각 티켓이 승인되면 해당 티켓만 진행.
- 매 작업: (1) 이전 결과와 문서 읽기 (2) 근거/수정 계획 5줄 (3) 코드·테스트 (4) `uv run ruff check`, `uv run pytest` (5) 증빙·미확정 사항 기록 (6) 로컬 Git 커밋.
- 테스트 실패하면 실패 그대로 보고하고 다음 티켓 중지. 코드 실작성 없이 문서만 '완료' 표시 금지.
- KIS 키가 없는 상태에서도 `MockBroker`로 대부분 개발 가능. 모의·실거래 테스트는 키가 없으면 보류하고 막히지 않는 티켓을 우선 수행.

## P0-01 — 프로젝트 구조와 공식 API 조사
**착수 조건**: 패키지 문서 전체 읽음. **수정**: `README.md`, `pyproject.toml`, `src/invest_agent/__init__.py`, `docs/API_VERIFICATION_LOG.md`, `.gitignore`, `docs/OPEN_QUESTIONS.md`. **실행**: Python 3.11/uv 설치 확인, KIS 공식 `llms.txt`와 `examples_user`, `examples_llm`에서 국내/해외 현금주문·시세·잔고·주문/체결/취소 경로 조사; KIS commit hash 고정; 상품별 PAPER/실전 및 주문단위 여부 기록. **테스트**: `uv sync`와 `uv run python -c 'import invest_agent'`. **완료**: 실제 존재하는 공식 API 이름·소스 링크·확인 상태 표. **금지**: 주문 호출/실거래 기능 개발.

## P0-02 — 설정 모델 / 실행모드 격리
**수정**: `src/invest_agent/settings.py`, `domain/enums.py`, `config/settings.example.yaml`, `config/.env.example`, `tests/unit/test_settings.py`. **작업**: 시장 KRX/US ON/OFF, 모드 BACKTEST/OFFLINE_SIM/KIS_PAPER/LIVE, 허용 종목·레버리지·cash_only·kill switch 유효성 검사. **완료**: 기본값 OFFLINE_SIM/스케줄 OFF/LIVE OFF, LIVE config 변경만으로 실행 불가; 환경변수 키 값 비노출. **테스트**: T-001~006, T-030, 031, 034.

## P0-03 — 도메인 모델 / SQLite 마이그레이션
**수정**: `domain/models.py`, `domain/errors.py`, `storage/db.py`, `storage/repositories.py`, `migrations/001_init.sql`, `002_ai_state.sql`, `tests/unit/test_storage.py`. **작업**: Decimal, UTC, asset identity, state_version 낙관적 잠금, 감사 로그, WAL, 원자적 주문 intent 저장. **완료**: 저장·재시작·중복키 방지·DB 충돌 처리. **테스트**: T-018, 025, 035, 039.

P0-03 저장 계층은 완료했다. 사용자가 승인한 통합 검증 이월과 미검증 경계는 `11_OPEN_DECISIONS.md`의 P03-ACCEPT-01, 세부 결과는 `P03_FINAL_2026-11-04.md`를 참조한다. T-018·T-035의 실행기/브로커 측 거래 차단과 T-025의 실제 주문 경계는 통과로 처리하지 않는다.

## P0-04 — KIS 읽기전용 어댑터 / MockBroker
**수정**: `broker/protocol.py`, `broker/mock_broker.py`, `broker/kis_adapter.py`(READ만), `normalize.py`, `rate_limiter.py`, `tests/contract/test_broker.py`. **작업**: 현재가·잔고·주문내역 조회의 정규화, REST 모의/실전 호스트 분리, 429 및 토큰 수명, 요청 속도 큐. **완료**: MockBroker는 키 없어도 동작; KIS 실조회는 사용자가 키를 넣은 후 별도 READ_ONLY 증빙. **테스트**: T-013, 032, 040. **금지**: 공식 예제 `*_examples.py` 전체 실행.

## P0-05 — KRX/US 시장·상품/가격 정규화
**수정**: `market/market_data.py`, `calendar.py`, `indicators.py`, `portfolio/valuation.py`, `tests/unit/test_market.py`. **작업**: 시장 선택, DST/휴장, 시세 시각, OHLCV 기본 분석, 시장별 LOT, 평가통화 FX. **완료**: KRX OFF/US ON과 역의 테스트; 지연가격으로 주문 막힘; USD+KRW 분리. **테스트**: T-002,003,013,014,028,039.

## P0-06 — Mock 주문 엔진·현금 원장·위험 게이트
**수정**: `execution/risk_gate.py`, `sizing.py`, `order_engine.py`, `reconcile.py`, `portfolio/ledger.py`, `tests/unit/test_risk.py`, `tests/integration/test_offline_orders.py`. **작업**: 목표비중→수량, 현금·미체결 예약, idempotency, 주문 상태, 부분체결, 취소, 중복 방지, 시간초과 복구. **완료**: 오프라인 Mock에서 현금 음수/이중 주문 없음. **테스트**: T-005~010,015~019,027,029,034, I-02, I-05.

## P0-07 — AI Provider 추상화·표준 입력/출력
**수정**: `ai/protocol.py`, `ai/openai_compatible.py`, `ai/ollama.py`, `ai/fake_provider.py`, `ai/router.py`, `agent/decision_validator.py`, `tests/contract/test_ai_providers.py`. **작업**: 무료 외부 API/로컬 AI 설정 교체, JSON 파싱·local validation, timeout, token/call budget, 비밀정보 차단. **완료**: FakeProvider offline fully tested; 실제 공급자 호출은 별도 user key 및 약관 확인, 기본 OFF. **테스트**: T-020~023,026,033,037, I-08.

## P0-08 — 영속 투자 기억과 모델 인계
**수정**: `agent/context_builder.py`, `agent/thesis_manager.py`, `storage/repositories.py`, `tests/integration/test_handoff.py`. **작업**: `ContextEnvelope` 및 활성 가설/기각조건/최근 이력, HandoffSnapshot, version check, Provider A→B→A 교체. **완료**: 투자 논리·주문상태 중도 유실 불가, 판단 변경 근거 보존. **테스트**: T-023,024,025,035,037, I-04.

## P1-09 — 연구 파이프라인·공시·데이터 출처
**수정**: `agent/research_planner.py`, `market/evidence.py`, `market/filings_dart.py`, `tests/unit/test_evidence.py`. **작업**: 기사/공시 허용 공급자 목록, 중복 제거, 공개자료에 발표시각 저장, 위험 프롬프트 인젝션, 정해진 범위 내 자율 연구 도구 요청. **완료**: 입력 토큰/요청 예산 내에서 필요한 조사만 수행하고 신규 근거 없을 때 NO_TRADE 허용. **테스트**: T-021,022,038.

## P1-10 — 완전 자동 `run-once`와 기본 CLI
**수정**: `runtime/orchestrator.py`, `runtime/locking.py`, `cli.py`, `operations/health.py`, `reporting/daily.py`, `tests/integration/test_run_once.py`. **작업**: 조사→판단→RiskGate→Mock 실행→대사→일지, status, runs, portfolio, universe, orders, stop/recover. **완료**: `uv run invest run-once --mode offline-sim`, 중복 트리거 스킵, 실패 보고. **테스트**: I-01, I-02, I-03, I-06, I-09.

## P1-11 — KIS 공식 모의투자 주문 검증
**선행**: KIS 모의계좌 키 실제 준비, 사용 자산의 paper 주문 지원 개별 검증. **수정**: `broker/kis_adapter.py` 쓰기 어댑터, `tests/integration/test_kis_paper_live_api.py`, API Verification Log. **작업**: 공식 현금주문/취소/체결조회로만 구현. 조회권한 확인, 주문전 모드 분리, 한도, 상품 적격성. **완료**: PAPER 상에서 정상 주문·취소·부분체결 혹은 해당 시나리오 Mock 증빙을 구분. 지원 불명확 상품은 `UNSUPPORTED` 처리. **절대 금지**: 실제 키로 실주문.

## P1-12 — 실행 일정·성과 평가·운영 리포트
**수정**: `runtime/scheduler.py`, `scripts/install_schedule.ps1`, `evaluation/metrics.py`, `evaluation/baselines.py`, `reporting/daily.py`, `tests/unit/test_evaluation.py`. **작업**: Windows 예약 간격/단일 인스턴스, 재부팅 복구, 매매 없는 날의 정상 기록, TWR·MDD·비용/기준선/입출금 분리. **완료**: 매일 Markdown 보고서, 계정 입금이 수익률로 나타나지 않음. **테스트**: T-018,027~029, I-07,I-09.

## P2-13 — BACKTEST 엔진 검증
**수정**: `evaluation/backtest.py`, `tests/integration/test_backtest.py`, 선택적 공식 Backtester 래핑. **작업**: 과거 시점 데이터만 사용·수수료/환율 반영, 최소 단순 보유·정기매수 기준선, 구간별 성과. **완료**: 미래 데이터 유출 검출. 공식 KIS Backtester에 Docker/LEAN이 필요하면 설치 여부 사용자가 선택; 의존성이 무거우면 기본 오프라인 재현 가능 최소 엔진으로 시작.

## P2-14 — LIVE 활성화 게이트 (별도 사용자 승인 전 착수 금지)
**선행**: 사용자 실제 자금/리스크 최대치 승인, API 이용약관 검증, KIS 지원 범위와 paper 테스트 완료, 모든 핵심 사고 리허설 통과. **수정**: live-only 어댑터, 로컬 실거래 잠금 해제, 설명서. **완료**: 명시적 1회 소액 테스트와 체결 확인 후 일반적 스케줄 활성화 승인. **금지**: 코드·문서 생성만으로 실주문 자동 실행.

## P3-15 — 선택적 확장
- 국내 장내채권/해외채권의 API·거래단위·가격·세금/경과이자 검증 이후에만 확장.
- Android Gemma E2B는 공식 로컬 모델 호출/백그라운드·휴대폰 단독 네트워크·보안·운용 가능성을 먼저 PoC. 기존 PC 실행기를 바로 휴대폰으로 복사하면 작동한다고 가정 금지.
- 최소 Streamlit 로컬 화면은 CLI가 충분히 작동한 뒤 필요할 때만.

## 에이전트 인수검사 양식
```
[티켓] P0-0X
[변경 파일] ...
[공식 근거] URL, commit, 파일/함수, 확인일
[사용자 요구사항 대응] ID / 구현 방법
[테스트] 명령 + PASS/FAIL/NOT_RUN + 정확한 수
[외부 API] MOCK / KIS_READ_VERIFIED / KIS_PAPER_VERIFIED / UNKNOWN
[보안] 실주문 0, 비밀로그 0, 모드격리 확인
[미해결] 이슈번호/이유/차단영향
[로컬 Git 커밋] hash
[다음 작업] 티켓 번호, 착수 승인 대기
```
