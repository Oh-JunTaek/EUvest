# 11 — 사용자 결정 필요 항목 / 안전한 기본값 / 작업 차단 범위

이 문서에 적힌 질문 외에 사용자에게 반복해서 질문하지 말 것. **미결정이어도 OFFLINE_SIM/READ_ONLY/PAPER 개발은 진행 가능**해야 한다. `BLOCKING_LIVE`는 실거래 전 반드시 승인받는다.

| ID | 항목 | 현재 안전 기본값 | 언제 결정 필요한가 | 구분 |
|---|---|---|---|---|
| D-01 | 처음 허용할 거래 종목 | `[]`(빈 목록) / 데이터 조회 샘플 KRX 005930, US VOO 가능 | 실제 paper 자동거래 전에 | PAPER_BLOCKING |
| D-02 | 실거래 시작 자금 | 미정, 입력/입금액 추적 기능만 구현 | LIVE 활성화 전에 | BLOCKING_LIVE |
| D-03 | 단일 주문 최대 금액, 하루 신규 매수 한도 | `null` → LIVE_BLOCKED, paper에서 낮은 가상 예산 | LIVE 활성화 전에 | BLOCKING_LIVE |
| D-04 | 계좌 손실 보호 정책, 최대 보유 노출 및 거래 제한 | 미정 → LIVE_BLOCKED; 오프라인은 테스트용 소액 제한 | LIVE 활성화 전에 | BLOCKING_LIVE |
| D-05 | 거래 허용 시장 | KRX=ON, US=ON(계정 지원 확인 전 주문 없음) | 첫 모의 주문 전 설정 가능 | NONBLOCKING |
| D-06 | 초기 허용 상품 | 현물 주식·일반 ETF, 레버리지/인버스 기본 차단 | 초기 paper 이전 | NONBLOCKING |
| D-07 | 초반 운영 모델 공급자 | `FakeProvider`, 실제 외부/로컬 모델 미연결 | 실 AI 테스트 시작 시 | AI_TEST_BLOCKING |
| D-08 | 무료 원격 API 실제 거래 이용약관 | 미검증 → 해당 provider LIVE_BLOCKED | 실 AI LIVE 전 | BLOCKING_LIVE |
| D-09 | PC 전원·작업 시간 | Windows 작업스케줄러, 스케줄 OFF, 정규장만 | 무인 운용 전 | NONBLOCKING |
| D-10 | 수수료/환율/최소 수량 | KIS 사용자 계정 수수료표 미확인 → 실주문 차단 | PAPER/LIVE order 검증 전 | BLOCKING_LIVE |
| D-11 | KIS APP 키·모의계좌 사용 | 미입력 → Mock/READ_ONLY만 | 실제 KIS 조회 시작 시 | ACCOUNT_BLOCKING |
| D-12 | US 자동 환전 여부 | **OFF**. 보유 USD만 매수, 자동 환전 기능 미구현 | USD 없는 계좌에서 US 주문 전 | OPTIONAL |
| D-13 | AI 신규 종목 발굴·추가 | 정보 수집 후보만 제안, 실제 허용 목록 자동 변경 불가 | 나중에 전략 확장 시 | OPTIONAL |
| D-14 | 레버리지 ETF 옵트인 | 기본 OFF, 초기 실거래 기능 미지원 | 별도 확장 시 | OPTIONAL |
| D-15 | Android Gemma E2B | 후속 PoC, PC 주문 엔진 영향 없음 | P3 | OPTIONAL |
| D-16 | 성과 기준선 | 시장별 단순 보유 + 정기매수 모두 기록, 상세 종목 나중 선택 | 평가 리포트 작성 시 | NONBLOCKING |
| D-17 | 주문유형 | 정규장 지정가, 공식 지원 확인 뒤 PAPER 검증 | KIS paper 주문 전 | PAPER_BLOCKING |
| D-18 | 백테스트 Docker LEAN 도입 | 오프라인 최소 백테스트 먼저, Docker는 별도 승인 | P2-13 | OPTIONAL |

## 처음 사용자에게 물어볼 4가지 (대답을 기다리되 개발 전체를 막지 말 것)
1. 최초 PAPER 실험 허용 종목은 KRX 1~2개와 미국 ETF 1~2개처럼 제한할까, 직접 목록을 넣을까? (현재 빈 목록 유지)
2. 첫 운영 모델은 로컬 Ollama부터 시험할지, 무료 원격 API를 먼저 시험할지? (둘 다 구현, 기본 Fake)
3. 자동 실험 실행 주기는 매 60분을 기본값으로 둘까, 시장별 정규장 시작·종료 시점에 하루 2회로 둘까? (기본 스케줄 OFF)
4. 미국 주식은 보유 USD만 사용하고 자동 환전은 일단 제외할까? (안전 기본값 OFF)

## 실거래 활성화 직전에 반드시 사용자에게 재질문할 것
- 실거래에 할당할 전용 계좌와 현금 자본, 허용 자산 목록
- 하루 손실/월 최대 낙폭, 단일 주문 금액, 계좌 전체 노출 최대치
- 미국 주식 환전·세금·수수료와 채권 거래 관련 추가 확인
- 사용하고자 하는 운영 LLM 공급자의 실제 거래 사용 허가 여부와 개인정보 정책
- 계좌 연결 및 종목별 PAPER 통합 검증 수행 여부

## 사용자가 변경하면 안 되는 강제 제한
`cash_only=true`, `no_margin=true`, `no_short=true`, `no_auto_credit=true`는 개발팀 임의 완화 불가. 사용자가 나중에 레버리지 ETF 매수를 허용하더라도 **신용/미수 주문 허용과 별개**이며 기본 설정은 여전히 OFF.
