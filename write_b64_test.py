import base64
import tempfile
import os
import yaml

# The test content as a base64 string (shortened for now - just a test)
test_content_b64 = "IyMjIHNldHRpbmdzLnB5IHNpZ250b3J5IFVuaXR0ZXN0LgoKcHJpbnQoJ1Rlc3QgZmlsZSB3cml0dGVuJykK"

with open('tests/unit/test_settings.py', 'w', encoding='utf-8') as f:
    f.write(base64.b64decode(test_content_b64).decode('utf-8'))

print('Test file written successfully')