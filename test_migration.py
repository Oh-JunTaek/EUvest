import sys
sys.path.insert(0, 'src')
import tempfile
from pathlib import Path
import sqlite3

from invest_agent.storage.schema import ensure_db, migrate

# Test migration on a v2 database
tmp = Path(tempfile.mkdtemp())
db_path = str(tmp / 'test.db')

# Create v2 database (version 2)
conn = sqlite3.connect(db_path)
conn.execute('CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT)')
conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (2, '2024-01-01T00:00:00')")

# Create v2 tables (simplified)
conn.execute('''
CREATE TABLE theses (
    id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    metadata TEXT NOT NULL DEFAULT '{}'
)
''')
conn.execute('''
CREATE TABLE agent_runs (
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
''')
conn.execute('''
CREATE TABLE decisions (
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
''')
conn.execute('''
CREATE TABLE orders (
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
''')
conn.execute('''
CREATE TABLE handoffs (
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
''')
conn.execute('''
CREATE TABLE equity_snapshots (
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
''')
conn.execute('''
CREATE TABLE evidence (
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
''')
conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (2, '2024-01-01T00:00:00') ON CONFLICT(version) DO UPDATE SET applied_at=excluded.applied_at")
conn.commit()
conn.close()

print('v2 DB created, testing migrate...')
from invest_agent.storage.schema import migrate
migrate(db_path, target_version=3)
print('Migration successful!')

# Verify new tables
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Check new tables
for table in ['mock_account', 'mock_positions', 'processed_fills']:
    cursor.execute(f'SELECT * FROM {table}')
    rows = cursor.fetchall()
    print(f'{table}: {len(rows)} rows')
    for row in rows:
        print(f'  {dict(row)}')

# Check schema version
cursor.execute('SELECT * FROM schema_version')
print('Schema version:', cursor.fetchone())

conn.close()
print('Test passed!')