# Part 2b: Test method continuation
part2b = """        # 3. 마이그레이션 실행
        from invest_agent.storage.schema import migrate, get_schema_version
        migrate(self.db_path)

        # 4. 스키마 버전이 2로 업데이트되었는지 확인
        version = get_schema_version(self.db_path)
        assert version == 2

        # 5. FK가 RESTRICT로 변경되었는지 검증 (PRAGMA foreign_key_list)
        conn = sqlite3.connect(str(self.db_path))
        try:
            tables_with_fk = [
                ("evidence", "thesis_id"),
                ("decisions", "thesis_id"),
                ("decisions", "run_id"),
                ("orders", "run_id"),
                ("orders", "decision_id"),
                ("handoffs", "from_run_id"),
                ("handoffs", "to_run_id"),
                ("handoffs", "thesis_id"),
                ("handoffs", "previous_decision_id"),
                ("equity_snapshots", "run_id"),
            ]
            for table, fk_col in tables_with_fk:
                fk_list = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
                # 각 FK에 대해 ON DELETE RESTRICT 확인
                for fk in fk_list:
                    # fk 튜플: (id, seq, table, from, to, on_update, on_delete, match)
                    on_delete = fk[6]
                    assert on_delete == "RESTRICT", f"Table {table} FK {fk_col} should be RESTRICT, got {on_delete}"
        finally:
            conn.close()

        # 6. 데이터가 보존되었는지 검증
        from invest_agent.storage.repositories import (
            ThesisRepository, EvidenceRepository, DecisionRepository,
            AgentRunRepository, OrderRepository, HandoffRepository,
            EquitySnapshotRepository
        )
        thesis_repo = ThesisRepository(self.db_path)
        evidence_repo = EvidenceRepository(self.db_path)
        decision_repo = DecisionRepository(self.db_path)
        run_repo = AgentRunRepository(self.db_path)
        order_repo = OrderRepository(self.db_path)
        handoff_repo = HandoffRepository(self.db_path)
        snapshot_repo = EquitySnapshotRepository(self.db_path)

        assert thesis_repo.get(thesis_id) is not None
        assert evidence_repo.get(evidence_id) is not None
        assert decision_repo.get(decision_id) is not None
        assert run_repo.get(run_id) is not None
        assert order_repo.get(order_id) is not None
        assert handoff_repo.get(handoff_id) is not None
        assert snapshot_repo.get(snapshot_id) is not None

        # 7. 삭제 제한 검증: 자식이 있는 부모 삭제 시 IntegrityError 발생
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            # 가설 삭제 시도 (증거가 있으므로 실패해야 함)
            conn.execute("DELETE FROM theses WHERE id = ?", (thesis_id,))
            conn.commit()
            assert False, "Should have raised IntegrityError due to RESTRICT FK"
        except sqlite3.IntegrityError:
            pass  # Expected
        finally:
            conn.close()

        # 8. 자식이 없는 부모는 삭제 가능해야 함
        # 새로운 가설 생성 (자식 없음)
        new_thesis_id = str(uuid4())
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute(
                "INSERT INTO theses (id, asset_id, hypothesis, rationale, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (new_thesis_id, "US:AAPL", "New hypothesis", "New rationale", now, now),
            )
            conn.commit()
            # 자식 없으므로 삭제 가능
            conn.execute("DELETE FROM theses WHERE id = ?", (new_thesis_id,))
            conn.commit()
        finally:
            conn.close()
        # 삭제되었는지 확인
        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute("SELECT id FROM theses WHERE id = ?", (new_thesis_id,)).fetchone()
            assert row is None
        finally:
            conn.close()

"""

with open('tests/unit/test_storage.py', 'a', encoding='utf-8') as f:
    f.write(part2b)
print('Part 2b appended')