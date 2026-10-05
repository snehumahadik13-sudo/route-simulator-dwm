content = open('templates/dashboard.html', encoding='utf-8').read()
lines = content.split('\n')
for i, l in enumerate(lines):
    if 'simulator' in l.lower():
        print(f'{i+1}: {l}')
