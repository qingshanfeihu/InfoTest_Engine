#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一键清除项目中所有 python 代码的冗余注释。

保留:
- shebang (如 #!/usr/bin/env python)
- encoding (如 # -*- coding: utf-8 -*-)
- type checking / flags (如 type: ignore, noqa, pragma: no cover)
"""

from __future__ import annotations

import os
import tokenize
import io

def clean_file_comments(filepath: str):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(content).readline))
    except Exception as e:
        print(f"Error parsing tokens for {filepath}: {e}")
        return

    comments_by_line = {}
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            val = tok.string
            val_lower = val.lower()
            
            if any(x in val_lower for x in ['noqa', 'type: ignore', 'coding:', 'pylint:', 'pragma: no cover']) or val.startswith('#!'):
                continue
            line_idx = tok.start[0]
            col_idx = tok.start[1]
            comments_by_line[line_idx] = col_idx

    if not comments_by_line:
        return

    lines = content.splitlines(keepends=True)
    new_lines = []
    for i, line in enumerate(lines, start=1):
        if i in comments_by_line:
            col = comments_by_line[i]
            sliced = line[:col]
            stripped = sliced.rstrip()
            if not stripped:
                
                indent = sliced[:len(sliced)-len(sliced.lstrip())]
                new_line = indent + '\n' if line.endswith('\n') else indent
                new_lines.append(new_line)
            else:
                has_newline = line.endswith('\n')
                new_line = stripped
                if has_newline:
                    new_line += '\n'
                new_lines.append(new_line)
        else:
            new_lines.append(line)
            
    new_content = "".join(new_lines)
    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Cleaned comments in: {filepath} ({len(comments_by_line)} cleared)")

def main():
    roots = ["main", "tests", "scripts"]
    for r in roots:
        for root, dirs, files in os.walk(r):
            
            if any(p in root.split(os.sep) for p in [".venv", ".venv311", "__pycache__", ".git", ".pytest_cache"]):
                continue
            for file in files:
                if file.endswith(".py"):
                    filepath = os.path.join(root, file)
                    clean_file_comments(filepath)

if __name__ == "__main__":
    main()
