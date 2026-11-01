import sys
sys.path.insert(0, '.')

import tempfile
import os
import sqlite3

from invest_agent.storage.schema import ensure_db

db = tempfile.mktemp(suffix='.db')
ensure_db(db)

conn = sqlite3.connect(db)
conn.execute('PRAGMA foreign_keys=ON')
cur = conn.execute('SELECT name, sql FROM sqlite_master WHERE type="table"')
tables = cur.fetchall()
for name, sql in tables:
    if sql:
        print(f"Table: {name}")
        print(sql[:200])
    else:
        print(f"SQL is None for table: {name}")

conn.close()
os.unlink(db)