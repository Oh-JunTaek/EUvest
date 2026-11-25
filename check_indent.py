with open('src/invest_agent/evaluation.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
    for i, line in enumerate(lines[285:310], start=286):
        print(f'Line {i}: {repr(line[:80])}')