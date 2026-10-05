#!/usr/bin/env python3
"""Replace the simulator page HTML in dashboard.html."""

import re

html_file = r'templates/dashboard.html'

with open(html_file, 'r', encoding='utf-8') as f:
    content = f.read()

# Find the exact simulator page block
start_marker = '<!-- \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550 PAGE: SIMULATOR \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550 -->'
end_marker = '<!-- \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550 PAGE: OLAP PLAYGROUND'

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

if start_idx == -1:
    print("ERROR: Start marker not found!")
    print("Looking for:", repr(start_marker[:50]))
    # Try to find what's there
    for i, line in enumerate(content.split('\n')):
        if 'PAGE: SIMULATOR' in line:
            print(f"Found at line {i+1}: {repr(line)}")
elif end_idx == -1:
    print("ERROR: End marker not found!")
else:
    print(f"Found block: lines {start_idx} to {end_idx}")
    print(f"Block length: {end_idx - start_idx} chars")
    old_block = content[start_idx:end_idx]
    print("Old block first 200 chars:", repr(old_block[:200]))
