# Write schema.py in parts
# Part 1: Tables

tables_part1 = """    # theses 테이블
    \"\"\"
    CREATE TABLE IF NOT EXISTS theses (
        id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL,
        hypothesis TEXT NOT NULL,
        rationale TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        metadata TEXT NOT NULL DEFAULT '{}'
    )
    \"\"\",
    # evidence 테이블
    \"\"\"
    CREATE TABLE IF NOT EXISTS evidence (
        id TEXT PRIMARY KEY,
        thesis_id TEXT NOT NULL,
        evidence_type TEXT NOT NULL,
        source TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        collected_at TEXT NOT NULL,
        content TEXT NOT NULL DEFAULT '{}',
        raw_ref TEXT NOT NULL DEFAULT '',
        metadata TEXT NOT NULL DEFAULT '{}',
        FOREIGN KEY (thesis_id) REFERENCES theses(id) ON DELETE RESTRICT
    )
    \"\"\",
    # decisions 테이블
    \"\"\"
    CREATE TABLE IF NOT EXISTS decisions (
        id TEXT PRIMARY KEY,
        thesis_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        outcome TEXT NOT NULL,
        side TEXT,
        target_weight_bps INTEGER,
        current_weight_bps INTEGER,
        rationale TEXT NOT NULL,
        evidence_ids TEXT NOT NULL DEFAULT '[]',
        model_provider TEXT NOT NULL,
        model_name TEXT NOT NULL,
        execution_mode TEXT NOT NULL,
        decided_at TEXT NOT NULL,
        error TEXT,
        metadata TEXT NOT NULL DEFAULT '{}',
        FOREIGN KEY (thesis_id) REFERENCES theses(id) ON DELETE RESTRICT,
        FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE RESTRICT
    )
    \"\"\",
    # agent_runs 테이블
    \"\"\"
    CREATE TABLE IF NOT EXISTS agent_runs (
        id TEXT PRIMARY KEY,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        status TEXT NOT NULL,
        execution_mode TEXT NOT NULL,
        schedule_id TEXT,
        thesis_ids TEXT NOT NULL DEFAULT '[]',
        decision_ids TEXT NOT NULL DEFAULT '[]',
        order_ids TEXT NOT NULL DEFAULT '[]',
        error TEXT,
        metadata TEXT NOT NULL DEFAULT '{}'
    )
    \"\"\",
    # orders 테이블
    \"\"\"
    CREATE TABLE IF NOT EXISTS orders (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        decision_id TEXT NOT NULL,
        asset_id TEXT NOT NULL,
        side TEXT NOT NULL,
        order_type TEXT NOT NULL,
        quantity TEXT NOT NULL,
        price TEXT,
        status TEXT NOT NULL,
        broker_order_id TEXT,
        submitted_at TEXT,
        acknowledged_at TEXT,
        filled_at TEXT,
        filled_quantity TEXT NOT NULL DEFAULT '0',
        filled_price TEXT,
        commission TEXT NOT NULL DEFAULT '0',
        tax TEXT NOT NULL DEFAULT '0',
        error TEXT,
        metadata TEXT NOT NULL DEFAULT '{}',
        FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE RESTRICT,
        FOREIGN KEY (decision_id) REFERENCES decisions(id) ON DELETE RESTRICT
    )
    \"\"\",
"""

with open('src/invest_agent/storage/schema.py', 'a', encoding='utf-8') as f:
    f.write(tables_part1)
print('Part 1 appended')