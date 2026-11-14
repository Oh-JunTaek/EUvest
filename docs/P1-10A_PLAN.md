# P1-10A OFFLINE_SIM 모의계좌 영속화 구현 계획

## 목표
OFFLINE_SIM 모드에서 MockBroker의 현금(KRW/USD), 보유 종목, 평균 매입가, 체결 결과가 프로그램 종료·재시작 이후에도 유지되도록 한다.

## 현재 상태 분석

### 기존 구조
- `MockBroker`: 메모리 내 `_cash_krw`, `_cash_usd`, `_positions`, `_orders` 관리
- SQLite: `theses`, `evidence`, `decisions`, `agent_runs`, `orders`, `handoffs` 테이블 존재
- 스키마 버전: v2 (v1→v2 마이그레이션 구현됨)
- `MockBroker`는 `BrokerProtocol` 구현체로 메모리 상태만 관리

### 필요한 변경 사항
1. **새 테이블 추가** (v2→v3 마이그레이션):
   - `mock_account`: 계좌 현금(KRW/USD), 환율 저장
   - `mock_positions`: 보유 종목(수량, 평균단가, 현재가, 통화) 저장
   - `processed_fills`: 중복 체결 방지용 체결 기록

2. **MockBroker 수정**:
   - 초기화 시 DB에서 계좌/포지션 복원 (없으면 초기값 사용)
   - `fill_order` 후 DB에 계좌/포지션 저장
   - 중복 방지: 체결 ID 기반 멱등성 보장

3. **마이그레이션**: v2→v4 (v3 건너뛰고 v4로, v3은 예약)

4. **테스트**: 재시작 시뮬레이션, KRW/USD 일관성, 중복 방지

## 구현 계획

### Phase 1: 스키마 및 마이그레이션 (v2→v3)
- `schema.py`에 DDL 추가
- `migrate` 함수에 `_migrate_v2_to_v3` 추가
- `SCHEMA_VERSION = 3` 업데이트

### Phase 2: MockBroker 영속화
- `__init__`에 DB 경로 추가, 복원 로직 추가
- `fill_order` 후 저장 로직 추가
- `set_quote`, `set_position`도 저장
- `processed_fills` 테이블로 중복 방지

### Phase 3: Orchestrator 연동
- `create_orchestrator`에서 DB 경로 전달
- `MockBroker` 생성 시 DB 경로 전달

### Phase 4: 테스트
- 재시작 시뮬레이션 테스트
- KRW/USD 일관성 검증
- 중복 체결 방지 테스트

## 기술적 세부사항

### 새 테이블 설계

```sql
-- 모의 계좌 현금/환율
CREATE TABLE IF NOT EXISTS mock_account (
    id TEXT PRIMARY KEY DEFAULT 'default',
    cash_krw TEXT NOT NULL DEFAULT '0',
    cash_usd TEXT NOT NULL DEFAULT '0',
    fx_rate_usd_krw TEXT NOT NULL DEFAULT '1300',
    updated_at TEXT NOT NULL
);

-- 모의 포지션
CREATE TABLE IF NOT EXISTS mock_positions (
    asset_id TEXT PRIMARY KEY,
    quantity TEXT NOT NULL,
    avg_price TEXT NOT NULL,
    current_price TEXT NOT NULL,
    currency TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 처리된 체결 기록 (중복 방지)
CREATE TABLE IF NOT EXISTS processed_fills (
    fill_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    side TEXT NOT NULL,
    filled_qty TEXT NOT NULL,
    filled_price TEXT NOT NULL,
    processed_at TEXT NOT NULL
);
```

### MockBroker 변경사항
- `__init__(db_path: str | Path | None = None, ...)`
- `_load_from_db()`: 초기화 시 호출
- `_save_account()`, `_save_position()`, `_save_fill()`: 변경 시 호출
- `_is_fill_processed(fill_id)`: 중복 체크

## 위험 요소 및 대응
- **DB 락 경합**: `ExecutionLock`과 별도 테이블이므로 경합 최소화
- **마이그레이션 실패**: 기존 v2 DB는 읽기 전용으로 보호, v3 생성 시에만 마이그레이션
- **동시성**: 단일 프로세스 가정, 스레드 락으로 보호

## 완료 기준 체크리스트
- [ ] 최초 실행 → Mock 매수 → 재시작 → 잔고/포지션 복원 성공
- [ ] 이후 추가 주문 시 기존 상태 기준 계산
- [ ] 중복 체결 방지 테스트 통과
- [ ] pytest 및 Ruff 통과
- [ ] 기존 테스트 225개 통과 유지