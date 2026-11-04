import base64
import os

# The complete schema.py content as base64
encoded = os.environ.get('SCHEMA_B64', '')
decoded = base64.b64decode(encoded).decode('utf-8')
with open('src/invest_agent/storage/schema.py', 'w', encoding='utf-8') as f:
    f.write(decoded)
print('Schema written')
