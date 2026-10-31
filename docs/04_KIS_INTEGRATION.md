# 04 — 한국투자증권 API 개발 지침 / 확인 매트릭스

## A. 근거 URL (실제 조사 우선 순서)
1. 공식 개발자센터: https://apiportal.koreainvestment.com/intro
2. 시작 가이드: https://apiportal.koreainvestment.com/about-howto
3. API 개요: https://apiportal.koreainvestment.com/apiservice-summary
4. 공식 소스: https://github.com/koreainvestment/open-trading-api
5. LLM 탐색: https://github.com/koreainvestment/open-trading-api/blob/main/llms.txt
6. 인증·시세 단일 예제: `examples_llm/` 내부 해당 카테고리
7. 업무별 종합 예제: `examples_user/domestic_stock`, `examples_user/overseas_stock`, `examples_user/domestic_bond`
8. 공식 `strategy_builder/` (선택적 코드 재사용) 및 `backtester/` (LEAN/Docker는 후순위)
9. 공지: https://apiportal.koreainvestment.com/community/10000000-0000-0011-0000-000000000001

**공식 샘플은 업데이트될 수 있음.** 에이전트는 최초 조사 시 Git commit hash, URL, 조사 날짜, 요구 API 식별자, 호출 파라미터와 응답 검증 필드를 `docs/API_VERIFICATION_LOG.md`에 기록해야 한다.

## B. 확인된 사실과 주의사항 (2026-10-31 조회)
- 개인이 자신의 자산으로 자기 전략을 개발·매매하는 KIS Open API 이용 경로를 공식적으로 안내함.
- API 신청과 앱키/시크릿 필요. 실전/모의 키 각각 확보할 수 있음. access token은 유효기간 있으므로 캐싱과 유효시간 전 갱신이 필요.
- 공식 문서의 REST 호스트는 실전 `https://openapi.koreainvestment.com:9443`, 모의 `https://openapivts.koreainvestment.com:29443`. **직접 코드에 상수로 임의 구성하지 말고 검증된 host mapping을 쓰며 혼용 금지**.
- 공지된 REST 유량(2026-04-20 기준): 실전 계좌당 **18 req/s**, 모의 **1 req/s**; 신규 고객 특례·추가 유량제한 공지는 **실제 계정에서 재확인**. 최소한 모의 1 req/s보다 느리게 요청하도록 rate limiter 기본값 보수적으로 구현.
- 인증 토큰 발급도 개별 제한. 앱 시작마다 무조건 재발급하지 말고 안전하게 캐시/갱신.
- 2026-11-11 16:00 이후 **국내주식 재무분석 API 7종 종료 예정**. 신규 개발 의존 금지. 재무지표는 OpenDART/대체 검증 데이터 공급자를 사용.
- 국내주식 `order_cash` 현금주문 예제, 해외주식 `inquire_balance`, `inquire_ccnl` 예제는 공식 저장소에서 확인됨. 이름 유사하다는 이유로 국내/해외 TR_ID를 공유 금지.
- 공식 KIS Trading MCP는 주문 등 강한 권한을 노출하므로 **실거래 에이전트에 직접 연결하지 않음**. 코드 검색/읽기용으로만 참고.

## C. 지원 범위 매트릭스 (상태 구분 엄수)
상태: `DOCUMENTED`=카테고리/샘플 존재, `VERIFIED_READ`=해당 사용자 키로 실제 조회 성공, `VERIFIED_PAPER`=해당 상품 모의 주문 및 체결 조회 성공, `VERIFIED_LIVE`=별도 승인한 실제 체결 테스트 확인, `UNSUPPORTED`=명시 미지원, `UNVERIFIED`=미확인.

| 시장·상품 | 계좌/시세 조회 | 모의 주문 | 실전 주문 | 현재 처리 |
|---|---|---|---|---|
| KRX 현물 주식 | DOCUMENTED | UNVERIFIED | DOCUMENTED (공식 현금주문 예제) | P1에서 PAPER 검증 |
| 미국 현물 주식 | DOCUMENTED | UNVERIFIED | DOCUMENTED (공식 해외주식 예제) | P1에서 PAPER 검증 |
| 한국 상장 ETF | DOCUMENTED (ETF/ETN 카테고리) | UNVERIFIED | UNVERIFIED (현금주식 주문 가능 상품 매핑 검사) | 별도 상품 적격성 확인 |
| 미국 상장 ETF | DOCUMENTED (해외주식 카테고리) | UNVERIFIED | UNVERIFIED | 소수점/거래소/제한 확인 |
| 국내 장내채권 | DOCUMENTED (장내채권 카테고리) | UNVERIFIED | UNVERIFIED | P2 확장 |
| 해외 개별채권 | UNVERIFIED | UNVERIFIED | UNVERIFIED | 확인 전 주문 구현 금지 |
| 레버리지/인버스 ETF | 상품조회 가능성 별도 확인 | UNVERIFIED | 기본 차단 | 사용자 별도 승인 전 불가 |
| 신용·미수·파생 | 본 프로젝트 범위 외 | 금지 | 금지 | 주문 어댑터에 메서드 자체를 노출하지 않음 |

**중요:** 공식 폴더/샘플 존재는 특정 사용자 계좌의 실거래 및 모의거래를 보증하지 않는다. 확인 전 `UNVERIFIED` 상태에서 `KIS_PAPER` 주문 기능을 광고/활성화 금지.

## D. KIS 어댑터 작성 순서
1. API 카테고리별 필요한 5가지 기능만 선택한다: (a) 인증 (b) 잔고 (c) 현재가 (d) 현금주문 (e) 주문·체결 조회/취소.
2. `API_VERIFICATION_LOG`에 정확한 공식 Python 함수/파일·메서드·TR ID·시장 및 PAPER/PROD 차이 기록. **검증 없이 TR_ID/`OVRS_EXCG_CD`/시장구분 코드 하드코딩 금지**.
3. `KisReadAdapter`를 우선 구현. `get_balances()`, `get_quote()`, `get_open_orders()`, `get_order()`를 독립 테스트.
4. 원본 응답을 정규화하고 DataFrame 컬럼명이 바뀌는 경우 명확한 `BrokerProtocolError`.
5. 반환값이 빈 DataFrame이라도 성공으로 간주 금지(휴장·잘못된 파라미터·인증오류 구분).
6. rate limiter, timeout, 429/EGW 오류 처리, 인증 토큰 갱신, 요청 추적 ID(민감값 제외) 적용.
7. 실거래용 호출 코드에서 `order_credit`/`futures` 등은 import 하지 않는다. 주문 허용 API는 `order_cash` 해당 시장 현금주문만.
8. KIS_PAPER 환경 검증이 끝날 때까지 `KisBroker.submit_order`는 `UnsupportedModeError`를 내도록 유지.
9. 모의주문 성공 후 주문조회로 상태를 반드시 확인. 미국 시장은 거래소·통화/환전·정규장 여부 구분.
10. 모의 자산 미지원 시 `OFFLINE_SIM`을 사용하고 `PAPER 지원`처럼 표시 금지.

## E. Rate limit 기본 구현 정책
- 각 `(account_alias, execution_mode, API class)`에 token bucket+serialized queue. 모의 읽기/주문을 합쳐 **1 req/s 미만**으로 시작. 실전도 공지된 최대치보다 보수적으로 3~5 req/s 정도 상한 설정(안전한 기술 기본값이며 계정별 변동 가능).
- 인증 토큰 발급 별도 느린 큐. 모든 호출에 timeout. Retry 가능한 idempotent GET만 제한된 지수 backoff, jitter 적용.
- POST 주문의 응답이 실패/타임아웃/연결종료라고 해도 **즉시 재전송 금지**. 먼저 주문내역·미체결 조회 및 계좌 잔고 대조, 불명확하면 `RECOVERY_REQUIRED`.
- 최신 공지에서 신설·변경된 유량 정책이 있으면 안전한 값으로 재설정 후 테스트, 근거 기록.

## F. 예제 사용 방식과 금지사항
- `examples_user/*_examples.py`에는 주문 예제가 포함될 수 있다. **파일 전체 실행 금지**. 필요한 단일 함수만 별도 래퍼에서 호출/Mock.
- KIS 샘플이 신용·선물 주문 메서드를 포함해도 **직접 노출 금지**.
- 코드 복사 또는 재사용 시 라이선스·최신 공식 출처를 확인하고 소스 사용 사실을 `THIRD_PARTY.md`에 기록.
- 초기엔 `kis_auth.py`의 설정 파일 동작을 이해하고 무분별한 토큰 재발급·로그 노출을 차단. 예제 샘플의 글로벌 상태가 테스트 사이에 섞이지 않도록 래퍼 사용.
