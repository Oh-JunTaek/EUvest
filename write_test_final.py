import base64
import tempfile
import os
import yaml

# The full test content as a base64 string (generated separately)
# This is a placeholder - we'll generate it in the next step
test_content_b64 = ""

with open('tests/unit/test_settings.py', 'w', encoding='utf-8') as f:
    f.write(base64.b64decode(test_content_b64).decode('utf-8'))

print('File written')