with open('src/invest_agent/evaluation.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace tabs with spaces
content = content.replace('\t', '    ')

with open('src/invest_agent/evaluation.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed tabs to spaces')