# KIS API 검증 로그 (API_VERIFICATION_LOG.md)

> **작성일**: 2026-10-31  
> **기준 저장소**: https://github.com/koreainvestment/open-trading-api  
> **커밋 해시**: `3a9be59` (2026-10-27, "fix: 토큰 관리 및 OS 간 호환성 오류 수정")  
> **문서 버전**: 1.0  
> **작성자**: EUvest 개발 에이전트  

---

## 상태 정의 (문서 04 준수)

| 상태 | 의미 |
|------|------|
| `DOCUMENTED` | 공식 문서/샘플에 존재함 (코드 미검증) |
| `VERIFIED_READ` | 해당 사용자 키로 실제 조회 성공 |
| `VERIFIED_PAPER` | 해당 상품 모의 주문 및 체결 조회 성공 |
| `VERIFIED_LIVE` | 별도 승인한 실제 체결 테스트 확인 |
| `UNSUPPORTED` | 명시적 미지원 |
| `UNVERIFIED` | 미확인 (개발 전 기본값) |
| `BLOCKED` | 실거래 금지/구현 불가 |

> **중요**: 현재 KIS API 키가 없으므로 모든 항목은 `DOCUMENTED` 또는 `UNVERIFIED` 상태입니다. `VERIFIED_READ` 이상은 키 발급 후 별도 검증 필요.
﻿
---

## 검증 매트릭스

| service | market | asset_type | operation | official_url | repo_commit | exact_file_function | mode | status | tested_at | proof | notes |
|---------|--------|------------|-----------|--------------|-------------|---------------------|------|--------|-----------|-------|-------|
| KIS | KRX | STOCK/ETF | 주식현재가 시세조회 | https://apiportal.koreainvestment.com/apiservice-summary | 3a9be59 | examples_llm/domestic_stock/inquire_price/inquire_price.py → `inquire_price()` | OFFLINE_SIM | DOCUMENTED | 2026-10-31 | TR_ID: FHKST01010100, URL: /uapi/domestic-stock/v1/quotations/inquire-price | 실시간 시세는 WebSocket 필요 |
| KIS | KRX | STOCK/ETF | 주식잔고조회 | https://apiportal.koreainvestment.com/apiservice-summary | 3a9be59 | examples_llm/domestic_stock/inquire_balance/inquire_balance.py → `inquire_balance()` | OFFLINE_SIM | DOCUMENTED | 2026-10-31 | TR_ID: 실전 TTTC8434R / 모의 VTTC8434R, URL: /uapi/domestic-stock/v1/trading/inquire-balance | output1: 보유종목, output2: 예수금 요약 |
| KIS | KRX | STOCK/ETF | 현금주문(매수) | https://apiportal.koreainvestment.com/apiservice-summary | 3a9be59 | examples_llm/domestic_stock/order_cash/order_cash.py → `order_cash()` | OFFLINE_SIM | DOCUMENTED | 2026-10-31 | TR_ID: 실전 TTTC0012U / 모의 VTTC0012U, URL: /uapi/domestic-stock/v1/trading/order-cash | ord_dv=buy, 지정가만 지원(ord_dvsn=00) |
| KIS | KRX | STOCK/ETF | 현금주문(매도) | https://apiportal.koreainvestment.com/apiservice-summary | 3a9be59 | examples_llm/domestic_stock/order_cash/order_cash.py → `order_cash()` | OFFLINE_SIM | DOCUMENTED | 2026-10-31 | TR_ID: 실전 TTTC0011U / 모의 VTTC0011U, URL: /uapi/domestic-stock/v1/trading/order-cash | ord_dv=sell, 지정가만 지원(ord_dvsn=00) |
| KIS | KRX | STOCK/ETF | 주문정정취소 | https://apiportal.koreainvestment.com/apiservice-summary | 3a9be59 | examples_llm/domestic_stock/order_rvsecncl/order_rvsecncl.py → `order_rvsecncl()` | OFFLINE_SIM | DOCUMENTED | 2026-10-31 | TR_ID: 실전 TTTC0013U / 모의 VTTC0013U, URL: /uapi/domestic-stock/v1/trading/order-rvsecncl | rvse_cncl_dvsn_cd: 01(정정)/02(취소), 정정취소가능주문조회 선행 필수 |
| KIS | KRX | STOCK/ETF | 주문체결내역조회 | https://apiportal.koreainvestment.com/apiservice-summary | 3a9be59 | examples_user/domestic_stock/domestic_stock_functions.py → `inquire_ccnl()` | OFFLINE_SIM | DOCUMENTED | 2026-10-31 | TR_ID: 확인 필요, URL: /uapi/domestic-stock/v1/trading/inquire-ccnl | 미체결/체결 구분 조회 가능 |
| KIS | US | STOCK/ETF | 해외주식 현재가 시세조회 | https://apiportal.koreainvestment.com/apiservice-summary | 3a9be59 | examples_llm/overseas_stock/inquire_price/ (파일 미존재) | OFFLINE_SIM | UNVERIFIED | 2026-10-31 | examples_user/overseas_stock/overseas_stock_functions.py 참조 필요 | examples_llm에 단일 파일 없음 |
| KIS | US | STOCK/ETF | 해외주식 잔고조회 | https://apiportal.koreainvestment.com/apiservice-summary | 3a9be59 | examples_llm/overseas_stock/inquire_balance/inquire_balance.py → `inquire_balance()` | OFFLINE_SIM | DOCUMENTED | 2026-10-31 | TR_ID: 실전 TTTS3039R / 모의 VTTS3039R, URL: /uapi/overseas-stock/v1/trading/inquire-balance | ovrs_excg_cd, tr_crcy_cd 필수 |
| KIS | US | STOCK/ETF | 해외주식 주문(매수) | https://apiportal.koreainvestment.com/apiservice-summary | 3a9be59 | examples_llm/overseas_stock/order/order.py → `order()` | OFFLINE_SIM | DOCUMENTED | 2026-10-31 | TR_ID: 실전 TTTT1002U / 모의 VTTT1002U, URL: /uapi/overseas-stock/v1/trading/order | 거래소별 TR_ID 상이, 모의는 지정가만 |
| KIS | US | STOCK/ETF | 해외주식 주문(매도) | https://apiportal.koreainvestment.com/apiservice-summary | 3a9be59 | examples_llm/overseas_stock/order/order.py → `order()` | OFFLINE_SIM | DOCUMENTED | 2026-10-31 | TR_ID: 실전 TTTT1006U / 모의 VTTT1001U, URL: /uapi/overseas-stock/v1/trading/order | 거래소별 TR_ID 상이, 모의는 지정가만 |
| KIS | US | STOCK/ETF | 해외주식 정정취소 | https://apiportal.koreainvestment.com/apiservice-summary | 3a9be59 | examples_llm/overseas_stock/order_rvsecncl/order_rvsecncl.py → `order_rvsecncl()` | OFFLINE_SIM | DOCUMENTED | 2026-10-31 | TR_ID: 거래소별 분기, URL: /uapi/overseas-stock/v1/trading/order-rvsecncl | ovrs_excg_cd별 TR_ID 분기, 원주문번호 필수 |
| KIS | US | STOCK/ETF | 해외주식 주문체결조회 | https://apiportal.koreainvestment.com/apiservice-summary | 3a9be59 | examples_llm/overseas_stock/inquire_ccnl/inquire_ccnl.py → `inquire_ccnl()` | OFFLINE_SIM | DOCUMENTED | 2026-10-31 | TR_ID: 확인 필요, URL: /uapi/overseas-stock/v1/trading/inquire-ccnl | pdno=% 전체조회, 기간/거래소 필터링 |
| KIS | KRX | DOMESTIC_BOND | 장내채권 현재가(시세) | https://apiportal.koreainvestment.com/apiservice-summary | 3a9be59 | examples_llm/domestic_bond/inquire_price/inquire_price.py → `inquire_price()` | OFFLINE_SIM | DOCUMENTED | 2026-10-31 | TR_ID: FHKBJ773400C0, URL: /uapi/domestic-bond/v1/quotations/inquire-price | fid_cond_mrkt_div_code=B |
| KIS | KRX | DOMESTIC_BOND | 장내채권 매수주문 | https://apiportal.koreainvestment.com/apiservice-summary | 3a9be59 | examples_llm/domestic_bond/order/ (확인 필요) | OFFLINE_SIM | UNVERIFIED | 2026-10-31 | examples_user/domestic_bond/ 확인 필요 | 단위/호가/경과이자/수수료 별도 |
| KIS | KRX | DOMESTIC_BOND | 장내채권 매도주문 | https://apiportal.koreainvestment.com/apiservice-summary | 3a9be59 | examples_llm/domestic_bond/order/ (확인 필요) | OFFLINE_SIM | UNVERIFIED | 2026-10-31 | examples_user/domestic_bond/ 확인 필요 | 단위/호가/경과이자/수수료 별도 |
| KIS | - | - | OAuth 인증(토큰발급) | https://apiportal.koreainvestment.com/apiservice-summary | 3a9be59 | kis_auth.py → `auth()`, `getTREnv()` | ALL | DOCUMENTED | 2026-10-31 | 실전:9443, 모의:29443 | 토큰 24h 유효, 1분당 1회 제한 |
| KIS | - | - | 실시간 시세(WebSocket) | https://apiportal.koreainvestment.com/apiservice-summary | 3a9be59 | domestic_stock_functions_ws.py, kis_auth.py → `KISWebSocket` | OFFLINE_SIM | DOCUMENTED | 2026-10-31 | 국내/해외 실시간 체결가/호가 | HTS ID 필요, 접속키 별도 API |
---

## 핵심 구현 참고사항

### 1. 호스트 분리 (필수)
| 환경 | REST 호스트 | WebSocket 호스트 |
|------|-------------|------------------|
| 실전(PROD) | `https://openapi.koreainvestment.com:9443` | `wss://ops.koreainvestment.com:31000` |
| 모의(VPS) | `https://openapivts.koreainvestment.com:29443` | `wss://ops.koreainvestment.com:21000` |

> **절대 코드에 상수로 하드코딩 금지**. 설정/환경변수로 분리하여 `mode`와 매칭.

### 2. 인증 토큰 관리
- `kis_auth.py`의 `auth(svr="prod"|"vps")` 사용
- 토큰 유효기간 24시간, 만료 전 갱신 필요
- 1분당 1회 발급 제한 → 앱 시작마다 재발급 금지
- `getTREnv()`로 계좌번호(`my_acct`), 상품코드(`my_prod`) 등 환경별 설정 획득

### 3. Rate Limiting (공지 2026-04-20 기준)
| 환경 | 초당 요청 제한 | 권장 구현값 |
|------|----------------|-------------|
| 실전 | 18 req/s | 3~5 req/s (보수적) |
| 모의 | 1 req/s | **0.5 req/s** (안전 마진) |

- Token Bucket + 직렬 큐 구현 (`broker/rate_limiter.py`)
- 인증 토큰 발급 별도 느린 큐
- GET 멱등 호출만 지수 백오프+지터 재시도, **POST 주문은 재시도 금지**

### 4. 국내주식 핵심 TR_ID 매핑
| 작업 | 실전 TR_ID | 모의 TR_ID |
|------|------------|------------|
| 현재가 시세 | FHKST01010100 | FHKST01010100 (동일) |
| 잔고조회 | TTTC8434R | VTTC8434R |
| 현금매수 | TTTC0012U | VTTC0012U |
| 현금매도 | TTTC0011U | VTTC0011U |
| 정정취소 | TTTC0013U | VTTC0013U |

### 5. 해외주식 핵심 TR_ID 매핑 (미국 NASD/NYSE/AMEX 기준)
| 작업 | 실전 TR_ID | 모의 TR_ID |
|------|------------|------------|
| 잔고조회 | TTTS3039R | VTTS3039R |
| 매수 주문 | TTTT1002U | VTTT1002U |
| 매도 주문 | TTTT1006U | VTTT1001U |
| 정정취소 | (거래소별 상이) | V 프리픽스 적용 |

> **주의**: 모의투자에서는 지정가(ord_dvsn=00)만 지원. 시장가/LOC/LOO 등은 실전만 가능.

### 6. 미확인/미구현 항목 (BLOCKED)
| 항목 | 사유 | 대응 |
|------|------|------|
| 해외주식 현재가 시세조회 (examples_llm 단일 파일) | examples_llm/overseas_stock/inquire_price/ 디렉토리 없음 | examples_user/overseas_stock_functions.py의 `inquire_price()` 분석 후 래핑 필요 |
| 국내주식 주문체결내역조회 TR_ID | examples_llm에 단일 파일 없음 | functions.py에서 TR_ID 확인 후 래핑 |
| 해외주식 정정취소 TR_ID | 거래소별 분기 로직 복잡 | order.py의 TR_ID 분기 로직 참조하여 구현 |
| 장내채권 주문(매수/매도) | 단위/호가/경과이자/수수료 별도 | P2에서 공식 기능 확인 후 구현 |
| 해외 개별채권 | 공식 지원 미확인 | 확인 전 주문 구현 금지 (UNSUPPORTED) |
| 레버리지/인버스 ETF 주문 | 상품 적격성 매핑 미확인 | 기본 차단, 사용자 별도 승인 전 불가 |
| 신용/미수/파생상품 | 프로젝트 범위 외 | 어댑터에 메서드 자체 노출 금지 |

---

## 다음 검증 단계 (P0-04 이후)

1. **KIS 모의계좌 키 발급** → `VERIFIED_READ` 전환 (조회 API 테스트)
2. **MockBroker로 오프라인 테스트 완료** → `OFFLINE_SIM` 검증
3. **KIS_PAPER 모의 주문 테스트** → `VERIFIED_PAPER` 전환 (지원 상품별 개별 확인)
4. **실거래 승인 전** → `VERIFIED_LIVE` 전환 (소액 1건 테스트)

---

## 변경 이력

| 버전 | 날짜 | 변경 내용 | 작성자 |
|------|------|-----------|--------|
| 1.0 | 2026-10-31 | 초기 작성: P0-01 공식 API 조사 완료 | EUvest Agent |
