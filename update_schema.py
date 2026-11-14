# update_schema.py
import sys
sys.path.insert(0, 'src')

with open('src/invest_agent/storage/schema.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Update version
content = content.replace('SCHEMA_VERSION = 2', 'SCHEMA_VERSION = 3')

# Find handoffs table and add tables after it
old = '''    # handoffs 테이블
    """
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
    """,
    # equity_snapshots 테이블'''

new = '''    # handoffs 테이블
    """
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
    """,
    # mock_account: 모의 계좌 현금/환율 (OFFLINE_SIM 전용)
    """
    CREATE TABLE IF NOT EXISTS mock_account (
        id TEXT PRIMARY KEY DEFAULT 'default',
        cash_krw TEXT NOT NULL DEFAULT '0',
        cash_usd TEXT NOT NULL DEFAULT '0',
        fx_rate_usd_krw TEXT NOT NULL DEFAULT '1300',
        updated_at TEXT NOT NULL
    )
    """,
    # mock_positions: 모의 보유 포지션
    """
    CREATE TABLE IF NOT EXISTS mock_positions (
        asset_id TEXT PRIMARY KEY,
        quantity TEXT NOT NULL,
        avg_price TEXT NOT NULL,
        current_price TEXT NOT NULL,
        currency TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    # processed_fills: 처리된 체결 기록 (중복 방지)
    """
    CREATE TABLE IF NOT EXISTS processed_fills (
        fill_id TEXT PRIMARY KEY,
        order_id TEXT NOT NULL,
        asset_id TEXT NOT NULL,
        side TEXT NOT NULL,
        filled_qty TEXT NOT NULL,
        filled_price TEXT NOT NULL,
        processed_at TEXT NOT NULL
    )
    """,
    # equity_snapshots 테이블'''

if old in content:
    content = content.replace(old, new)
    content = content.replace('SCHEMA_VERSION = 2', 'SCHEMA_VERSION = 3')
    with open('src/invest_agent/storage/schema.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Schema updated successfully')
else:
    print('Pattern not found')
    # Debug: find the handoffs table
    idx = content.find('# handoffs 테이블')
    if idx >= 0:
        print('Found at:', idx)
        print(content[idx:idx+500])
    else:
        print('Not found')