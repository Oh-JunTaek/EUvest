# 02 — 기술 스택·정확한 산출물·파일 구조

## A. 고정 기술 선택
- OS: **Windows 11/10**, PowerShell 명령 테스트 필수.
- Language: **Python 3.11**. 3.12/3.13 자동 상향 금지(공식 예제 호환성 검증 후 가능).
- Env/deps: **uv** (`pyproject.toml`, `uv.lock`), `.venv`.
- CLI: `typer`, `rich`. 전부 CLI 명령으로 운영 가능.
- Configuration: YAML `PyYAML`, 환경변수, `.env`(gitignore 필수), `pydantic` v2 검증.
- HTTP: `httpx`(앱의 신규 호출), KIS 공식 예제의 `requests` 의존성은 래퍼 내 격리 가능.
- Database: **sqlite3(표준 라이브러리)** + `migrations/*.sql`. 단일 프로세스 쓰기·WAL 사용. SQLAlchemy/Redis/Postgres 초기 금지.
- Analysis: `pandas` + 필요시 `numpy`, 지표는 소규모 검증 함수 작성; TA-Lib 네이티브 빌드 필수화 금지.
- Test: `pytest`, `pytest-cov`, `ruff`, `unittest.mock`/fixture. 네트워크 없는 테스트 통과 필수.
- Market calendar: 검증된 캘린더 라이브러리 사용 가능하나 시장별 공식 휴장/거래시간과 DST 반영; 라이브러리 선정과 버전은 P0 조사 결과에 기록.
- LLM: JSON 기반 `AIProvider` 프로토콜 + OpenAI 호환 HTTP 어댑터, Ollama HTTP 어댑터, FakeProvider. 모델 이름은 설정에서만 선택.
- News: 공식 공시(OpenDART 등) 우선, 저작권·접근 정책 허용된 RSS/제공 API만. 무허가 범용 크롤러 초기 금지.
- Jobs: Windows Task Scheduler + app file lock, 표준 로그. 작업 완료 후 프로세스 종료. 별도 웹서버 불필요.
- UI: `invest status`, `invest report`, `invest runs`, `invest universe` 등 CLI/텍스트표. Streamlit은 모든 P0 완료 이후 별도 승인.

## B. 목표 저장소 구조 (반드시 만들 것: 파일별 점진 생성)

```text
personal-ai-investor/
├─ AGENTS.md
├─ README.md                     # 사용자 설치/운영, 구조, 안전 주의
├─ pyproject.toml                 # Python 3.11/uv deps
├─ uv.lock
├─ .gitignore
├─ .env.example
├─ config/settings.example.yaml
├─ config/settings.local.yaml    # 실행 시 복사, Git 제외
├─ schemas/context_envelope.schema.json
├─ schemas/decision_proposal.schema.json
├─ migrations/001_init.sql
├─ migrations/002_ai_state.sql
├─ src/invest_agent/
│  ├─ __init__.py
│  ├─ cli.py                      # Typer 엔트리 포인트
│  ├─ settings.py                 # 안전 설정/모드 검증
│  ├─ domain/models.py            # AssetId, Price, Portfolio, DecisionProposal 등
│  ├─ domain/enums.py             # Market, AssetType, ExecutionMode, RunStatus
│  ├─ domain/errors.py            # Typed exceptions
│  ├─ broker/protocol.py          # 읽기/주문/체결 공통 인터페이스
│  ├─ broker/kis_adapter.py       # 공식 KIS 샘플 래핑, 호출 매핑
│  ├─ broker/mock_broker.py       # 반복가능한 오프라인 모의계좌
│  ├─ broker/rate_limiter.py      # 계좌/모드별 요청 유량 관리
│  ├─ broker/normalize.py         # KIS 원본값→도메인 객체
│  ├─ ai/protocol.py              # Provider 공통 인터페이스
│  ├─ ai/openai_compatible.py     # 선택형 무료 외부 API
│  ├─ ai/ollama.py                # 로컬 AI
│  ├─ ai/fake_provider.py         # 테스트 fixture 결정 반환
│  ├─ ai/router.py                # 선택·fallback·쿼터/토큰 예산
│  ├─ agent/context_builder.py    # DB 상태→모델 중립 ContextEnvelope
│  ├─ agent/research_planner.py   # 제한된 조사 계획 선택
│  ├─ agent/decision_validator.py # JSON/근거/상태버전 검증
│  ├─ agent/thesis_manager.py     # 투자 가설 새 버전 및 인계
│  ├─ market/market_data.py       # KRX/US 시세·OHLCV·가공
│  ├─ market/calendar.py          # 거래일·현지장·시간외 정책
│  ├─ market/indicators.py        # 결정론적 기술지표 계산
│  ├─ market/evidence.py          # 출처+발행시각+수집시각
│  ├─ market/filings_dart.py      # 선택적 OpenDART(초기에는 비활성)
│  ├─ portfolio/ledger.py         # 현금·보유·입출금·FX 기록
│  ├─ portfolio/valuation.py      # 시가평가, USD/KRW 평가통화
│  ├─ execution/risk_gate.py      # 투자판단과 독립된 하드제약
│  ├─ execution/sizing.py         # Decimal 및 주문단위 적용
│  ├─ execution/order_engine.py   # intent/idempotency/recovery
│  ├─ execution/reconcile.py      # 실제 미체결·체결 대사
│  ├─ runtime/orchestrator.py     # 실행 상태 기계
│  ├─ runtime/locking.py          # 단일 인스턴스
│  ├─ runtime/scheduler.py        # 예약 실행 (작업스케줄러 설정)
│  ├─ storage/db.py               # SQLite 연결/WAL/트랜잭션
│  ├─ storage/repositories.py     # 기록 저장·버전 체크
│  ├─ evaluation/metrics.py       # TWR/MDD/현금흐름/비용
│  ├─ evaluation/baselines.py     # 단순 보유/정기매수 비교
│  ├─ reporting/daily.py          # JSON/Markdown 보고서
│  └─ operations/health.py        # doctor/stop/recovery status
├─ tests/
│  ├─ fixtures/                  # 가짜 KIS 응답·시장데이터·LLM 출력
│  ├─ unit/                      # 순수 함수 테스트
│  ├─ contract/                  # Provider/MockBroker 계약 테스트
│  ├─ integration/               # DB + 모의 주문 전체 흐름
│  └─ fault/                     # 타임아웃, 429, 중복, 재부팅 주입
├─ scripts/
│  ├─ install_schedule.ps1       # 사용자 승인 후 일정 등록
│  └─ verify_env.ps1
├─ docs/
│  ├─ API_VERIFICATION_LOG.md
│  ├─ EXECUTION_LOG.md
│  ├─ CHANGELOG.md
│  ├─ OPEN_QUESTIONS.md
│  └─ TEST_REPORT.md
└─ data/                        # Git 제외 / DB / 내보내기 / 백업
   ├─ investor.db
   ├─ reports/
   ├─ backups/
   └─ logs/
```

- 아직 구현하지 않은 P1/P2 모듈을 의미 없는 `pass`로 생성하지 않는다. **만든 파일만 완료 보고**한다.
- Windows 플랫폼에서 `uv run invest doctor` 등 실행이 되는지 문서와 테스트로 검증.
- 사용자 비밀키는 project root `.env`에만 두는 식도 보안 위험이 있으므로 `.gitignore`와 절대경로·로그 마스킹 검증; 가능하면 Windows Credential Manager/DPAPI를 후속 적용.

## C. CLI 계약
| 명령 | 정확한 동작 | 기본 안전 |
|---|---|---|
| `invest doctor` | Python/설정/시계/키 존재/DB/공식 API 접근 상태 진단 | 인증 값 내용 표시 금지 |
| `invest universe list` | KRX/US 허용 상품·검증 상태 출력 | 빈 목록에서 거래 불가 |
| `invest universe add KRX 005930` | 심볼·시장·상품 확인 후 추가 | 레버리지·미확인 자산 기본 차단 |
| `invest universe add US VOO` | 미국 종목 허용 | 국내 시장 비활성에도 US 별도 |
| `invest portfolio --source mock` | 모의 잔고 | LIVE 접근 없이 동작 |
| `invest portfolio --source kis-paper` | KIS paper 잔고 | 인증없으면 명확히 실패 |
| `invest run-once --mode offline-sim` | 정규화 스냅샷→모의 판단→모의 주문/일지 | 기본 |
| `invest run-once --mode research-only` | 읽기전용 조사·LLM 판단만 | 거래 요청 불가 |
| `invest runs --last 10` | 실행/모델/비용/실패 사유 | 로컬 |
| `invest orders --last 20` | 주문·체결/정정/거부/모드 | 로컬 |
| `invest report --days 30` | 수익·비용·거래수·실패·벤치마크 | 자료 부족 표시 |
| `invest stop` | kill switch 활성: 신규 주문/재시도 차단 | 기존 미체결 자동취소는 아님 |
| `invest recover` | 미체결·원장 대사 후 블록 상태 해제 가능성 보고 | 자동 주문 없음 |

`invest run-once --mode live` 등의 명령은 **실거래 Phase 전에는 아예 등록하지 않는다.** 백테스트는 `invest backtest`로 별도 구현하되 미래정보 누출 금지.
