"""Test Case Review — Sanity Check Script

DEPRECATED(2026-07-17 team4 审计确认):qa_sanity_check 工具已废弃——verifier subagent
自发 grep 探索字面问题,不再依赖本机械扫描(见 tools/skills/__init__.py 顶部 NOTE)。
本文件保留仅作脚本模式参考(grade_extract_script.py docstring 引用),勿再接入新链路。

仿 anthropics/skills xlsx/scripts/recalc.py 模式：
- 顶层入口极简，无 argparse，sys.argv 直接用
- stdout 输出 json.dumps(result, indent=2) 单一 JSON
- 结果 dict 含 status / total_issues / checks，每类位置截断 20 条

机械扫描 6 类问题（attention 在做产品架构推理时会自动忽略的细节）：
  block_mode_mismatch     — 块标题 vs 内容字面错位（如块名 enc_name 但描述写 enc_ip）
  outlier_identifiers     — 离群标识符（如全文 vs11 出现 274 次，单独一行写 vs12）
  field_emptiness         — 字段空值率（Result/Automated/ID 等）
  duplicate_descriptions  — 重复描述 + 中文叠字 + 未闭合双引号
  type_marking_consistency — Test Types 标记一致性（同类用例标 Configuration vs Boundary）
  numerical_regularity    — 数值规律性（持续时间 / Priority 分布）

用法：
    python sanity_check.py <markdown_file>

输出：
    JSON 到 stdout，exit 0 正常 / exit 1 参数错误
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path


_MAX_LOCATIONS = 20


def _read_table_rows(content):
    """提取 List Template 章节的所有表格行。

    返回 list[dict]，每个 dict 是 {column_name: cell_value, _line: 行号, _block: 当前块标题}。
    """
    lines = content.split("\n")
    in_list_template = False
    header = None
    rows = []
    current_block = ""
    block_cols = ()

    for i, line in enumerate(lines, 1):
        if line.startswith("## List Template"):
            in_list_template = True
            continue
        if in_list_template and line.startswith("## "):
            break
        if not in_list_template or not line.startswith("|"):
            continue
        if line.startswith("| ---"):
            continue

        cells = [c.strip() for c in line.split("|")[1:-1]]
        if header is None:
            if cells and cells[0].lower() == "item":
                header = cells
                
                idx_item = header.index("Item") if "Item" in header else 0
                idx_sub = header.index("Sub Item") if "Sub Item" in header else 1
                block_cols = (idx_item, idx_sub)
            continue

        if len(cells) != len(header):
            continue

        
        item_v = cells[block_cols[0]] if block_cols[0] < len(cells) else ""
        sub_v = cells[block_cols[1]] if block_cols[1] < len(cells) else ""
        if item_v:
            current_block = item_v
            current_sub = sub_v
        elif sub_v:
            current_sub = sub_v

        row = {h: c for h, c in zip(header, cells)}
        row["_line"] = i
        row["_block"] = current_block
        row["_sub"] = locals().get("current_sub", "")
        rows.append(row)

    return rows, header


def check_block_mode_mismatch(rows):
    """6.5.1 块名 vs 内容字面对照

    检测 mode 错位的算法：滑动窗口扫"连续相邻行 mode 突变"——
    当一行的 mode X 跟它前后各 1-2 行（必须同 Sub Item 块）的 mode Y 都不一样，
    认为是错位。这是真实复制粘贴 bug 的特征：行 76 enc_name → 行 77 enc_ip → 行 78 enc_name。

    HA 章节用例（每行不同 mode）不会触发，因为相邻行的 mode 本来就互不相同，
    没有"上下都是 X 突然冒出 Y"的模式。
    """
    mode_tokens = ["enc_name", "enc_ip", "plainname", "hexname"]

    def get_mode(row):
        desc = row.get("Description", "") or ""
        for tok in mode_tokens:
            if re.search(rf"mode\s*为\s*{re.escape(tok)}", desc):
                return tok
        return None

    issues = []
    for i, row in enumerate(rows):
        my_mode = get_mode(row)
        if not my_mode:
            continue
        
        my_sub = row.get("_sub", "")
        neighbors = []
        for offset in [-2, -1, 1, 2]:
            j = i + offset
            if 0 <= j < len(rows):
                if rows[j].get("_sub", "") == my_sub:
                    nm = get_mode(rows[j])
                    if nm:
                        neighbors.append(nm)
        if len(neighbors) < 2:
            continue
        
        neighbor_set = set(neighbors)
        if len(neighbor_set) == 1 and my_mode not in neighbor_set:
            consistent = neighbors[0]
            issues.append({
                "line": row["_line"],
                "neighbor_mode": consistent,
                "this_line_mode": my_mode,
                "desc_preview": (row.get("Description") or "")[:120],
            })
            if len(issues) >= _MAX_LOCATIONS:
                return issues
    return issues


def check_outlier_identifiers(content):
    """6.5.2 离群标识符 — 全文标识符频次统计，找出现 1-3 次的可疑项。

    中文 markdown 里 'vs11' 周围没有 ASCII 词边界（汉字不算），所以不能用 \\b。
    用前后字符断言：前面不是字母数字、后面是数字结束（更宽松的边界）。
    """
    issues = {}
    for label, pattern in [
        
        ("vs", r"(?<![a-zA-Z0-9])vs\d+(?![a-zA-Z0-9])"),
        ("g", r"(?<![a-zA-Z0-9])g\d+(?![a-zA-Z0-9])"),
    ]:
        names = Counter(re.findall(pattern, content))
        if not names:
            continue
        most = names.most_common()
        if len(most) < 2:
            continue
        top = most[0]
        
        
        threshold = max(3, top[1] // 20)
        outliers = [(name, cnt) for name, cnt in most if cnt <= threshold and cnt < top[1] // 5]
        if outliers and top[1] >= 20:
            issues[label] = {
                "top_identifier": f"{top[0]} ({top[1]}x)",
                "outliers": [{"name": n, "count": c} for n, c in outliers[:_MAX_LOCATIONS]],
            }
    return issues


def check_field_emptiness(rows, header):
    """6.5.3 字段空值率"""
    if not rows or not header:
        return {}
    total = len(rows)
    empty_counts = {}
    for h in header:
        if h.startswith("_"):
            continue
        empty = sum(1 for r in rows if not r.get(h, "").strip())
        if empty > 0:
            empty_counts[h] = {
                "empty": empty,
                "total": total,
                "rate": round(empty / total * 100, 1),
            }
    
    severe = {k: v for k, v in empty_counts.items() if v["rate"] >= 50}
    return {"total_rows": total, "severely_empty_fields": severe}


def check_duplicates_and_typos(content, rows):
    """6.5.4 重复描述 + 中文叠字 + 未闭合双引号"""
    issues = {}

    
    zh_dup = Counter(re.findall(r"([一-鿿])\1", content))
    if zh_dup:
        issues["chinese_duplicates"] = {
            "top_duplicates": [
                {"char": c, "count": n} for c, n in zh_dup.most_common(10)
            ],
            "lines_with_为为": [
                i for i, l in enumerate(content.split("\n"), 1) if "为为" in l
            ][:_MAX_LOCATIONS],
        }

    
    unclosed = []
    for i, line in enumerate(content.split("\n"), 1):
        if line.strip().startswith("|") and line.count('"') % 2 == 1:
            unclosed.append({"line": i, "preview": line[:100]})
    if unclosed:
        issues["unclosed_quotes"] = {
            "count": len(unclosed),
            "locations": unclosed[:_MAX_LOCATIONS],
        }

    
    descs = Counter()
    desc_lines = {}
    for r in rows:
        d = r.get("Description", "").strip()
        if len(d) > 20:
            descs[d] += 1
            desc_lines.setdefault(d, []).append(r["_line"])
    duplicates = []
    for d, n in descs.most_common():
        if n >= 2:
            duplicates.append({
                "count": n,
                "lines": desc_lines[d][:_MAX_LOCATIONS],
                "preview": d[:80],
            })
    if duplicates:
        issues["duplicate_descriptions"] = {
            "count": len(duplicates),
            "items": duplicates[:_MAX_LOCATIONS],
        }

    return issues


def check_type_marking_consistency(rows):
    """6.5.5 Test Types 标记一致性

    扫所有用例的 (Description 关键词, Test Types) 组合，找同样关键词标不同 Type 的情况。
    例：`xxx ?` help 提示用例：49-53 行标 Configuration，92-96 行标 Boundary。
    """
    issues = []
    
    help_pattern = re.compile(r"^[\w\s]+\?$")
    help_groups = {}
    for r in rows:
        d = r.get("Description", "").strip()
        t = r.get("Test Types", "").strip()
        if help_pattern.match(d):
            help_groups.setdefault(t, []).append({"line": r["_line"], "desc": d})

    if len(help_groups) > 1:
        
        issues.append({
            "category": "CLI help tests",
            "types_used": {t: len(rows_) for t, rows_ in help_groups.items()},
            "by_type": {t: rs[:_MAX_LOCATIONS // 2] for t, rs in help_groups.items()},
        })
    return issues


def check_numerical_regularity(content, rows):
    """6.5.6 数值规律性 + Priority 分布"""
    issues = {}

    
    durations = re.findall(r"持续\s*(\d+)\s*[hH]", content)
    if durations:
        durs = [int(d) for d in durations]
        unique = sorted(set(durs))
        
        is_regular = len(unique) <= 1 or (
            max(unique) - min(unique) == len(unique) - 1
        )
        issues["stress_duration"] = {
            "values": durs,
            "unique_sorted": unique,
            "is_regular": is_regular,
        }

    
    priorities = Counter()
    for r in rows:
        p = r.get("Priority", "").strip()
        if p in {"High", "Medium", "Low"}:
            priorities[p] += 1
    if priorities:
        total = sum(priorities.values())
        issues["priority_distribution"] = {
            "high": priorities["High"],
            "medium": priorities["Medium"],
            "low": priorities["Low"],
            "total": total,
            "high_pct": round(priorities["High"] / total * 100, 1) if total else 0,
        }

    return issues


def check_priority_severity_alignment(rows, bug_severity):
    """6.5.7 Priority 分布 vs BUG 严重度匹配（Phase 5 P5-1）.

    BUG ``Sev=low`` 但 High 占比 > 60%（过度测试 / BUG 严重度被低估），或
    BUG ``Sev=high`` 但 Low 占比 > 50%（覆盖不足）—— 都标 P1。

    bug_severity 由 qa_sanity_check tool 从 kb_bug_search 的 metadata.severity
    传入；缺省时跳过本检查。
    """
    if not bug_severity:
        return {}

    bug_sev = (bug_severity or "").strip().lower()
    priorities = Counter()
    for r in rows:
        p = r.get("Priority", "").strip()
        if p in {"High", "Medium", "Low"}:
            priorities[p] += 1
    total = sum(priorities.values())
    if total == 0:
        return {}

    high_pct = priorities["High"] / total * 100
    low_pct = priorities["Low"] / total * 100

    issue = None
    if bug_sev in {"low", "minor", "trivial"} and high_pct > 60:
        issue = {
            "category": "over_testing",
            "bug_severity": bug_severity,
            "high_count": priorities["High"],
            "total": total,
            "high_pct": round(high_pct, 1),
            "explanation": f"BUG severity={bug_severity} 但 High 优先级用例占 {high_pct:.0f}%（>60%），可能过度测试或 BUG 严重度被低估",
        }
    elif bug_sev in {"high", "critical", "major"} and low_pct > 50:
        issue = {
            "category": "under_testing",
            "bug_severity": bug_severity,
            "low_count": priorities["Low"],
            "total": total,
            "low_pct": round(low_pct, 1),
            "explanation": f"BUG severity={bug_severity} 但 Low 优先级用例占 {low_pct:.0f}%（>50%），覆盖严重度不足",
        }
    return {"misalignment": issue} if issue else {}


def check_cli_help_ratio(rows):
    """6.5.8 CLI help 测试占比（Phase 5 P5-1）.

    Description 末尾匹配 ``<cmd> ?`` 模式的"help 提示自检"占总用例 > 30% 时
    标 P1—— 这类用例机械、信息量低，占比过高说明测试投入产出比失衡。
    """
    help_pattern = re.compile(r"^[\w\s]+\?$")
    help_count = 0
    help_lines = []
    for r in rows:
        d = (r.get("Description") or "").strip()
        if help_pattern.match(d):
            help_count += 1
            help_lines.append({"line": r["_line"], "desc": d[:60]})
    total = len(rows)
    if total == 0:
        return {}
    pct = help_count / total * 100
    if pct > 30:
        return {
            "help_count": help_count,
            "total": total,
            "help_pct": round(pct, 1),
            "sample_locations": help_lines[:_MAX_LOCATIONS],
            "explanation": f"CLI help 提示用例占 {pct:.0f}%（>30%），测试投入产出比失衡——这类用例机械、信息量低",
        }
    return {}


def check_section_redundancy(rows):
    """6.5.9 章节同质性（Phase 5 P5-1）.

    用 difflib 按 ``_sub``（Sub Item 列）分组比较两块的 Description 序列；
    相似度 > 0.9 时标记冗余（如 segment webui 跟 webui 章节字字相同）。

    用 _sub 而非 _block：因为 segment webui / WebUI 都属于 Item="WebUI" 的同一
    个 _block，但是不同的 _sub。
    """
    import difflib

    
    groups: dict[str, list[str]] = {}
    sub_lines: dict[str, list[int]] = {}
    for r in rows:
        sub = r.get("_sub", "") or "(unspecified)"
        desc = (r.get("Description") or "").strip()
        if not desc:
            continue
        groups.setdefault(sub, []).append(desc)
        sub_lines.setdefault(sub, []).append(r["_line"])

    sub_names = [s for s in groups if len(groups[s]) >= 5]
    redundant_pairs = []
    for i in range(len(sub_names)):
        for j in range(i + 1, len(sub_names)):
            a, b = sub_names[i], sub_names[j]
            seq_a, seq_b = groups[a], groups[b]
            ratio = difflib.SequenceMatcher(None, seq_a, seq_b).ratio()
            if ratio > 0.9:
                redundant_pairs.append({
                    "sub_a": a,
                    "sub_a_lines": [sub_lines[a][0], sub_lines[a][-1]],
                    "sub_a_count": len(seq_a),
                    "sub_b": b,
                    "sub_b_lines": [sub_lines[b][0], sub_lines[b][-1]],
                    "sub_b_count": len(seq_b),
                    "similarity": round(ratio, 3),
                    "explanation": f"子块 '{a}' 与 '{b}' Description 相似度 {ratio:.0%}，疑似冗余复制",
                })
    return {"redundant_pairs": redundant_pairs[:_MAX_LOCATIONS]} if redundant_pairs else {}


def sanity_check(filename, bug_severity=None):
    if not Path(filename).exists():
        return {"status": "error", "error": f"File not found: {filename}"}

    try:
        content = Path(filename).read_text(encoding="utf-8")
    except Exception as e:
        return {"status": "error", "error": str(e)}

    rows, header = _read_table_rows(content)
    if not rows:
        return {
            "status": "error",
            "error": "No List Template table found (need '## List Template' section + table header)",
        }

    checks = {
        "block_mode_mismatch": check_block_mode_mismatch(rows),
        "outlier_identifiers": check_outlier_identifiers(content),
        "field_emptiness": check_field_emptiness(rows, header),
        "duplicates_and_typos": check_duplicates_and_typos(content, rows),
        "type_marking_consistency": check_type_marking_consistency(rows),
        "numerical_regularity": check_numerical_regularity(content, rows),
        "priority_severity_alignment": check_priority_severity_alignment(rows, bug_severity),
        "cli_help_ratio": check_cli_help_ratio(rows),
        "section_redundancy": check_section_redundancy(rows),
    }

    
    total_issues = (
        len(checks["block_mode_mismatch"])
        + sum(len(v.get("outliers", [])) for v in checks["outlier_identifiers"].values())
        + len(checks["field_emptiness"].get("severely_empty_fields", {}))
        + len(checks["duplicates_and_typos"].get("duplicate_descriptions", {}).get("items", []))
        + (1 if checks["duplicates_and_typos"].get("chinese_duplicates") else 0)
        + (1 if checks["duplicates_and_typos"].get("unclosed_quotes") else 0)
        + len(checks["type_marking_consistency"])
        + (0 if checks["numerical_regularity"].get("stress_duration", {}).get("is_regular", True) else 1)
        + (1 if checks["priority_severity_alignment"].get("misalignment") else 0)
        + (1 if checks["cli_help_ratio"] else 0)
        + len(checks["section_redundancy"].get("redundant_pairs", []))
    )

    return {
        "status": "success" if total_issues == 0 else "issues_found",
        "total_issues": total_issues,
        "total_rows": len(rows),
        "checks": checks,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python sanity_check.py <markdown_file> [bug_severity]")
        print("\nMechanical sanity check for test case markdown files.")
        print("\nReturns JSON with 9 checks:")
        print("  - block_mode_mismatch:        block name vs Description literal mismatch")
        print("  - outlier_identifiers:        typos in vs/group identifiers")
        print("  - field_emptiness:            fields with > 50% empty rate")
        print("  - duplicates_and_typos:       duplicate descriptions + Chinese叠字 + unclosed quotes")
        print("  - type_marking_consistency:   Test Types marking conflicts")
        print("  - numerical_regularity:       stress duration + Priority distribution")
        print("  - priority_severity_alignment: Priority distribution vs BUG severity (P5-1)")
        print("  - cli_help_ratio:             CLI help test ratio > 30% (P5-1)")
        print("  - section_redundancy:         section description similarity > 90% (P5-1)")
        sys.exit(1)

    filename = sys.argv[1]
    bug_severity = sys.argv[2] if len(sys.argv) > 2 else None
    result = sanity_check(filename, bug_severity=bug_severity)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
