import base64

# Decode and append part 1
with open('append_part1.b64', 'r', encoding='utf-8') as f:
    content = f.read()
decoded = base64.b64decode(content).decode('utf-8')
with open('tests/unit/test_storage.py', 'a', encoding='utf-8') as f:
    f.write(decoded)
print('Part 1 appended')

# Decode and append part 2
with open('append_part2.b64', 'r', encoding='utf-8') as f:
    content = f.read()
decoded = base64.b64decode(content).decode('utf-8')
with open('tests/unit/test_storage.py', 'a', encoding='utf-8') as f:
    f.write(decoded)
print('Part 2 appended')

print('All appended')