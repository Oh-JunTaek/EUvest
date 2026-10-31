# 07 — 자동 테스트 명세 / 단계별 완료 판정

## A. 실행 명령 (저장소 생성 후 기본)
```powershell
uv sync
uv run ruff check src tests
uv run pytest -q
uv run pytest tests/unit -q
uv run pytest tests/contract -q
uv run pytest tests/integration -q
uv run pytest tests/fault -q
uv run invest doctor
uv run invest run-once --mode offline-sim
uv run invest status
```

다른 OS에서만 PASS한 결과로 Windows에서 검증 완료 표시 금지. 모든 테스트는 네트워크·API 키 없이 통과해야 함(라이브 키를 필요로 하는 통합 테스트는 별도 명시하고 `SKIPPED_NOT_CONFIGURED`). Mock 데이터와 실제 거래 확인을 섞어서 보고 금지.

## B. 최소 단위 테스트 (ID 고정)
| ID | 입력/상황 | 기대 결과 |
|---|---|---|
| T-001 | 빈 allowlist | 신규 거래 0건, NO_TRADE |
| T-002 | KRX ON / US OFF, 미국 주식 제안 | 0건, `MARKET_DISABLED` |
| T-003 | KRX OFF / US ON, 한국 주식 제안 | 0건, `MARKET_DISABLED` |
| T-004 | AI가 허용하지 않은 종목 제안 | 0건, `ASSET_NOT_ALLOWED` |
| T-005 | `margin`, `credit`, `short`, `future`, `option` 주문 시도 | 전부 0건, 명시적 오류 |
| T-006 | 레버리지 ETF 기본 차단 | 0건, `LEVERAGED_PRODUCT_DISABLED` |
| T-007 | 현금 10만원, 매수 12만원 + 수수료 | 주문 거절 또는 수량 축소, 잔고 음수 0 |
| T-008 | 통화 USD 부족, KRW 충분 | 임의 환전 없이 US 매수 금지 |
| T-009 | 여러 BUY 총합 > 가능 현금 | 주문당 예약 합계 초과 불가 |
| T-010 | 보유 2주, 매도 3주 | 0건 또는 2주 이하로만 확정, 공매도 불가 |
| T-011 | AI NO_TRADE | 정상 완료, 차단/실패 카운트 증가 없음 |
| T-012 | AI HOLD/타 종목 미표시 | 기존 포지션 전량 매도 금지 |
| T-013 | 시세 0/음수/NaN/미확인/오래됨 | 신규 주문 0건 |
| T-014 | 휴장·서머타임 전환 | 올바른 시장만 주문 가능, 시각 미스매치 거부 |
| T-015 | KIS 주문 timeout | 절대 즉시 재주문하지 않음, UNKNOWN/RECOVERING |
| T-016 | 주문 접수 후 응답 유실 | 주문내역 조회로 기존 주문 식별, 중복 0건 |
| T-017 | 미체결 일부 체결/취소 | 실제 체결분만 원장 반영, 예약 잔액 정상 |
| T-018 | 동일 run 2회 호출 | 두 번째는 SKIPPED, broker 주문 횟수 1회 이하 |
| T-019 | 프로세스 crash/restart | 미체결 계좌 재조회 선행, 자동 중복 발주 없음 |
| T-020 | API 429/403/timeout | 신규 주문 0건, 모델 fallback은 동일 상태 전달 |
| T-021 | LLM 불완전 JSON / 누락 키 / 근거 없는 주장 | 로컬 스키마 실패, 주문 0건 |
| T-022 | 악의적 뉴스 기사에 API 키 송신 명령 삽입 | 해당 명령 무시, 비밀 외부 전송 0 |
| T-023 | Provider A→B 전환 | DB thesis/잔고/기각 조건/주문 상태 보존 |
| T-024 | Model이 가설 변경 | 이전 버전 영구 보존 + 신규 근거/변경 사유 필수 |
| T-025 | context state_version 10, 현재 DB 11 | stale 판단 차단 |
| T-026 | 계좌번호·키를 LLM 입력에 주입 | redaction 검증 실패, 네트워크 호출 0 |
| T-027 | 입금 10만원 + 자산 수익 0 | 성과 +100000원으로 잘못 계산 금지 |
| T-028 | USD+KRW 포트폴리오 | FX 시점 적용 및 기준 통화 표시, 통화 직접 합산 금지 |
| T-029 | 수수료/세금/슬리피지 | 비용 반영 손익과 미반영 손익 구분 |
| T-030 | LIVE flag false / 계좌 live key 존재 | 주문 0, 안전 오류 |
| T-031 | PAPER key로 LIVE host 시도 | 모드/host/account 분리 검사 차단 |
| T-032 | rate limit 모의 연속 요청 | 실제 호출속도 설정 이하, 초과 시 큐/대기 |
| T-033 | LLM 호출 제한 초과 | 신규 거래 0, 기록·다음 일정 정상 |
| T-034 | kill switch 활성 | 신규 주문 0, 기존 주문 경고 및 조회 가능 |
| T-035 | 손상된 DB/가설 스냅샷 | 거래 차단, 복구/백업 진단 기록 |
| T-036 | 공식 API 자산 미지원 | `UNSUPPORTED`, fake-success 금지 |
| T-037 | 2개 공급자에 같은 입력 | 입력 JSON schema/version 동일, 결과는 달라도 됨 |
| T-038 | 뉴스 증거 발표 시각 > 판단 시각 | 해당 미래 증거 제거/주문 차단 |
| T-039 | 동일 ticker 다른 market/venue | 자산 identity 충돌 없음 |
| T-040 | KIS read-only 조회 실패 | `BROKER_UNAVAILABLE`, 실주문 불가 |

## C. 통합 테스트
- `I-01`: 오프라인 30회 실행: 20회 NO_TRADE + 10회 BUY/SELL의 기록 및 상태 기계 정상.
- `I-02`: 모의 잔고 10만원, 주식 1주 보유 → AI 2종목 구매 제안 → 현금 초과 없이 최대 주문수량 반영.
- `I-03`: KRX 휴장 + US 정규장, 양쪽 활성→ US만 모의 주문.
- `I-04`: provider A 실패→provider B 동일 `state_version` 컨텍스트로 재판단, 전략 상태 손실 없음.
- `I-05`: KIS 모의 주문 응답 손실+broker 뒤늦은 체결→중복 주문 0건, 원장 보정.
- `I-06`: 강제 종료/재부팅 후 `recover`로 상태 복구, 보호 상태 해제 전에 신규 주문 없음.
- `I-07`: 거래 수수료와 추가입금이 포함된 30일 보고서 계산 손익 정확.
- `I-08`: 동일 프롬프트 JSON fixture 서로 다른 Provider 어댑터 거쳐 동일 schema 검증.
- `I-09`: 스케줄러 중복 호출을 강제하여 최대 1개 실행만 동작.

## D. 합격 기준
- 전체 unit/contract/integration/fault 테스트 **실패 0**. 치명 주문·보안 테스트 **예외 없이 100%** 통과.
- `ruff check` 통과, `doctor`는 secrets 마스킹, 모든 경고는 명시.
- `KIS_PAPER`는 인증 없이 완료했다고 보고할 수 없음. 실제 테스트 전에는 `PENDING_CREDENTIALS`.
- 실제 API 기능을 확인하지 못한 상품은 `UNVERIFIED/UNSUPPORTED`; 가짜 예제로 기능 합격 처리 금지.
- 백테스트의 재현 가능 데이터와 결정론적 결과 확인. 미래정보/조정주가/수수료 미반영은 별도 명시.
- `LIVE`는 실거래 사용자 승인과 치명 단계 검증 완료 전 **절대 PASS 아님**.
- 각 Phase `docs/TEST_REPORT.md`에 테스트 날짜, 명령, 출력 요약, 검증 환경, 증거/로그 경로, 실제 API 테스트 여부 기록.

## E. 필수 사고 리허설
- 임의 프로세스 종료, 인터넷 연결 끊김, 미국 DST 전환 날짜, KIS 429, `api_key` 로그 오염, 상태 DB 롤백, 주문 거절, 환전 불가, 주문 일부체결, 모의/실전 키 뒤바뀜.
- 각 리허설 후 **실주문 건수 0**, Mock 주문 횟수 및 원장 정확성 수치로 확인.
