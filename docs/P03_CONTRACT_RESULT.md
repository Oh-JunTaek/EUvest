# P0-03 신규 저장 계약 작업 결과 — 2026-11-04

> 이후 보강과 최신 결과는 `P03_PROGRESS_2026-11-04.md`를 따른다.

## 상태: 진행 중 / 전체 인수 미완료

기존 v1/v2 DB는 자동 변환하지 않는다. 신규 DB는 `storage.contract_store.create_contract_db`로 별도 경로에만 만들며, 이미 있는 파일은 거부한다. 기존 저장소·설정은 신규 DB를 자동 사용하지 않는다. `11_OPEN_DECISIONS.md`의 P03-DATA-01 이행 규칙은 미해결이다.

`migrations/001_init.sql`, `002_ai_state.sql`에 문서 03 최소 테이블을 생성한다. `domain/contracts.py`는 intent의 Decimal·양수·시간대·4부분 자산 식별을 검증한다. `contract_store.py`는 버전 충돌 확인, 상태 추가, intent와 최초 감사 이벤트의 원자 저장 및 기본 무결성 검사를 제공한다. 감사 이벤트는 update/delete 및 중복키 replace를 거부한다.

## 검증 범위

- 임시 DB에서 신규 생성·기존 파일 거부, 필수 테이블, 거래소별 동일 심볼 분리, Decimal 보존, naive 시간 거부·UTC 변환을 확인했다.
- 두 연결의 동시 상태 변경 중 하나만 성공, 오래된 판단 거부, intent 중복키 및 이벤트 중복 시 롤백, 감사 이벤트 수정/삭제/교체 거부, 버전·외래키 이상 시 쓰기 차단을 확인했다.
- `.venv\Scripts\python.exe -m pytest -o addopts='' -q -p no:cacheprovider tests` → 91 passed. `.venv\Scripts\ruff.exe check src tests`와 `git diff --check` → 통과. 테스트는 임시 DB와 fixture뿐이다.

## 필수 잔여 사항

1. 신규 SQL 테이블의 존재는 모든 필드의 도메인 검증이나 Repository 구현을 뜻하지 않는다. 나머지 DTO·저장/조회·JSON 계약 검증, 금액·시간·자산 검증을 모든 쓰기 경로에 적용해야 한다. 기존 `domain/models.py`와 `storage/repositories.py`는 여전히 옛 계약과 naive 시간 방식을 사용한다.
2. `save_intent`는 저장만 담당하고 판단 JSON의 실제 스키마 검증, 위험 검증, 계좌 대사, 주문 제출을 수행하지 않는다. 테스트의 `schema_valid`는 fixture 값이다. 실행기에 연결하거나 거래가 안전하다고 판단하는 근거로 사용하면 안 된다.
3. 단일 DB 내 테스트 외 운영 DB 백업 복원, 강제 종료, 다중 프로세스·디스크 오류 검증은 NOT_TESTED다. 별도 DB에서 기존 이력을 누락 없이 참조할 이행 정책은 미결정이다.
4. T-018은 실행기가 없고, T-025는 저장 계층 충돌만 테스트했으며 실제 stale 주문 차단은 미검증이다. T-035는 FK/버전 이상에 대한 저장 거부만, T-039는 저장 키 분리만 확인했다.
5. 전체 P0-03 인수 전 P0-04 착수 금지. 실제 API 인증·계좌·주문은 NOT_TESTED / NO_LIVE.
