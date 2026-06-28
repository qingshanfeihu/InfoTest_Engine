"""kb_footprint — agent 查询 footprint 知识的工具。

agent 在评审或回答产品问题时，通过 CLI 命令名查询已积累的 footprint 知识，
获取已验证的产品事实、决策规则、已知缺陷等。

走 FootprintIndex 单例（懒加载 + dict 索引）。
"""

from __future__ import annotations

import logging
import os
import re
import threading

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# 深展开上限（轨迹缩减）：命中**自带命令的 branch**（如 `sdns pool`）时，一次返回其子树
# 带命令后代的**紧凑文法**（brief：命令行 + 枚举参数取值，省 desc/rules）、而非只列子命令名
# ——省掉 draft 自顶向下逐层走树的来回 LLM 往返（实测 sdns pool 只列名→draft 再单查
# name/service/method… 制造 5.3 轮/fork）。超此字符上限即停展开、剩余后代回退列名，护住病态
# 宽节点（如 `sdns` 41 子）不爆上下文。6000：brief 紧凑后大节点全子树才 ~4.5k（sdns pool 21
# 子命令），6000 可整装、核心子命令不被截、draft 零再查（≈3000token，1M 上下文可忽略）。env 可调。
_KB_EXPAND_MAX_CHARS = int(os.environ.get("IST_KB_EXPAND_MAX_CHARS", "6000"))

# 启用/总开关命令的形态：含 {on|off}/{enable|disable} 选项,或以 on/enable 结尾。
_ENABLE_CMD_RE = re.compile(
    r"\{\s*on\s*\|\s*off\s*\}|\{\s*enable\s*\|\s*disable\s*\}|\bon\b\s*$|\benable\b\s*$",
    re.IGNORECASE,
)


def _ancestor_enable_deps(idx, command: str) -> list[str]:
    """沿命令的**祖先节点链**收集"启用/总开关"命令作为前置依赖（结构化推导）。

    footprint 是按命令前缀组织的树。查 `sdns host persistence` 时，其祖先节点
    `sdns` / `sdns.host` 若挂着启用型命令（`{on|off}` / `{enable|disable}` / 结尾 on|enable），
    即为该命令的**前置依赖**——必须先执行否则不生效。沿整条祖先链遍历，能抓到**多级**总开关
    （如 `sdns` 模块开关 + `sdns.service` 子模块开关两层），比只查根 token 更全。

    依赖完全从**树结构 + 已抽取的 cli_command** 确定性推导，不靠 LLM 抽散文、不写死具体命令。
    返回顺序：从外层模块到内层（即应当的先后启用顺序）。
    """
    # 同时支持点分 feature_id（`sdns.pool.cname`）与空格命令（`sdns pool cname`）两种查询格式：
    # 把"."也当分隔符——否则点分格式整串成单 token、range(1,1) 取不到祖先链 → 前置依赖丢失、
    # 同一节点两种格式返回不一致（draft 混用两格式查会拿到矛盾结果、反复辨析空转）。
    toks = (command or "").lower().replace(".", " ").split()
    while toks and toks[0] in ("no", "show", "clear"):
        toks = toks[1:]
    deps: list[str] = []
    seen: set[str] = set()
    # 祖先 = 命令的所有真前缀 feature_id（前缀长度 1..len-1，不含命令自身）
    for i in range(1, len(toks)):
        fid = ".".join(toks[:i])
        try:
            node = idx.lookup(fid)
        except Exception:  # noqa: BLE001
            continue
        if not node:
            continue
        for cm in (node.get("cli", {}) or {}).get("commands", []):
            c = cm.get("command", "") if isinstance(cm, dict) else str(cm)
            if c and _ENABLE_CMD_RE.search(c) and c not in seen:
                seen.add(c)
                deps.append(c)
    return deps


def _module_enable_hint(idx, command: str) -> str:
    """把祖先链推导出的前置依赖渲染成提示串（空则返回空串）。"""
    deps = _ancestor_enable_deps(idx, command)
    if not deps:
        return ""
    body = deps[0] if len(deps) == 1 else "；".join(deps) + "（按从外层到内层顺序先执行）"
    return (f"⚠ 前置依赖（来自上级模块开关，**必须先执行**，否则配了也不生效、服务不起、"
            f"上机 fail）: {body}\n\n")


def _format_node(data: dict, brief: bool = False) -> str:
    """将 footprint JSON 格式化为人可读摘要。

    brief=True:父节点深展开后代时用——每条命令只附**枚举类参数**(method: rr|wrr|ga|topology)
    的取值范围,省略冗长 desc 与 rules/behaviors/issues,紧凑以容纳全部子命令、不被 cap 截掉核心
    命令(name/service/method)。leaf 直查用 brief=False(默认)给完整语义(含 desc),解 WRR 当 GA。"""
    lines: list[str] = []
    fid = data.get("feature_id", "?")
    level = data.get("level", "?")
    meta = data.get("footprint_meta", {})
    lines.append(f"## {fid} ({level}, verified {meta.get('verified_count', 0)}x)")

    cli = data.get("cli", {}).get("commands", [])
    if cli:
        lines.append(f"\nCLI commands ({len(cli)}):")
        for cmd in cli[:5]:
            lines.append(f"  - {cmd.get('command', '?')}")
            # 渲染参数:枚举参数(method: rr|wrr|ga|topology)的 value_range 是 draft 写对断言的
            # 关键依据(否则只见 <method> 占位符,rr/wrr/ga 信息全同 → 把 WRR 当 GA 测)。
            for p in cmd.get("parameters", []) or []:
                vr = (p.get("value_range") or "").strip()
                ds = (p.get("desc") or "").strip()
                if brief:
                    # 紧凑:只附枚举类(多选 |)取值范围,省 desc——父节点深展开容纳更多子命令
                    if vr and "|" in vr:
                        lines.append(f"      {p.get('name', '?')}: {vr}")
                    continue
                if not (vr or ds):
                    continue
                req = "必选" if p.get("required") else "可选"
                sep = " — " if vr and ds else ""
                lines.append(f"      {p.get('name', '?')} ({req}): {vr}{sep}{ds}")

    if brief:        # 深展开后代:命令+枚举取值即够,省 rules/behaviors/issues(leaf 直查才详给)
        return "\n".join(lines)

    rules = data.get("decision_rules", [])
    if rules:
        lines.append(f"\nDecision rules ({len(rules)}):")
        for r in rules[:5]:
            cond = r.get("condition", "")[:140]
            dec = r.get("decision", "")
            if dec:
                lines.append(f"  - IF {cond} → {dec}")
            else:
                lines.append(f"  - {cond}")

    behaviors = data.get("behaviors", [])
    if behaviors:
        lines.append(f"\nBehaviors ({len(behaviors)}):")
        for b in behaviors[:3]:
            lines.append(f"  - {b.get('content', '')[:140]}")

    issues = data.get("known_issues", [])
    if issues:
        lines.append(f"\nKnown issues ({len(issues)}):")
        for iss in issues[:5]:
            title = iss.get("title", "")
            lines.append(f"  - {iss.get('issue_id', '?')}: {title[:80]}")

    vs = data.get("version_scope", {})
    if vs.get("product_versions"):
        lines.append(f"\nVersions: {', '.join(vs['product_versions'][:5])}")

    return "\n".join(lines)


# 共享 footprint 缓存:并发 draft 反复查**同一命令**(各自孤立 fork、互不知道查过了)→
# 命中即返回。footprint 索引在一次 run 内静态 → 缓存安全;让重复查询即时返回、结果一致。
_FP_CACHE: dict[str, str] = {}
_FP_CACHE_LOCK = threading.Lock()
_FP_CACHE_IDX_ID = None  # 缓存对应的 index 对象 id;index 重载/换(含测试换 index)→ id 变 → 清缓存防 stale


@tool(parse_docstring=True)
def kb_footprint(command: str) -> str:
    """查询 CLI 命令的产品知识（已验证的规则、行为、缺陷）。

    在评审或回答产品问题时使用。读到 CLI 命令文档后调用此工具，
    获取该命令的历史评审积累知识，避免重复检索原始文档。

    支持两种查询模式：
    - 精确查询：如 "slb mode ircookie" → 返回该命令的完整 footprint
    - 前缀查询：如 "slb mode" → 列出该前缀下的所有子命令

    Args:
        command: CLI 命令名（精确或前缀）。

    Returns:
        匹配的 footprint 内容（CLI 语法、决策规则、行为、已知缺陷），
        或 "未找到" 提示。
    """
    from main.ist_core.memory.footprint import get_footprint_index
    idx_id = id(get_footprint_index())
    key = (command or "").strip().lower()
    global _FP_CACHE_IDX_ID
    with _FP_CACHE_LOCK:
        if idx_id != _FP_CACHE_IDX_ID:   # 索引重载/换 index → 清缓存(防 stale + 保测试隔离)
            _FP_CACHE.clear()
            _FP_CACHE_IDX_ID = idx_id
        if key in _FP_CACHE:
            return _FP_CACHE[key]
    result_text = _kb_footprint_compute(command)
    if key:
        with _FP_CACHE_LOCK:
            _FP_CACHE[key] = result_text
    return result_text


def _kb_footprint_compute(command: str) -> str:
    """kb_footprint 的实际计算(被共享缓存包裹;并发 draft 反复查同命令时只算一次)。"""
    try:
        from main.ist_core.memory.footprint import get_footprint_index
        idx = get_footprint_index()
        result = idx.lookup(command)
        enable_hint = _module_enable_hint(idx, command)

        def _has_commands(r: dict | None) -> bool:
            return bool(r and r.get("cli", {}).get("commands"))

        def _collect_descendant_command_nodes(node: dict, seen: set[str]) -> list[dict]:
            """递归收集 node 子树里**所有带命令的后代节点**（深度优先，去重）。
            治：trunk 的直接子节点本身是空 branch、命令在孙节点时，单层展开会漏。"""
            out: list[dict] = []
            for cid in node.get("children", []) or []:
                if cid in seen:
                    continue
                seen.add(cid)
                cnode = idx.lookup(cid)
                if cnode is None:
                    continue
                if _has_commands(cnode):
                    out.append(cnode)
                # 子节点即便自己有命令，也可能还有更深的孙节点，继续下潜
                out.extend(_collect_descendant_command_nodes(cnode, seen))
            return out

        # 命中的节点自己没有命令（branch/trunk 空壳索引节点，或合成前缀结果）：
        if not _has_commands(result):
            # 这是一个**已知的 branch**（lookup 命中了，有 children）→ 递归展开其子树里
            # 带命令的后代节点，给 draft 它真正要的命令（而不是全树模糊的无关节点）。
            if result and result.get("children"):
                child_nodes = _collect_descendant_command_nodes(result, set())
                if child_nodes:
                    parts = [f"## 「{command}」是父节点，展开其子树中 "
                             f"{len(child_nodes)} 个带命令的节点（紧凑文法）："]
                    shown_fids: set[str] = set()
                    total = 0
                    for node in child_nodes:   # brief 紧凑 + 有界:核心子命令优先进 cap、不被截
                        block = "\n" + _format_node(node, brief=True)
                        if total and total + len(block) > _KB_EXPAND_MAX_CHARS:
                            break
                        parts.append(block)
                        shown_fids.add(node.get("feature_id", ""))
                        total += len(block)
                    rest = [n.get("feature_id", "") for n in child_nodes
                            if n.get("feature_id", "") not in shown_fids]
                    if rest:
                        parts.append("\n\n（其余子命令未展开，需要时再 kb_footprint 查："
                                     + ", ".join(rest) + "）")
                    return enable_hint + "\n".join(parts)
                # branch 存在但整棵子树都没有命令 → 如实说明，不要用 branch 的 token
                # 去全树模糊匹配（那会返回仅共享一个词的无关节点，误导 draft）。
                return (f"## {result.get('feature_id', command)} "
                        f"是父节点，但其子树未记录任何 CLI 命令。")

            # result is None：查询不对应任何节点/前缀（多为自然措辞，如
            # "sdns host method rr"）→ 全树模糊兜底，只收带命令的叶子。
            hits = idx.search(command, top_k=3)
            leaf_hits = []
            for fid, _ in hits:
                node = idx.lookup(fid)
                if _has_commands(node):
                    leaf_hits.append(node)
                elif node and node.get("children"):
                    # trunk 命中（命令空但有子节点，如 sdns.dc 之于「sdns datacenter」）→ 展开其
                    # 带命令的后代（sdns.dc.name/status…），否则 trunk 被剔、只剩无关的有命令节点。
                    leaf_hits.extend(_collect_descendant_command_nodes(node, set()))
            if leaf_hits:
                parts = [f"## 「{command}」精确未命中，模糊匹配到 "
                         f"{len(leaf_hits)} 个相关命令节点："]
                for node in leaf_hits:
                    parts.append("\n" + _format_node(node))
                return enable_hint + "\n".join(parts)
            return (enable_hint + f"未找到 '{command}' 的 footprint 知识。") if enable_hint \
                else f"未找到 '{command}' 的 footprint 知识。"

        # 命中的节点自己有命令：先出它自身文法；若同时是 branch（带子节点），**深展开**
        # 子树带命令后代的完整文法（不再只列子命令名）——治 draft 拿到 `sdns pool` 只得
        # 子命令名、被迫逐个再单查 name/service/method 的自顶向下走树（5.3 轮的制造机）。
        # 按 _KB_EXPAND_MAX_CHARS 有界：累加超限即停，剩余后代回退列名提示再查。
        out = _format_node(result)
        if result.get("children"):
            child_nodes = _collect_descendant_command_nodes(result, set())
            if child_nodes:
                shown: list[str] = []
                shown_fids: set[str] = set()
                total = 0
                for node in child_nodes:
                    block = "\n" + _format_node(node, brief=True)   # 紧凑:命令+枚举取值,免 desc 撑爆 cap
                    if total and total + len(block) > _KB_EXPAND_MAX_CHARS:
                        break   # 超上限即停（首个总展开，防全被截没）
                    shown.append(block)
                    shown_fids.add(node.get("feature_id", ""))
                    total += len(block)
                out += (f"\n\n子命令文法（展开 {len(shown)} 个带命令后代——"
                        f"**这些已为你查好，别再逐个 kb_footprint 单查**）：")
                out += "".join(shown)
                rest = [n.get("feature_id", "") for n in child_nodes
                        if n.get("feature_id", "") not in shown_fids]
                if rest:
                    out += ("\n\n（其余子命令未展开，需要时再 kb_footprint 查："
                            + ", ".join(rest) + "）")
        return enable_hint + out
    except Exception as exc:
        logger.warning("kb_footprint error: %s", exc)
        return f"查询失败: {exc}"
