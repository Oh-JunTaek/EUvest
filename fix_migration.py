# Fix migration function
with open('src/invest_agent/storage/schema.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the function start
start_idx = content.find('def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:')
if start_idx == -1:
    print('Function not found')
    exit(1)

# Find the next function (migrate)
end_idx = content.find('\ndef migrate(', start_idx)
if end_idx == -1:
    print('Next function not found')
    exit(1)

# Replace the function
new_func = '''def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    \"\"\"v1(CASCADE FK) -> v2(RESTRICT FK) 마이그레이션.

    SQLite는 FK 변경 시 테이블 재생성이 필요하므로:
    1. 새 테이블(_v2) 생성 (RESTRICT FK) - DDL_STATEMENTS의 스키마 사용
    2. 데이터 복사
    3. 기존 테이블 삭제
    4. 새 테이블 이름 변경
    \"\"\"
    # FK가 있는 테이블들 (마이그레이션 순서 중요: 부모 테이블 먼저)
    tables_with_fk = [
        "evidence",
        "decisions",
        "orders",
        "handoffs",
        "equity_snapshots",
    ]

    # 각 테이블별로 재생성
    for table in tables_with_fk:
        # 임시 테이블명
        new_table = f"{table}_v2"

        # 기존 테이블 존재 확인
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()

        if not exists:
            continue

        # 새 테이블 생성 (DDL_STATEMENTS에서 해당 테이블의 CREATE 문 사용)
        # DDL_STATEMENTS에서 테이블 생성문 찾기
        create_ddl = None
        for ddl in DDL_STATEMENTS:
            if ddl.strip().upper().startswith("CREATE TABLE") and f"{table} (" in ddl:
                create_ddl = ddl
                break

        if not create_ddl:
            continue

        # 테이블명 변경하여 새 테이블 생성
        new_sql = create_ddl.replace(f"CREATE TABLE {table}", f"CREATE TABLE {new_table}")
        new_sql = new_sql.replace(f"CREATE TABLE IF NOT EXISTS {table}", f"CREATE TABLE IF NOT EXISTS {new_table}")

        conn.execute(new_sql)

        # 데이터 복사
        conn.execute(f"INSERT INTO {new_table} SELECT * FROM {table}")

        # 기존 테이블 삭제
        conn.execute(f"DROP TABLE {table}")

        # 새 테이블 이름 변경
        conn.execute(f"ALTER TABLE {new_table} RENAME TO {table}")

        # 인덱스 재생성 (인덱스는 DROP TABLE 시 자동 삭제됨)
        # 인덱스 생성문은 DDL_STATEMENTS에 있으므로 init_db 시 재생성됨

    # 인덱스 재생성
    index_ddls = [ddl for ddl in DDL_STATEMENTS if ddl.strip().upper().startswith("CREATE INDEX")]
    for ddl in index_ddls:
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass  # 이미 존재할 수 있음


'''

# Replace
new_content = content[:start_idx] + new_func + content[end_idx:]

with open('src/invest_agent/storage/schema.py', 'w', encoding='utf-8') as f:
    f.write(new_content)
print('Migration function fixed')