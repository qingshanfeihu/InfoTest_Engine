#!/usr/bin/env python3
r"""AsciiDoc -> Markdown 转换工具。用于将产品 CLI 手册(.adoc)转为可读 Markdown。

用法:
    # 单个文件
    python scripts/adoc_to_md.py <src.adoc> [dst.md]
    不指定 dst.md 时自动输出到同目录下的同名 .md 文件。

    # 批量转换文件夹
    python scripts/adoc_to_md.py --dir <dir_path>
    转换指定文件夹下所有 .adoc 文件。

转换规则:
    = Title       -> # Title
    == Section    -> ## Section
    === Sub       -> ### Sub
    ==== SubSub   -> #### SubSub
    *bold*        -> **bold**
    ....          -> ``` 代码块
    |===          -> 表格 -> | 参数 | 说明 | 格式
    [NOTE]..====  -> > blockquote
    * list        -> - list
    image::       -> ![]()

依赖: Python 3.8+(标准库，无第三方依赖)
"""

import re
import sys
from pathlib import Path


def _clean_cell(s: str) -> str:
    """Clean adoc table cell: remove trailing | and a| marker."""
    s = s.strip()
    # Remove trailing | (cell delimiter) -- only if NOT part of 'param | desc'
    if s.endswith("|") and " | " not in s:
        s = s[:-1].strip()
    # Remove trailing a| marker (adoc cell continuation marker)
    s = re.sub(r"\s+a\s*$", "", s)
    # Clean adoc escaped pipes: \| -> |
    s = s.replace("\\|", "|")
    return s.strip()


def _split_inline_cell(content: str) -> tuple[str, str]:
    r"""Split a cell like 'param | desc' into (param, desc).

    Matches: 'param |desc'  or  'param|desc'  or  'param a|desc'
    Also handles adoc escaped pipe: 'param1 \|param2|' -> ('param1 |param2', '')
    """
    # First try: param (with optional 'a') followed by unescaped | followed by desc
    m = re.match(r"^(\S+)\s*a?\|(.*)$", content)
    if m:
        param_part = m.group(1).strip().replace("\\|", "|")
        desc_part = m.group(2).strip()
        return param_part, desc_part
    # Second try: handle escaped \| -- find the LAST unescaped | as delimiter
    last_pipe = content.rfind("|")
    if last_pipe > 0 and (last_pipe == 0 or content[last_pipe - 1] != "\\"):
        before = content[:last_pipe].strip()
        after = content[last_pipe + 1:].strip()
        before = re.sub(r"\s+a\s*$", "", before).strip()
        before = before.replace("\\|", "|")
        return before, after
    return content.strip(), None  # No | found -- not an inline cell


# 命令签名行：行首单星命令主体 *cmd*（adoc 把命令主体标成 *bold*，参数标成 _italic_）。
# body 首字符限非空白非星 → 排除 `* 列表项`（body 以空格起）与已加粗 `**...**`。
_CMD_SIG_RE = re.compile(r"^(\s*)\*([^*\s][^*]*)\*(.*)$")


def _bold_leading_command(s: str) -> str:
    """行首命令签名 ``*cmd*[...]`` → ``**cmd**[...]``（通用，幂等）。

    手册里每条命令签名独占一行、行首即命令主体；参数走 ``_斜体_`` 不受影响。
    已是 ``**粗体**`` / 列表项 ``* item`` / 无闭合星的行一律不动。
    """
    if s.lstrip().startswith("**"):
        return s
    m = _CMD_SIG_RE.match(s)
    if m:
        indent, body, rest = m.groups()
        return f"{indent}**{body}**{rest}"
    return s


def _bold(s: str) -> str:
    """Convert adoc *bold* to markdown **bold**.

    两类：(1) 行首命令签名 → 通用加粗（覆盖全部命令，不再 sdns 偏置）；
    (2) 正文里的行内命令引用 → 保留原 sdns/config/slb/ha 白名单加粗（lookaround 防双重加粗）。
    """
    s = _bold_leading_command(s)
    if s.lstrip().startswith("**"):
        return s  # 行首命令签名已加粗，不再做行内处理
    s = re.sub(r"(?<!\*)\*(sdns\s+\S[\s\S]*?)\*(?!\*)", r"**\1**", s)
    s = re.sub(r"(?<!\*)\*(show\s+sdns[\s\S]*?)\*(?!\*)", r"**\1**", s)
    s = re.sub(r"(?<!\*)\*(clear\s+sdns[\s\S]*?)\*(?!\*)", r"**\1**", s)
    s = re.sub(r"(?<!\*)\*(no\s+sdns[\s\S]*?)\*(?!\*)", r"**\1**", s)
    s = re.sub(r"(?<!\*)\*(config\s+\S[\s\S]*?)\*(?!\*)", r"**\1**", s)
    s = re.sub(r"(?<!\*)\*(slb\s+\S[\s\S]*?)\*(?!\*)", r"**\1**", s)
    s = re.sub(r"(?<!\*)\*(ha\s+\S[\s\S]*?)\*(?!\*)", r"**\1**", s)
    s = re.sub(r"(?<!\*)\*(on/off)\*(?!\*)", r"**\1**", s)
    return s


def convert_adoc_to_md(src_path: Path, dst_path: Path) -> int:
    """Convert .adoc to .md. Returns number of tables converted."""
    with open(src_path, encoding="utf-8") as f:
        lines = f.readlines()

    out = []
    in_code = False
    in_note = False
    note_lines = []
    in_table = False
    in_table_note = False
    table_rows = []
    cur_param = ""
    cur_desc = []

    def _emit_table():
        nonlocal table_rows, cur_param, cur_desc
        if cur_param:
            table_rows.append((cur_param, cur_desc))
            cur_param = ""
            cur_desc = []
        if not table_rows:
            return
        out.append("| 参数 | 说明 |")
        out.append("|------|------|")
        for p, d in table_rows:
            desc = "<br>".join(x.strip() for x in d if x.strip())
            out.append(f"| {p.strip()} | {desc} |")
        out.append("")
        table_rows = []

    def _emit_note():
        nonlocal note_lines
        if not note_lines:
            return
        out.append("> **注意：**")
        out.append(">")
        for nl in note_lines:
            t = nl.strip()
            t = re.sub(r"^\d+\.\s*\*?\s*", "", t)
            t = re.sub(r"^\*\s*", "", t)
            if t:
                out.append(f"> {t}")
        out.append("")
        note_lines = []

    for s in (l.rstrip() for l in lines):
        # Code blocks
        if s == "....":
            _emit_table()
            _emit_note()
            out.append("```")
            in_code = not in_code
            continue
        if in_code:
            out.append(s)
            continue

        # [NOTE] block -- inside table: part of cell description; outside: blockquote
        if s == "[NOTE]":
            if in_table:
                in_table_note = True
                cur_desc.append("")
            else:
                _emit_table()
                in_note = True
                note_skipped_start = False
            continue
        if in_note:
            if s == "====":
                if not note_skipped_start:
                    note_skipped_start = True
                    continue
                _emit_note()
                in_note = False
                continue
            note_lines.append(s)
            continue

        # ==== end marker -- check table note FIRST, then treat as stray
        if s == "====":
            if in_table_note:
                in_table_note = False
                cur_desc.append("")
                continue
            continue

        # Table attributes -- skip
        if re.match(r"^\[width=", s) or re.match(r"^\[cols=", s):
            continue

        # Table start/end
        if s == "|===":
            if in_table:
                _emit_table()
                in_table = False
            else:
                _emit_table()
                in_table = True
                cur_param = ""
                cur_desc = []
            continue

        # Table cell -- alternate param / desc columns
        if in_table:
            cell = re.match(r"^\|(.+)$", s)
            if cell:
                raw = cell.group(1)
                param, inline_desc = _split_inline_cell(raw)
                if inline_desc is not None:
                    # Found a | delimiter -- save previous row first
                    if cur_param:
                        table_rows.append((cur_param, cur_desc))
                        cur_param = ""
                        cur_desc = []
                    if inline_desc:
                        # Full inline row: param and desc on same | line
                        table_rows.append((param, [inline_desc]))
                    else:
                        # Desc is empty -- start new param (for multi-line cells)
                        cur_param = param
                        cur_desc = []
                elif cur_param:
                    # Previous param exists -- this is its desc
                    desc_text = _clean_cell(raw)
                    cur_desc.append(desc_text)
                    table_rows.append((cur_param, cur_desc))
                    cur_param = ""
                    cur_desc = []
                else:
                    # New param
                    cur_param = _clean_cell(raw)
                    cur_desc = []
                continue
            # Continuation line (no |)
            if cur_param:
                cur_desc.append(s)
            continue

        # Not in table
        _emit_table()

        # Headings
        if s.startswith("==== "):
            out.append(f"#### {s[5:]}")
            out.append("")
            continue
        if s.startswith("=== "):
            out.append(f"### {s[4:]}")
            out.append("")
            continue
        if s.startswith("== "):
            out.append(f"## {s[3:]}")
            out.append("")
            continue
        if s.startswith("= "):
            out.append(f"# {s[2:]}")
            out.append("")
            continue

        # Images
        if s.startswith("image::"):
            m = re.match(r"image::([^\[]+)\[(.*)\]", s)
            if m:
                out.append(f"![{m.group(2)}]({m.group(1)})")
                out.append("")
            continue

        # List items
        if re.match(r"^\*\s+", s):
            out.append(f"- {s[2:]}")
            continue

        out.append(_bold(s))

    _emit_table()
    _emit_note()

    content = "\n".join(out)
    content = content.replace("***", "**")
    # 清 adoc 转义残留：`\{` `\}` `\[` `\]` 是 adoc 防属性替换的转义，markdown 里应还原为
    # 裸括号(否则命令签名 `**waf log audit \{on|off}**` 的 `\` 污染命令主体解析)。
    content = re.sub(r"\\([{}\[\]])", r"\1", content)
    content = re.sub(r"\n{4,}", "\n\n\n", content)

    with open(dst_path, "w", encoding="utf-8") as f:
        f.write(content)

    return content.count("|------|------|")


def convert_directory(dir_path: Path) -> None:
    """Convert all .adoc files in a directory to .md."""
    adoc_files = sorted(dir_path.glob("*.adoc"))
    if not adoc_files:
        print(f"目录下没有 .adoc 文件: {dir_path}")
        return

    total = len(adoc_files)
    for i, src in enumerate(adoc_files, 1):
        dst = src.with_suffix(".md")
        tables = convert_adoc_to_md(src, dst)
        lines = len(dst.read_text(encoding="utf-8").splitlines())
        print(f"[{i}/{total}] {src.name} -> {dst.name} ({lines} 行, {tables} 表格)")


def main():
    if len(sys.argv) < 2:
        print("用法: python adoc_to_md.py <src.adoc> [dst.md]")
        print("      python adoc_to_md.py --dir <dir_path>")
        sys.exit(1)

    if sys.argv[1] == "--dir":
        if len(sys.argv) < 3:
            print("错误: --dir 需要指定目录路径")
            sys.exit(1)
        dir_path = Path(sys.argv[2])
        if not dir_path.is_dir():
            print(f"错误: 目录不存在 -- {dir_path}")
            sys.exit(1)
        convert_directory(dir_path)
    else:
        src = Path(sys.argv[1])
        if not src.exists():
            print(f"错误: 文件不存在 -- {src}")
            sys.exit(1)
        dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".md")
        tables = convert_adoc_to_md(src, dst)
        print(f"{dst} ({len(dst.read_text(encoding='utf-8').splitlines())} 行, {tables} 表格)")


if __name__ == "__main__":
    main()
