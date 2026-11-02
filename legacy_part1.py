# Part 1: Class definition and setup methods
# Part 1: Class definition and setup methods
part1 = """class TestMigrationFromLegacy:
    \"\"\"기존 DB(CASCADE FK)에서 신규 DB(RESTRICT FK)로 마이그레이션 테스트.\"\"\"

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()
        os.rmdir(self.temp_dir)

    def _create_legacy_db_with_cascade_fk(self):
        \"\"\"구버전 스키마(CASCADE FK)로 DB 생성.\"\"\"
        import sqlite3
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            conn.execute('''CREATE TABLE theses (id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, hypothesis TEXT NOT NULL, rationale TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1, metadata TEXT NOT NULL DEFAULT '{ }')''')
            conn.execute('''CREATE TABLE evidence (id TEXT PRIMARY KEY, thesis_id TEXT NOT NULL, evidence_type TEXT NOT NULL, source TEXT NOT NULL, observed_at TEXT NOT NULL, collected_at TEXT NOT NULL, content TEXT NOT NULL DEFAULT '{ }', raw_ref TEXT NOT NULL DEFAULT '', metadata TEXT NOT NULL DEFAULT '{ }', FOREIGN KEY (thesis_id) REFERENCES theses(id) ON DELETE CASCADE)''')
            conn.execute('''CREATE TABLE decisions (id TEXT PRIMARY KEY, thesis_id TEXT NOT NULL, run_id TEXT NOT NULL, outcome TEXT NOT NULL, side TEXT, target_weight_bps INTEGER, current_weight_bps INTEGER, rationale TEXT NOT NULL, evidence_ids TEXT NOT NULL DEFAULT '[]', model_provider TEXT NOT NULL, model_name TEXT NOT NULL, execution_mode TEXT NOT NULL, decided_at TEXT NOT NULL, error TEXT, metadata TEXT NOT NULL DEFAULT '{ }', FOREIGN KEY (thesis_id) REFERENCES theses(id) ON DELETE CASCADE, FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE CASCADE)''')
            conn.execute('''CREATE TABLE agent_runs (id TEXT PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT, status TEXT NOT NULL, execution_mode TEXT NOT NULL, schedule_id TEXT, thesis_ids TEXT NOT NULL DEFAULT '[]', decision_ids TEXT NOT NULL DEFAULT '[]', order_ids TEXT NOT NULL DEFAULT '[]', error TEXT, metadata TEXT NOT NULL DEFAULT '{ }')''')
            conn.execute('''CREATE TABLE orders (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, decision_id TEXT NOT NULL, asset_id TEXT NOT NULL, side TEXT NOT NULL, order_type TEXT NOT NULL, quantity TEXT NOT NULL, price TEXT, status TEXT NOT NULL, broker_order_id TEXT, submitted_at TEXT, acknowledged_at TEXT, filled_at TEXT, filled_quantity TEXT NOT NULL DEFAULT '0', filled_price TEXT, commission TEXT NOT NULL DEFAULT '0', tax TEXT NOT NULL DEFAULT '0', error TEXT, metadata TEXT NOT NULL DEFAULT '{ }', FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE CASCADE, FOREIGN KEY (decision_id) REFERENCES decisions(id) ON DELETE CASCADE)''')
            conn.execute('''CREATE TABLE handoffs (id TEXT PRIMARY KEY, from_run_id TEXT NOT NULL, to_run_id TEXT NOT NULL, thesis_id TEXT NOT NULL, previous_decision_id TEXT NOT NULL, previous_outcome TEXT NOT NULL, new_outcome TEXT NOT NULL, changed INTEGER NOT NULL, change_reason TEXT NOT NULL, model_provider_from TEXT NOT NULL, model_provider_to TEXT NOT NULL, model_name_from TEXT NOT NULL, model_name_to TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY (from_run_id) REFERENCES agent_runs(id) ON DELETE CASCADE, FOREIGN KEY (to_run_id) REFERENCES agent_runs(id) ON DELETE CASCADE, FOREIGN KEY (thesis_id) REFERENCES theses(id) ON DELETE CASCADE, FOREIGN KEY (previous_decision_id) REFERENCES decisions(id) ON DELETE CASCADE)''')
            conn.execute('''CREATE TABLE equity_snapshots (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, timestamp TEXT NOT NULL, total_equity TEXT NOT NULL DEFAULT '0', cash_balance TEXT NOT NULL DEFAULT '0', positions TEXT NOT NULL DEFAULT '{ }', unrealized_pnl TEXT NOT NULL DEFAULT '0', realized_pnl TEXT NOT NULL DEFAULT '0', metadata TEXT NOT NULL DEFAULT '{ }', FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE CASCADE)''')
            conn.execute('''CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))''')
            conn.execute("INSERT INTO schema_version (version) VALUES (1)")
            conn.commit()
        finally:
            conn.close()

"""

with open('tests/unit/test_storage.py', 'a', encoding='utf-8') as f:
    f.write(part1)
print('Part 1 appended')