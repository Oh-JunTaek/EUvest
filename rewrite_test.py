import re
with open('tests/unit/test_execution_p06.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Remove the helper function
content = re.sub(r'def calculate_sizing_proper\(\):[\s\S]*?

', '', content)

# Fix all calculate_sizing calls to use proper arguments
# This is a complex replacement - let's just rewrite the whole file
print('Script written')
