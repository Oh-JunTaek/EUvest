with open('tests/unit/test_evaluation.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the class structure
# The issue is that TestEvaluateDecision class is at wrong indentation
# Find and fix the class structure

# First, fix the TestEvaluationHelpers class closing and TestEvaluateDecision class
content = content.replace(
    'assert _check_price_confirmation_time(None, as_of, "1d", reasons) is False\nclass TestEvaluateDecision:',
    'assert _check_price_confirmation_time(None, as_of, "1d", reasons) is False\n\n\nclass TestEvaluateDecision:'
)

# Write back
with open('tests/unit/test_evaluation.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed class structure')