import base64

# Full test content as a base64 string
# This is a placeholder - we'll replace with actual content
test_content_b64 = ""

with open('tests/unit/test_settings.py', 'w', encoding='utf-8') as f:
    f.write(base64.b64decode(test_content_b64).decode('utf-8'))

print('Test file written')