"""C3 dream 验证 —— 对照 /goal 三条验收标准。

1. 树架构正确，上下级关系正确
2. leaf/trunk/branch 内容准确，CLI 命令和参数生成正确
3. 无孤儿节点，no/show/clear 处理正确
"""
import json
import sys
from pathlib import Path

ROOT = Path("knowledge/footprints/nodes")


def load_nodes():
    nodes = {}
    for f in sorted(ROOT.glob("*.json")):
        d = json.loads(f.read_text())
        nodes[d["feature_id"]] = d
    return nodes


def parent_id(fid):
    return fid.rsplit(".", 1)[0] if "." in fid else None


def check_architecture(nodes):
    print("=" * 80)
    print("① 树架构 + 上下级关系")
    print("=" * 80)
    problems = []
    
    for fid in nodes:
        p = parent_id(fid)
        if p is not None and p not in nodes:
            problems.append(f"  ✗ {fid} 的父节点 {p} 缺失(空心树)")
    
    for fid, d in nodes.items():
        actual_children = sorted(k for k in nodes if parent_id(k) == fid)
        stored = sorted(d.get("children", []))
        if actual_children != stored:
            problems.append(f"  ✗ {fid} children 不一致: 存={stored} 实={actual_children}")
    
    def height(fid, cache={}):
        if fid in cache:
            return cache[fid]
        kids = [k for k in nodes if parent_id(k) == fid]
        h = 0 if not kids else max(height(k) for k in kids) + 1
        cache[fid] = h
        return h
    for fid, d in nodes.items():
        h = height(fid)
        exp = "leaf" if h == 0 else "trunk" if h == 1 else "branch"
        if d.get("level") != exp:
            problems.append(f"  ✗ {fid} level={d.get('level')} 但 height={h} 应为 {exp}")
    if problems:
        print("\n".join(problems))
    else:
        print("  ✓ 所有父节点存在(无空心)、children 一致、level 符合树高")
    return len(problems)


def check_content(nodes):
    print("\n" + "=" * 80)
    print("② leaf/trunk/branch 内容 + CLI 命令/参数准确性")
    print("=" * 80)
    problems = []
    BAD = ("用于", "语法为", "：", "。", "，", "“", "”")
    for fid, d in nodes.items():
        for c in d.get("cli", {}).get("commands", []):
            syn = c.get("command", "")
            
            if any(b in syn for b in BAD):
                problems.append(f"  ✗ {fid} cli_syntax 含噪声: {syn!r}")
            
            for p in c.get("parameters", []):
                if not p.get("name"):
                    problems.append(f"  ✗ {fid} 参数缺 name: {p}")
    
    by_level = {}
    for fid, d in nodes.items():
        by_level.setdefault(d["level"], []).append(fid)
    print(f"\n  节点分布: {{ {', '.join(f'{k}:{len(v)}' for k,v in sorted(by_level.items()))} }}")
    ncli = sum(len(d.get("cli", {}).get("commands", [])) for d in nodes.values())
    nparam = sum(len(c.get("parameters", []))
                 for d in nodes.values() for c in d.get("cli", {}).get("commands", []))
    print(f"  CLI 命令 {ncli} 条，参数 {nparam} 个")
    if problems:
        print("\n".join(problems))
    else:
        print("  ✓ CLI 命令无噪声、参数 name 齐全")
    return len(problems)


def check_orphans_and_ops(nodes):
    print("\n" + "=" * 80)
    print("③ 孤儿节点 + no/show/clear 处理")
    print("=" * 80)
    problems = []
    
    for fid, d in nodes.items():
        ncli = len(d.get("cli", {}).get("commands", []))
        nrule = len(d.get("decision_rules", []))
        nbeh = len(d.get("behaviors", []))
        nbug = len(d.get("known_issues", []))
        nchild = len(d.get("children", []))
        if ncli + nrule + nbeh + nbug == 0 and nchild == 0:
            problems.append(f"  ✗ 孤儿节点(空内容无子节点): {fid}")
    
    for fid in nodes:
        toks = fid.split(".")
        if toks[0] in ("no", "show", "clear"):
            problems.append(f"  ✗ feature_id 含未剥离的操作前缀: {fid}")
    
    ops_in_syntax = 0
    for d in nodes.values():
        for c in d.get("cli", {}).get("commands", []):
            if c.get("command", "").split()[:1] and c["command"].split()[0] in ("no", "show", "clear"):
                ops_in_syntax += 1
    print(f"\n  cli_syntax 中保留的 no/show/clear 完整命令: {ops_in_syntax} 条")
    if problems:
        print("\n".join(problems))
    else:
        print("  ✓ 无孤儿节点、feature_id 无操作前缀残留、操作命令完整保留在 cli_syntax")
    return len(problems)


def main():
    if not ROOT.exists():
        print(f"✗ {ROOT} 不存在")
        sys.exit(1)
    nodes = load_nodes()
    print(f"加载 {len(nodes)} 个节点\n")
    n = check_architecture(nodes)
    n += check_content(nodes)
    n += check_orphans_and_ops(nodes)
    print("\n" + "=" * 80)
    print(f"{'✓ 三项验收全部通过' if n == 0 else f'✗ 共 {n} 个问题'}")
    print("=" * 80)
    sys.exit(1 if n else 0)


if __name__ == "__main__":
    main()
