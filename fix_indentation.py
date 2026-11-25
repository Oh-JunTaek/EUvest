with open('tests/unit/test_evaluation.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Fix indentation for TestEvaluationHelpers class methods
# The class starts at line 41, methods should be indented 4 spaces
# Currently the methods are at wrong indentation

# Let's rebuild the file properly
output_lines = []
in_test_evaluation_helpers = False
in_test_evaluate_decision = False
in_test_evaluate_decisions = False

for i, line in enumerate(lines):
    # Detect class boundaries
    if 'class TestEvaluationHelpers:' in line:
        in_test_evaluation_helpers = True
        in_test_evaluate_decision = False
        in_test_evaluate_decisions = False
    elif 'class TestEvaluateDecision:' in line:
        in_test_evaluation_helpers = False
        in_test_evaluate_decision = True
        in_test_evaluate_decisions = False
    elif 'class TestEvaluateDecisions:' in line:
        in_test_evaluation_helpers = False
        in_test_evaluate_decision = False
        in_test_evaluate_decisions = True
    elif line.strip().startswith('class ') and not line.startswith(' '):
        # New top-level class
        in_test_evaluation_helpers = False
        in_test_evaluate_decision = False
        in_test_evaluate_decisions = False

    # Fix indentation
    if in_test_evaluation_helpers:
        # Methods should be indented 4 spaces (inside class)
        if line.strip().startswith('def test_'):
            line = '    ' + line.lstrip()
        elif line.strip() and not line.startswith('    ') and not line.startswith('class ') and not line.strip().startswith('def '):
            # Content inside methods should be 8 spaces
            if line.strip() and not line.startswith('        ') and not line.startswith('    ') and line.strip() != '':
                line = '        ' + line.lstrip()
    elif in_test_evaluate_decision or in_test_evaluate_decisions:
        # Methods should be indented 4 spaces (inside class)
        if line.strip().startswith('def '):
            line = '    ' + line.lstrip()
        elif line.strip() and not line.startswith('    ') and not line.startswith('class '):
            # Content inside methods should be 8 spaces
            if line.strip() and not line.startswith('        ') and not line.startswith('    ') and line.strip() != '':
                line = '        ' + line.lstrip()

    output_lines.append(line)

with open('tests/unit/test_evaluation.py', 'w', encoding='utf-8') as f:
    f.writelines(output_lines)

print('Fixed indentation')