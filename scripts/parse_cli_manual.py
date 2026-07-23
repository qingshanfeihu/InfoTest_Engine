#!/usr/bin/env python3
"""
解析 CLI 手册 (Chapter20.md) 为结构化 JSON。

支持三种参数表格格式：
  A) 单行: |param_name| description
  B) 分离: |param_name
           |description
  C) 修饰: |param_name modifier|
           description (无 | 前缀)

用法：
  python scripts/parse_cli_manual.py [--out output.json]
"""

import re
import json
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_FILE = ROOT / "knowledge" / "data" / "markdown" / "product" / "Chapter20.md"


# ═══════════════════════════════════════════════════════════
# 命令检测
# ═══════════════════════════════════════════════════════════

def is_cli_command_line(line: str) -> bool:
    """
    判断一行是否为 CLI 命令语法行。
    排除：** text**（子列表项）、**注意**、纯中文粗体、过长粗体等。
    """
    line_s = line.strip()
    m = re.match(r'^\*\*(.+?)\*\*', line_s)
    if not m:
        return False
    bold = m.group(1)
    if bold.startswith(' '):        # 子列表 ** text...
        return False
    if '注意' in bold:
        return False
    if re.match(r'^[一-鿿]', bold):  # 纯中文
        return False
    if len(bold) > 80:
        return False
    if not re.search(r'[a-z]', bold.lower()):
        return False
    return True


# ═══════════════════════════════════════════════════════════
# 主干 & 参数提取
# ═══════════════════════════════════════════════════════════

def extract_command_trunk(line: str) -> tuple[str, int, list[tuple[str, bool]], str]:
    """返回 (trunk, level, [(name, required)], full_syntax)。"""
    line = line.rstrip()
    bold_m = re.search(r'\*\*(.+?)\*\*', line)
    if not bold_m:
        return "", 0, [], line

    bold_content = bold_m.group(1).strip()
    # 去掉 {on|off} 等选择项
    trunk_cleaned = re.sub(r'\{[^}]+\}', '', bold_content).strip()
    trunk_cleaned = re.sub(r'\s+', ' ', trunk_cleaned).strip()
    level = len(trunk_cleaned.split()) if trunk_cleaned else 0

    after_bold = line[bold_m.end():].strip()
    before_bold = line[:bold_m.start()].strip()
    all_text = f"{before_bold} {after_bold}".strip()
    params = _extract_params(all_text)

    return trunk_cleaned, level, params, line


def _extract_params(text: str) -> list[tuple[str, bool]]:
    params = []
    # italic 包裹: _<name>_ / _[name]_ / _<name|alias>_ / _[name|alias]_
    italic_pat = re.compile(r'_<([^>]+)>_|_\[([^\]]+)\]_')
    for m in italic_pat.finditer(text):
        if m.group(1):
            name = m.group(1).split('|')[0].strip()
        else:
            name = m.group(2).split('|')[0].strip()
        if name and name not in {'on', 'off'}:
            params.append((name, m.group(1) is not None))  # group(1)→required, group(2)→optional

    # 裸 <param>
    no_italic = italic_pat.sub(' ', text)
    for m in re.finditer(r'<([^>]+)>', no_italic):
        name = m.group(1).split('|')[0].strip()
        if name and name not in {'on', 'off'}:
            params.append((name, True))

    # 裸 [param]（排除花括号内容）
    no_angle = re.sub(r'<[^>]+>', ' ', no_italic)
    for m in re.finditer(r'\[([^\[\]{}]+)\]', no_angle):
        name = m.group(1).split('|')[0].strip()
        if name and not re.match(r'^\d+$', name) and name not in {'on', 'off'}:
            params.append((name, False))

    seen = set()
    uniq = []
    for p in params:
        if p[0] not in seen:
            seen.add(p[0])
            uniq.append(p)
    return uniq


# ═══════════════════════════════════════════════════════════
# 描述提取
# ═══════════════════════════════════════════════════════════

def extract_description(lines: list[str], start_idx: int) -> tuple[str, int]:
    """提取"该命令"功能说明。返回 (text, next_idx)。"""
    i = start_idx
    parts = []
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith('该命令') or line.startswith('本命令'):
            parts.append(line)
            i += 1
            while i < len(lines):
                nl = lines[i].strip()
                if not nl:
                    break
                if (nl.startswith('|') or nl.startswith('**注意') or
                    is_cli_command_line(nl) or nl.startswith('例如') or
                    nl.startswith('```') or nl.startswith('该命令') or
                    nl.startswith('系统支持最多') or nl.startswith('默认值为') or
                    nl.startswith('系统允许') or re.match(r'^[\[<]', nl) or
                    re.match(r'^\.', nl)):
                    break
                parts.append(nl)
                i += 1
            break
        elif line.startswith('|') or is_cli_command_line(line) or line.startswith('**注意'):
            break
        else:
            i += 1
    return ' '.join(parts), i


# ═══════════════════════════════════════════════════════════
# 参数表格解析
# ═══════════════════════════════════════════════════════════

def _looks_like_param(text: str) -> bool:
    """判断表格单元格内容是否像参数名（短、无中文、字母开头）。"""
    t = text.strip()
    if not t or len(t) > 60:
        return False
    if re.search(r'[一-鿿]', t):
        return False
    return bool(re.match(r'^[a-zA-Z0-9_]', t))


def _cell_to_name(cell: str) -> str:
    """从表格单元格提取纯参数名。"""
    t = cell.strip()
    # host_name\|forward_zone_name → host_name
    t = t.split('\\')[0].strip()
    # host_name | forward_zone_name → host_name
    t = t.split('|')[0].strip()
    parts = t.split()
    name = parts[0] if parts else t
    # "a" 修饰符
    if name.lower() in {'a', '可选', '可选，'} and len(parts) > 1:
        name = parts[1]
    return name.strip()


def _append_desc(d: dict, name: str, desc: str) -> None:
    if name in d:
        d[name] += '；' + desc
    else:
        d[name] = desc


def parse_parameter_table(lines: list[str], start_idx: int) -> tuple[dict[str, str], int]:
    """
    解析参数表格，兼容 A/B/C 三种格式。
    返回: ({param_name: description}, next_index)
    """
    result = {}
    i = start_idx
    pending_name = None

    MAX_SCAN = 60  # 最多扫描行数，防止跑偏
    scan_count = 0

    while i < len(lines) and scan_count < MAX_SCAN:
        line = lines[i].strip()
        scan_count += 1

        if not line:
            if pending_name:
                result.setdefault(pending_name, "")
                pending_name = None
            i += 1
            continue

        # 非表格行
        if not line.startswith('|'):
            if pending_name:
                # 格式 C: 描述行（无 | 前缀）
                result[pending_name] = line
                pending_name = None
                i += 1
                continue
            if line.startswith('**注意'):
                # 表内嵌注意事项 — 跳过整个 note 块后继续解析表格
                i += 1
                while i < len(lines):
                    nl = lines[i].strip()
                    if not nl or nl.startswith('|') or is_cli_command_line(nl) or re.match(r'^###\s', nl):
                        break
                    i += 1
                continue
            if result and not is_cli_command_line(line):
                if not (line.startswith('该命令') or line.startswith('例如') or
                        line.startswith('```') or re.match(r'^###\s', line) or
                        line.startswith('系统允许配置') or line.startswith('下表列出') or
                        line.startswith('.')):
                    last_key = list(result.keys())[-1]
                    result[last_key] += ' ' + line
                    i += 1
                    continue
            # 尚未找到任何表格行，且不是命令/小节 — 跳过（处理列表项等间隔内容）
            if not result and not pending_name:
                if not is_cli_command_line(line) and not re.match(r'^###\s', line):
                    i += 1
                    continue
            break

        # ── | 开头行 ──
        single_m = re.match(r'^\|([^|]+)\|\s*(.*)$', line)
        if single_m:
            cell = single_m.group(1).strip()
            desc = single_m.group(2).strip()
            name = _cell_to_name(cell)
            if desc:
                _append_desc(result, name, desc)
                pending_name = None
            else:
                pending_name = name
            i += 1
            continue

        # 格式 B: |content（无尾 |）
        cell = line[1:].strip()
        name = _cell_to_name(cell)

        if _looks_like_param(cell):
            if pending_name:
                result.setdefault(pending_name, "")
            pending_name = name
        else:
            if pending_name:
                _append_desc(result, pending_name, cell)
                pending_name = None
            elif result:
                last_key = list(result.keys())[-1]
                result[last_key] += ' ' + cell
        i += 1

    if pending_name:
        result.setdefault(pending_name, "")

    return result, i


# ═══════════════════════════════════════════════════════════
# 注意事项提取
# ═══════════════════════════════════════════════════════════

def extract_notes(lines: list[str], start_idx: int) -> tuple[list[str], int]:
    """
    提取"**注意：**"内容。
    只扫描有限行数，遇到下一命令/小节/代码块即停。
    返回: ([note_texts], next_idx)
    """
    notes = []
    i = start_idx
    in_notes = False
    buf = []

    MAX_LOOKAHEAD = 80  # 最多前瞻行数
    looked = 0

    while i < len(lines) and looked < MAX_LOOKAHEAD:
        line = lines[i].strip()
        looked += 1

        # 搜索注意头
        if not in_notes:
            if re.match(r'^\*\*注意[：:]\s*\*\*', line) or re.match(r'^\*\*注意[：:]\*\*', line):
                in_notes = True
                rest = re.sub(r'^\*\*注意[：:]\s*\*\*\s*', '', line).strip()
                if rest:
                    buf.append(rest)
                i += 1
                continue
            # 还没找到注意头，但遇到以下内容则停止搜索
            if is_cli_command_line(line) or re.match(r'^###\s', line):
                break
            if line.startswith('```') or line.startswith('该命令'):
                break
            i += 1
            continue

        # in_notes=True
        if not line:
            i += 1
            continue
        # 终止
        if is_cli_command_line(line) or re.match(r'^###\s', line):
            break
        if line.startswith('```') or line.startswith('例如：') or line.startswith('例如:'):
            break
        if line.startswith('默认值为'):
            break

        # 过滤 [arabic]
        if re.match(r'^\[arabic\]', line):
            i += 1
            continue
        if re.match(r'^\.\s', line):
            buf.append(re.sub(r'^\.\s*', '', line).strip())
            i += 1
            continue

        buf.append(line)
        i += 1

    if buf:
        notes.append(' '.join(buf))
    return notes, i


# ═══════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════

def _desc_from_main(description: str, param_name: str) -> str:
    """从功能说明正文中提取参数相关描述片段。"""
    esc = re.escape(param_name)
    pats = [
        rf'参数["""“]{esc}["""”]\s*[，,]\s*(.+?)(?:[。；;]|当|如果|默认|取值|该参数)',
        rf'参数["""“]{esc}["""”]\s*(.+?)(?:[。；;]|当|如果)',
        rf'["""“]{esc}["""”]\s*(.+?)(?:[。；;]|当|如果)',
    ]
    for pat in pats:
        m = re.search(pat, description)
        if m:
            return m.group(1).strip() if m.lastindex else m.group(0).strip()
    return ""


def find_next_command(lines: list[str], start_idx: int) -> int:
    for i in range(start_idx, len(lines)):
        line = lines[i].strip()
        if not line:
            continue
        if is_cli_command_line(line):
            return i
        if re.match(r'^###\s', line):
            return i
    return len(lines)


def _resolve_param_desc(pname: str, param_table: dict, description: str) -> str:
    """为给定参数名查找最佳描述。"""
    # 1) 精确匹配（大小写不敏感）
    pname_lower = pname.lower()
    for key, val in param_table.items():
        if key.lower() == pname_lower:
            return val

    # 2) 精确匹配（原有逻辑）
    if pname in param_table:
        return param_table[pname]

    # 3) 模糊匹配
    for key, val in param_table.items():
        key_clean = key.split('\\')[0].split('|')[0].strip().split()[0]
        if key_clean.lower() == pname_lower or pname_lower == key_clean.lower():
            return val
        if pname_lower in key.lower().split():
            return val
        # ipv4_netmask → ipv4_netmask \| ipv4_prefix
        if key.lower().startswith(pname_lower) or pname_lower.startswith(key_clean.lower()):
            return val

    # 3) 从功能说明正文提取
    return _desc_from_main(description, pname)


# ═══════════════════════════════════════════════════════════
# 主解析
# ═══════════════════════════════════════════════════════════

def parse_cli_commands(filepath: str, version: str = "10.5") -> list[dict]:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = content.split('\n')
    total = len(lines)
    results = []

    i = 0
    current_section = ""
    cmd_index = 0

    while i < total:
        line = lines[i].strip()

        if re.match(r'^###\s', line):
            current_section = re.sub(r'^###\s+', '', line).strip()
            i += 1
            continue
        if re.match(r'^##\s', line):
            i += 1
            continue

        if not is_cli_command_line(line):
            i += 1
            continue

        trunk, level, params_raw, full_syntax = extract_command_trunk(line)
        if not trunk or level == 0:
            i += 1
            continue

        cmd_index += 1

        required_params = [p[0] for p in params_raw if p[1]]
        optional_params = [p[0] for p in params_raw if not p[1]]

        # ── 功能说明 ──
        desc_start = i + 1
        description, desc_end = extract_description(lines, desc_start)

        # ── 参数表格 ──
        tbl_start = max(desc_end, desc_start)
        param_table, tbl_end = parse_parameter_table(lines, tbl_start)

        # ── 注意事项 ──
        note_start = max(tbl_end, tbl_start)
        notes, _ = extract_notes(lines, note_start)

        # ── 组装参数说明 ──
        param_desc = {}
        all_params = required_params + optional_params
        for pname in all_params:
            param_desc[pname] = {
                "description": _resolve_param_desc(pname, param_table, description)
            }

        shard_id = f"Chapter20_{cmd_index:04d}"
        filename = Path(filepath).name

        entry = {
            "文件类型": f"cli_{cmd_index:03d}",
            "功能说明": description or "",
            "命令主干": trunk,
            "命令层级": level,
            "必选参数": required_params,
            "可选参数": optional_params,
            "参数说明": param_desc,
            "原始文件名": filename,
            "版本": version,
            "分片ID": shard_id,
            "所属小节": current_section,
        }
        if notes:
            entry["注意事项"] = notes

        results.append(entry)

        next_cmd = find_next_command(lines, i + 1)
        i = next_cmd

    # ── 后处理：no/show/clear 变体共用参数描述 ──
    _backfill_variant_params(results)

    return results


def _backfill_variant_params(results: list[dict]) -> None:
    """
    为参数描述为空的条目回填描述。
    1) no/show/clear 变体 → 从相同词干的主命令复制
    2) 其余空参数 → 从其他拥有该参数且已填充描述的条目复制
    """
    # 建立 主干→条目 索引
    trunk_index: dict[str, dict] = {}
    for r in results:
        trunk = r["命令主干"]
        if trunk not in trunk_index:
            trunk_index[trunk] = r

    # 建立 参数名→描述 全局字典
    global_param_desc: dict[str, str] = {}
    for r in results:
        for pname, pval in r.get("参数说明", {}).items():
            desc = pval.get("description", "") if isinstance(pval, dict) else str(pval)
            if desc and pname.lower() not in global_param_desc:
                global_param_desc[pname.lower()] = desc

    for r in results:
        trunk = r["命令主干"]

        # 1) no/show/clear 变体 → 同词干主命令
        prefix_m = re.match(r'^(no|show|clear)\s+(.+)$', trunk)
        if prefix_m:
            base_trunk = prefix_m.group(2)
            base = trunk_index.get(base_trunk)
            if base:
                for pname, pval in r.get("参数说明", {}).items():
                    if not pval.get("description", ""):
                        base_desc = base.get("参数说明", {}).get(pname, {})
                        bd = base_desc.get("description", "") if isinstance(base_desc, dict) else str(base_desc)
                        if bd:
                            pval["description"] = bd

        # 2) 全局回填（所有仍为空的参数）
        for pname, pval in r.get("参数说明", {}).items():
            if not pval.get("description", ""):
                gd = global_param_desc.get(pname.lower(), "")
                if gd:
                    pval["description"] = gd


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="解析 CLI 手册为结构化 JSON")
    ap.add_argument("--input", default=str(SRC_FILE))
    ap.add_argument("--out", default=None)
    ap.add_argument("--version", default="10.5")
    args = ap.parse_args()

    print(f"解析文件: {args.input}")
    results = parse_cli_commands(args.input, version=args.version)
    print(f"共解析出 {len(results)} 条 CLI 命令")

    if args.out:
        out_path = Path(args.out)
    else:
        out_dir = ROOT / "workspace" / "outputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "Chapter20_cli_parsed.json"

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"已写出: {out_path}")

    levels = {}
    for r in results:
        lv = r["命令层级"]
        levels[lv] = levels.get(lv, 0) + 1
    print(f"命令层级分布: {dict(sorted(levels.items()))}")

    total_params = 0
    empty_params = 0
    for r in results:
        for pn, pd in r.get("参数说明", {}).items():
            total_params += 1
            d = pd.get("description", "") if isinstance(pd, dict) else pd
            if not d:
                empty_params += 1
    pct = 100 * (total_params - empty_params) // max(total_params, 1)
    print(f"参数描述覆盖: {total_params - empty_params}/{total_params} ({pct}%)")
    if empty_params:
        print(f"(仍有 {empty_params} 个参数描述为空)")

    if results:
        print(f"\n--- 前3条预览 ---")
        for r in results[:3]:
            print(f"  主干: {r['命令主干']} (层级{r['命令层级']})")
            for pn, pd in r.get('参数说明', {}).items():
                d = pd.get('description', '') if isinstance(pd, dict) else pd
                print(f"    [{pn}]: {d[:80] if d else '(空)'}" + ("..." if len(d) > 80 else ""))
            if r.get('注意事项'):
                print(f"  注意事项: {len(r['注意事项'])}条")
            print()


if __name__ == "__main__":
    main()
