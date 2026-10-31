# 설계 패키지 구성 검사 결과

- 작성: 2026-10-31
- 범위: **설계 문서** 및 JSON Schema 견본. 애플리케이션 코드 구현/실계좌 API 테스트는 아직 수행하지 않음.
- 1. 패키지 README 및 AGENTS.md 존재
- 2. 공식 자료 URL 기재 및 KIS 지원 구분표 포함
- 3. `schemas` JSON Schema 검증 성공, 예제 JSON 검증 성공
- 4. YAML 설정 파싱 성공, 실행 기본값 OFFLINE_SIM/스케줄 OFF/실거래 OFF
- 5. 실제 credentials를 포함하지 않는 `.env.example`만 제공
- 6. 주문·실거래/모의 환경·AI 인계·실패 복구 필수 테스트 작성
- 7. 사용자 미결정 정책은 `docs/11_OPEN_DECISIONS.md`에 수록

**중요:** 이 검사는 문서 간 기계구문 검증일 뿐 거래 시스템의 안전성을 증명하지 않는다. 실주문 코드나 브로커 API를 실행하지 않았다.
