# Part 2: handoffs, equity_snapshots, indexes, schema_version

tables_part2 = """    # handoffs 테이블
    \"\"\"
    CREATE TABLE IF NOT EXISTS handoffs (
        id TEXT PRIMARY KEY,
        from_run_id TEXT NOT NULL,
        to_run_id TEXT NOT NULL,
        thesis_id TEXT NOT NULL,
        previous_decision_id TEXT NOT NULL,
        previous_outcome TEXT NOT NULL,
        new_outcome TEXT NOT NULL,
        changed INTEGER NOT NULL,
        change_reason TEXT NOT NULL,
        model_provider_from TEXT NOT NULL,
        model_provider_to TEXT NOT NULL,
        model_name_from TEXT NOT NULL,
        model_name_to TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (from_run_id) REFERENCES agent_runs(id) ON DELETE RESTRICT,
        FOREIGN KEY (to_run_id) REFERENCES agent_runs(id) ON DELETE RESTRICT,
        FOREIGN KEY (thesis_id) REFERENCES theses(id) ON DELETE RESTRICT,
        FOREIGN KEY (previous_decision_id) REFERENCES decisions(id) ON DELETE RESTRICT
    )
    \"\"\",
    # equity_snapshots 테이블
    \"\"\"
    CREATE TABLE IF NOT EXISTS equity_snapshots (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        total_equity TEXT NOT NULL DEFAULT '0',
        cash_balance TEXT NOT NULL DEFAULT '0',
        positions TEXT NOT NULL DEFAULT '{}',
        unrealized_pnl TEXT NOT NULL DEFAULT '0',
        realized_pnl TEXT NOT NULL DEFAULT '0',
        metadata TEXT NOT NULL DEFAULT '{}',
        FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE RESTRICT
    )
    \"\"\",
    # 인덱스
    "CREATE INDEX IF NOT EXISTS idx_theses_asset_id ON theses(asset_id)",
    "CREATE INDEX IF NOT EXISTS idx_theses_active ON theses(is_active)",
    "CREATE INDEX IF NOT EXISTS idx_evidence_thesis_id ON evidence(thesis_id)",
    "CREATE INDEX IF NOT EXISTS idx_decisions_thesis_id ON decisions(thesis_id)",
    "CREATE INDEX IF NOT EXISTS idx_decisions_run_id ON decisions(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON agent_runs(status)",
    "CREATE INDEX IF NOT EXISTS idx_agent_runs_started_at ON agent_runs(started_at)",
    "CREATE INDEX IF NOT EXISTS idx_orders_run_id ON orders(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_orders_decision_id ON orders(decision_id)",
    "CREATE INDEX IF NOT EXISTS idx_handoffs_thesis_id ON handoffs(thesis_id)",
    "CREATE INDEX IF NOT EXISTS idx_handoffs_from_run ON handoffs(from_run_id)",
    "CREATE INDEX IF NOT EXISTS idx_handoffs_to_run ON handoffs(to_run_id)",
    "CREATE INDEX IF NOT EXISTS idx_equity_snapshots_run_id ON equity_snapshots(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_equity_snapshots_timestamp ON equity_snapshots(timestamp)",
    # 스키마 버전 테이블
    \"\"\"
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    \"\"\",
]

INITIAL_VERSION_DDL = \"\"\"
INSERT OR IGNORE INTO schema_version (version) VALUES (1)
\"\"\"
"""

with open('src/invest_agent/storage/schema.py', 'a', encoding='utf-8') as f:
    f.write(tables_part2)
print('Part 2 appended')