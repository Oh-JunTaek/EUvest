import base64

# The test file content encoded in base64 to avoid shell escaping issues
encoded_content = "IyMjIHNldHRpbmdzLnB5IHNpZ250b3J5IFVuaXR0ZXN0LgoKcHJpbnQoJ1Rlc3QgZmlsZSB3cml0dGVuJykK"

with open('tests/unit/test_settings.py', 'w', encoding='utf-8') as f:
    f.write(base64.b64decode(encoded_content).decode('utf-8'))

print('File written')