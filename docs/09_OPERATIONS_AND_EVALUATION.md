# 09 — 개인 사용자 운영 매뉴얼 및 AI 투자 성과 비교

## A. 실제 사용 모습 (목표 UX, CLI 먼저)
1. 최초 1회: Python/uv 설치, KIS Developers Open API 신청/키 설정, `invest doctor`, KRX/US 옵션 및 허용 종목 선택.
2. 모의 시험: `invest run-once --mode offline-sim` (모델 `FakeProvider` 가능) → `invest report --days 7`로 로그 확인.
3. 모델 선택: `AI_PROVIDER=...` 및 API URL/model slug 설정. `invest doctor`는 비밀 표시 없이 모델과 토큰 사용량 확인.
4. 한투 모의계좌 연결: 사용자가 키를 입력한 후 paper 테스트. 미지원 자산은 오프라인 시뮬레이션만.
5. 주기 설정: Windows 작업스케줄러에 `invest run-once --mode kis-paper` 예약, 예: 매 60분; 실제 실행은 시장별 정규장·데이터 유효성 검사 후.
6. 평소: `invest status`, `invest portfolio`, `invest runs`, `invest report --days 30`로 현황 확인. **투자를 반드시 하는 구조가 아님**.
7. 실거래: 사용자 승인한 리스크 상한·공급자 이용조건 확인·모의 오류 0을 충족하기 전에는 사용 불가.

## B. 최소 상태 화면 텍스트 요구
```
MODE: OFFLINE_SIM       MARKET: KRX=ON US=ON
PROVIDER: mock          LAST_RUN: 2026-10-31T09:00:00Z
BROKER_STATUS: MOCK     ORDER_GATE: CLOSED_FOR_LIVE
PORTFOLIO: cash KRW 100000 / USD 0 / positions 0
OPEN_ORDERS: 0          PENDING_RECOVERY: 0
NEXT_RUN: NOT_SCHEDULED
LAST_DECISION: NO_TRADE / data insufficient
LAST_ERROR: NONE
```
- 실제 화면은 정보를 숨기지 않되 계좌 ID·인증값은 출력 금지.
- `NO_TRADE`(AI 의도적 관망)와 `BLOCKED`(문제 생겨 거래 불가) 색/문구 다르게 표기.
- UI 미구현으로 기능 테스트가 안 된다는 핑계 금지. CLI 명령/로그로 검증 가능해야 함.

## C. 측정 목적 및 평가방법
**평가 질문**: ‘AI가 같은 기간 동일 자금을 단순 ETF 보유/정기매수한 것보다 좋은 결과를 냈는가?’  단순 AI 예측 적중률만으로 성공 판정 금지.

측정 표준:
- 계좌 실제 **총자산 = 현금 + 보유자산 시가평가 – 부채(신용거래 없음)**; 기준 통화 KRW이며 USD 보유/주식에는 동일 시각 환율 적용.
- `NetPnL`: 실현 + 미실현 손익 + 배당 − 세금·수수료·환전 비용. 입출금은 수익이 아니므로 별도 CashFlow.
- `TWR`(시간가중수익률) 및 `XIRR`/MWR(필요할 때), 총 수익률, `MDD`(최대 낙폭), 변동성, 비용률, 거래 빈도, 현금 보유 일수.
- 선택한 시장/자산의 동일 기간 단순 보유와 정기매수 비교. 기준선은 사용자 선택 또는 별도 설정; 실험 중 변경 이력 기록.
- LLM 성과: 모델·버전·프롬프트·Evidence ID·Context hash·응답 시간·스키마 적합률·판단 변경 사유·실제 fill 거래비용 분리.
- 모델 교체 시, 직전 모델의 수익을 다음 모델의 수익으로 오인하지 않도록 `provider_run_id`와 `decision_id` 추적. 하나의 계좌가 여러 모델로 운영됐다면 **모델별 실제 투자 수익 귀속은 단순하지 않음**; 유사한 시장 스냅샷에서 별도 paper shadow portfolios를 유지하여 비교.
- 시장이 오른 날 수익이 났다는 이유만으로 AI 우위 주장 금지. 거래 비용/환율/현금흐름/표본 기간/시장상승을 분리해 판단.

## D. 일간/주간 보고서 파일 형식
`data/reports/YYYY-MM-DD_daily.md` 내용:
1. 실행시장·연결모드·모델·정상/실패 실행 수
2. 계좌 총 평가자산 및 KRW/USD 현금·포지션·외부 입출금
3. AI 자율 조사 요약(근거 ID·발행/관측 시간)
4. 오늘 결정: BUY/SELL/HOLD/NO_TRADE/ERROR/BLOCKED 구분
5. 실제 접수/체결 상태 및 수수료·세금(미확인 값 명시)
6. 활성 투자 가설/변경 사유/기각 조건
7. 누적 성과·기준선·주기별 차이, 비용·위험 지표
8. 호출 횟수·429·fallback·중복/복구 이슈
9. 다음 점검에 필요한 데이터(예상 주가 예언 금지)

## E. 자금·입금 운영
- 사용자가 KIS 전용 계좌에 추가 입금하면 다음 잔고 동기화 때 업데이트. 자동 추가 입금/현금 송금 권한은 없음.
- 외부 입금액과 매매 손익은 분리 기록. 10만 원→추가 20만 원은 수익 200%가 아니다.
- 처음에는 금액 비밀을 직접 사용자 계좌에 넣고 paper 또는 소액 현물에 한정. 미수·신용·대출 기능은 제공하지 않음.

## F. PC 절전/종료 대응
- PC OFF면 작업은 수행되지 않음. 종료 중 보호 주문을 자동으로 유지·갱신할 수 있다는 주장은 금지.
- 재기동 후 자동 밀린 주문 실행 금지. `recover`에서 KIS 현재 현금/포지션/미체결 동기화 후 새 시점 기준 판단.
- 정규장 외엔 새 주문을 만들지 않음. 한국/미국 시간대를 각각 평가.

## G. 운영 전 변경관리
- 모델 교체/프롬프트 수정/새 도구 연결/허용 자산 추가/거래 주기 변경은 `config_version`을 증가시키고 audit 기록.
- 결과에 영향을 미치는 변경 후에는 shadow paper 테스트와 최소한의 회귀 테스트를 다시 실행.
- 버그 수정이 실제 거래 코드에 닿으면 사용자가 동의하기 전까지 LIVE를 자동 중지 상태로 두는 보수적 정책.
