with open(r'c:\Users\wns53\Documents\GitHub\EUvest\src\invest_agent\storage\schema.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Remove whitespace from blank lines
content = content.replace('            raise ValueError(f"지원하지 않는 기존 스키마 버전: {current}")\n\n        data_version', '            raise ValueError(f"지원하지 않는 기존 스키마 버전: {current}")\n        data_version')
content = content.replace('            raise sqlite3.OperationalError("스키마 버전이 변경됨: 마이그레이션 중단")\n\n        # v1 -> v2', '            raise sqlite3.OperationalError("스키마 버전이 변경됨: 마이그레이션 중단")\n        # v1 -> v2')
content = content.replace('            _migrate_v1_to_v2(conn)\n            current = 2\n\n        # v2 -> v3', '            _migrate_v1_to_v2(conn)\n            current = 2\n        # v2 -> v3')
content = content.replace('            _migrate_v2_to_v3(conn)\n            current = 3\n\n        conn.execute', '            _migrate_v2_to_v3(conn)\n            current = 3\n        conn.execute')

with open(r'c:\Users\wns53\Documents\GitHub\EUvest\src\invest_agent\storage\schema.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Fixed schema.py')