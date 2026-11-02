# Part 2a: Test method start
part2a = """    def test_migrate_legacy_db_preserves_data_and_changes_fk_to_restrict(self):
        \"\"\"구버전 DB 마이그레이션: 데이터 보존 + FK가 RESTRICT로 변경.\"\"\"
        # 1. 구버전 DB(CASCADE FK) 생성
        self._create_legacy_db_with_cascade_fk()

        # 2. 테스트 데이터 삽입
        import sqlite3
        from uuid import uuid4
        from datetime import datetime
        from decimal import Decimal
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            thesis_id = str(uuid4())
            run_id = str(uuid4())
            decision_id = str(uuid4())
            evidence_id = str(uuid4())
            order_id = str(uuid4())
            handoff_id = str(uuid4())
            snapshot_id = str(uuid4())

            now = datetime.utcnow().isoformat()

            # 가설
            conn.execute(
                "INSERT INTO theses (id, asset_id, hypothesis, rationale, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (thesis_id, "KRX:005930", "Test hypothesis", "Test rationale", now, now),
            )
            # 실행
            conn.execute(
                "INSERT INTO agent_runs (id, started_at, status, execution_mode) VALUES (?, ?, ?, ?)",
                (run_id, now, "COMPLETED", "OFFLINE_SIM"),
            )
            # 판단
            conn.execute(
                "INSERT INTO decisions (id, thesis_id, run_id, outcome, rationale, model_provider, model_name, execution_mode, decided_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (decision_id, thesis_id, run_id, "TRADE", "Test rationale", "nvidia", "nemotron", "OFFLINE_SIM", now),
            )
            # 증거
            conn.execute(
                "INSERT INTO evidence (id, thesis_id, evidence_type, source, observed_at, collected_at, content) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (evidence_id, thesis_id, "PRICE", "test", now, now, '{"price": 70000}'),
            )
            # 주문
            conn.execute(
                "INSERT INTO orders (id, run_id, decision_id, asset_id, side, order_type, quantity, price, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (order_id, run_id, decision_id, "KRX:005930", "BUY", "LIMIT", "10", "70000", "ACKNOWLEDGED"),
            )
            # 인계
            conn.execute(
                "INSERT INTO handoffs (id, from_run_id, to_run_id, thesis_id, previous_decision_id, previous_outcome, new_outcome, changed, change_reason, model_provider_from, model_provider_to, model_name_from, model_name_to, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (handoff_id, run_id, run_id, thesis_id, decision_id, "NO_TRADE", "TRADE", 1, "test", "fake", "nvidia", "model1", "model2", now),
            )
            # 스냅샷
            conn.execute(
                "INSERT INTO equity_snapshots (id, run_id, timestamp, total_equity, cash_balance) VALUES (?, ?, ?, ?, ?)",
                (snapshot_id, run_id, now, "100000000", "50000000"),
            )
            conn.commit()
        finally:
            conn.close()

"""

with open('tests/unit/test_storage.py', 'a', encoding='utf-8') as f:
    f.write(part2a)
print('Part 2a appended')