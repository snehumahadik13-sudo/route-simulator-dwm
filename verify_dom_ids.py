import re

with open('templates/dashboard.html', encoding='utf-8') as f:
    html = f.read()

# Find querySelector and querySelectorAll
selectors = re.findall(r"querySelector(?:All)?\(['\"]([^'\"]+)['\"]\)", html)
print(f"Total querySelector calls: {len(selectors)}")
for s in set(selectors):
    print("  selector:", s)
