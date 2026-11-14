# add_migration.py - Add v2 to v3 migration function
import sys
sys.path.insert(0, 'src')

with open('src/invest_agent/storage/schema.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add _migrate_v2_to_v3 function after _migrate_v1_to_v2
if 'def _migrate_v2_to_v3' not in content:
    # Find the end of _migrate_v1_to_v2 function
    idx = content.find('def _migrate_v1_to_v2')
    if idx >= 0:
        # Find the next function definition
        next_func = content.find('\ndef ', idx + 1)
        if next_func >= 0:
            # Insert the new function before the next function
            new_func = '''

def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """v2 -> v3 마이그레이션: 모의 계좌 영속화 테이블 추가.

    새 테이블 추가:
    - mock_account: 모의 계좌 현금/환율
    - mock_positions: 모의 보유 포지션
    - processed_fills: 처리된 체결 기록 (중복 방지)

    이 테이블들은 기존 데이터와 무관하게 새로 생성되므로 단순 생성만 수행.
    """
    # 새 테이블 생성
    for ddl in DDL_STATEMENTS:
        if 'CREATE TABLE IF NOT EXISTS mock_account' in ddl:
            conn.execute(ddl)
            print("Created mock_account table")
        elif 'CREATE TABLE IF NOT EXISTS mock_positions' in ddl:
            conn.execute(ddl)
            print("Created mock_positions table")
        elif 'CREATE TABLE IF NOT EXISTS processed_fills' in ddl:
            conn.execute(ddl)
            print("Created processed_fills table")

    # 기본 mock_account 레코드 생성 (없는 경우)
    existing = conn.execute("SELECT 1 FROM mock_account WHERE id = 'default'").fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO mock_account (id, cash_krw, cash_usd, fx_rate_usd_krw, updated_at) VALUES (?, ?, ?, ?, ?)",
            ('default', '0', '0', '1300', datetime.now(UTC).isoformat())
        )
        print("Inserted default mock_account record")

    print("Migration v2 -> v3 completed")


'''
            content = content[:next_func] + new_func + content[next_func:]
            print('Added _migrate_v2_to_v3 function')
        else:
            print('Could not find next function')
    else:
        print('Could not find _migrate_v1_to_v2')

# Update migrate function to call _migrate_v2_to_v3
old_migrate = '_migrate_v1_to_v2(conn)'
new_migrate = '_migrate_v1_to_v2(conn)\n        _migrate_v2_to_v3(conn)'
if old_migrate in content:
    content = content.replace(old_migrate, new_migrate)
    print('Updated migrate function')
else:
    print('Could not find migrate call')

with open('src/invest_agent/storage/schema.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Migration function added and migrate updated')