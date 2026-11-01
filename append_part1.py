import base64

# The test content to append (part 1: TestSchemaAndMigration and TestDataIntegrity)
content_part1 = """\n\n\nclass TestSchemaAndMigration:
    \"\"\"스키마 초기화 및 마이그레이션 테스트.\"\"\"

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()
        os.rmdir(self.temp_dir)

    def test_init_db_creates_all_tables(self):
        init_db(self.db_path)
        import sqlite3
        conn = sqlite3.connect(str(self.db_path))
        try:
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            table_names = [t[0] for t in tables]
            expected = {"theses", "evidence", "decisions", "agent_runs", "orders", "handoffs", "equity_snapshots", "schema_version"}
            for t in expected:
                assert t in table_names, f"Table {t} not created"
        finally:
            conn.close()

    def test_foreign_keys_enforced(self):
        init_db(self.db_path)
        import sqlite3
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO evidence (id, thesis_id, evidence_type, source, observed_at, collected_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (str(uuid4()), str(uuid4()), "PRICE", "test", datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
                )
        finally:
            conn.close()

    def test_schema_version_recorded(self):
        init_db(self.db_path)
        version = get_schema_version(self.db_path)
        assert version == 1

    def test_migrate_idempotent(self):
        init_db(self.db_path)
        migrate(self.db_path)
        version = get_schema_version(self.db_path)
        assert version == 1

    def test_wal_mode_enabled(self):
        init_db(self.db_path)
        import sqlite3
        conn = sqlite3.connect(str(self.db_path))
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode.upper() == "WAL"
        finally:
            conn.close()


class TestDataIntegrity:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        ensure_db(self.db_path)

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()
        os.rmdir(self.temp_dir)

    def test_decimal_precision_preserved_through_roundtrip(self):
        from invest_agent.storage.repositories import OrderRepository
        repo = OrderRepository(self.db_path)
        order = OrderRecord(
            id=uuid4(),
            run_id=uuid4(),
            decision_id=uuid4(),
            asset_id="KRX:005930",
            side=OrderSide.BUY,
            order_type="LIMIT",
            quantity=Decimal("10.123456789"),
            price=Decimal("70000.12345"),
            status=OrderStatus.ACKNOWLEDGED,
        )
        repo = OrderRepository(self.db_path)
        repo.save(order)
        retrieved = repo.get(order.id)
        assert retrieved.quantity == Decimal("10.123456789")
        assert retrieved.price == Decimal("70000.12345")

    def test_utc_timestamps_preserved(self):
        from invest_agent.storage.repositories import ThesisRepository
        repo = ThesisRepository(self.db_path)
        t = Thesis(id=uuid4(), asset_id="KRX:005930", hypothesis="H1", rationale="R1")
        repo.save(t)
        retrieved = repo.get(t.id)
        assert retrieved.created_at.tzinfo is None
        assert retrieved.updated_at.tzinfo is None

    def test_execution_mode_recorded(self):
        from invest_agent.storage.repositories import AgentRunRepository
        repo = AgentRunRepository(self.db_path)
        run = AgentRun(id=uuid4(), status=RunStatus.COMPLETED, execution_mode="KIS_PAPER")
        repo.save(run)
        retrieved = repo.get(run.id)
        assert retrieved.execution_mode == "KIS_PAPER"

    def test_duplicate_save_is_upsert(self):
        from invest_agent.storage.repositories import ThesisRepository
        repo = ThesisRepository(self.db_path)
        thesis = Thesis(id=uuid4(), asset_id="KRX:005930", hypothesis="H1", rationale="R1")
        repo.save(thesis)
        thesis.hypothesis = "H1_updated"
        repo.save(thesis)
        retrieved = repo.get(thesis.id)
        assert retrieved.hypothesis == "H1_updated"

    def test_cascade_delete_thesis_deletes_evidence(self):
        from invest_agent.storage.repositories import ThesisRepository, EvidenceRepository
        thesis_repo = ThesisRepository(self.db_path)
        evidence_repo = EvidenceRepository(self.db_path)

        thesis = Thesis(id=uuid4(), asset_id="KRX:005930", hypothesis="H1", rationale="R1")
        thesis_repo.save(thesis)

        evidence = Evidence(id=uuid4(), thesis_id=thesis.id, evidence_type=EvidenceType.PRICE, source="test", observed_at=datetime.utcnow(), collected_at=datetime.utcnow(), content={})
        evidence_repo.save(evidence)

        import sqlite3
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM theses WHERE id = ?", (str(thesis.id),))
        conn.commit()
        conn.close()

        assert evidence_repo.get(evidence.id) is None


"""
# Encode and save part 1
import base64
encoded = base64.b64encode(content_part1.encode('utf-8')).decode('ascii')
with open('append_part1.b64', 'w') as f:
    f.write(encoded)
print('Part 1 encoded')