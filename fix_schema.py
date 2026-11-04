import sys
sys.path.insert(0, 'src')

with open('src/invest_agent/storage/schema.py', 'r', encoding='utf-8') as f_in:
    content = f_in.read()

print('File read, length:', len(content))
