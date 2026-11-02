# Part 3: Functions

functions_part = '''

def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """SQLite 연결 생성 (외래키 활성화, WAL 모드)."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path) -> None:
    """데이터베이스 초기화 (스키마 생성 + 버전 기록)."""
    conn = get_connection(db_path)
    try:
        for ddl in DDL_STATEMENTS:
            conn.execute(ddl)
        conn.execute(INITIAL_VERSION_DDL)
        conn.commit()
    finally:
        conn.close()


def get_schema_version(db_path: str | Path) -> int:
    """현재 스키마 버전 조회."""
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def _backup_db(db_path: Path) -> Path:
    """마이그레이션 전 백업 생성."""
    backup_path = db_path.with_suffix(f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(db_path, backup_path)
    return backup_path


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """v1(CASCADE FK) -> v2(RESTRICT FK) 마이그레이션.
    
    SQLite는 FK 변경 시 테이블 재생성이 필요하므로:
    1. 새 테이블(_v2) 생성 (RESTRICT FK)
    2. 데이터 복사
    3. 기존 테이블 삭제
    4. 새 테이블 이름 변경
    """
    tables_with_fk = [
        ("evidence", "thesis_id", "theses"),
        ("decisions", "thesis_id", "theses"),
        ("decisions", "run_id", "agent_runs"),
        ("orders", "run_id", "agent_runs"),
        ("orders", "decision_id", "decisions"),
        ("handoffs", "from_run_id", "agent_runs"),
        ("handoffs", "to_run_id", "agent_runs"),
        ("handoffs", "thesis_id", "theses"),
        ("handoffs", "previous_decision_id", "decisions"),
        ("equity_snapshots", "run_id", "agent_runs"),
    ]
    
    # 각 테이블별로 재생성
    for table, fk_col, ref_table in tables_with_fk:
        # 임시 테이블명
        new_table = f"{table}_v2"
        
        # 기존 테이블 스키마 조회
        create_sql = conn.execute(
            f"SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        
        if not create_sql:
            continue
            
        old_sql = create_sql[0]
        # ON DELETE CASCADE -> ON DELETE RESTRICT 변경
        new_sql = old_sql.replace("ON DELETE CASCADE", "ON DELETE RESTRICT")
        # 테이블명 변경
        new_sql = new_sql.replace(f"CREATE TABLE {table}", f"CREATE TABLE {new_table}")
        new_sql = new_sql.replace(f"CREATE TABLE IF NOT EXISTS {table}", f"CREATE TABLE IF NOT EXISTS {new_table}")
        
        # 새 테이블 생성
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


def migrate(db_path: str | Path, target_version: int = SCHEMA_VERSION) -> None:
    """마이그레이션 실행 (현재 버전 -> 타겟 버전)."""
    current = get_schema_version(db_path)
    if current >= target_version:
        return
    
    if target_version > SCHEMA_VERSION:
        raise ValueError(f"지원하지 않는 스키마 버전: {target_version} (최대: {SCHEMA_VERSION})")
    
    path = Path(db_path)
    backup_path = _backup_db(path)
    
    conn = get_connection(path)
    try:
        # 버전별 마이그레이션
        if current < 2 and target_version >= 2:
            _migrate_v1_to_v2(conn)
        
        # 버전 기록 업데이트 (최신 버전 추가)
        conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, ?)", 
                     (target_version, datetime.now().isoformat()))
        conn.commit()
    except Exception:
        # 실패 시 백업에서 복구
        conn.close()
        shutil.copy2(backup_path, path)
        raise
    finally:
        conn.close()


def ensure_db(db_path: str | Path) -> None:
    """DB가 없으면 초기화, 있으면 마이그레이션."""
    path = Path(db_path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        init_db(path)
    else:
        migrate(path)
'''

with open('src/invest_agent/storage/schema.py', 'a', encoding='utf-8') as f:
    f.write(functions_part)
print('Part 3 appended')