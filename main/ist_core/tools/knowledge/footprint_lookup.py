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
    body = deps[0] if len(deps) == 1 else "; ".join(deps) + " (run in outer→inner module order)"
    return (f"⚠ Prerequisites (enable switches from ancestor modules, **must run first** — "
            f"otherwise the config below takes no effect, the service never comes up, and the "
            f"case fails on device): {body}\n\n")


def _issue_label(issue: dict) -> str:
    """known_issue 短标签——兼容两 schema:老 `{issue_id,title}` / 新观察式 `{fact_key,content}`
    (#61:观察式 known_issue 用 fact_key/content,渲染器原只读 issue_id/title → 内容不可见,
    worker 看不到陷阱)。优先 title/issue_id/fact_key,退 content 前缀。"""
    if not isinstance(issue, dict):
        return str(issue)[:60]
    label = issue.get("title") or issue.get("issue_id") or issue.get("fact_key")
    if label:
        return str(label)
    return str(issue.get("content") or issue.get("condition") or "?")[:60]


def _format_node(data: dict, brief: bool = False) -> str:
    """将 footprint JSON 格式化为人可读摘要。

    brief=True:父节点深展开后代时用——每条命令只附**枚举类参数**(method: rr|wrr|ga|topology)
    的取值范围,省略冗长 desc 与详细 rules/behaviors,紧凑以容纳全部子命令、不被 cap 截掉核心
    命令(name/service/method)。**但浮现 known_issues 标题**(#61:父查漏子叶陷阱=知识可达但
    worker 自然查路径不可见;高频陷阱须在父查也可见)。leaf 直查用 brief=False(默认)给完整语义。"""
    lines: list[str] = []
    fid = data.get("feature_id", "?")
    level = data.get("level", "?")
    meta = data.get("footprint_meta", {})
    lines.append(f"## {fid} ({level}, verified {meta.get('verified_count', 0)}x)")

    cli = data.get("cli", {}).get("commands", [])
    if cli:
        lines.append(f"\nCLI commands ({len(cli)}):")
        for cmd in cli[:5]:
            # gap② S2(Design 裁决⑵):设备实发原文条目必须与手册签名可分辨——不标注的话
            # worker 把「跑通过的一个实例」读成语法(含实参、甚至框架 kwarg),重蹈 #61
            # 「知识存了读不回」。标注走 LLM-facing 英文(本行进 worker 上下文)。
            _sp = (cmd.get("syntax_provenance") or "").strip()
            _tag = "  [device-run verbatim, not manual syntax]" if _sp == "device_run_verbatim" else ""
            lines.append(f"  - {cmd.get('command', '?')}{_tag}")
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
                req = "required" if p.get("required") else "optional"
                sep = " — " if vr and ds else ""
                lines.append(f"      {p.get('name', '?')} ({req}): {vr}{sep}{ds}")

    # #61 surfacing:brief(父节点深展开)也**浮现子节点 known_issues 标签**——否则父查(如
    # `ssl activate`)拿到 compact grammar 却漏了叶节点的陷阱警告,worker 看不到→重犯(知识可达但
    # 在 worker 自然查的路径上不可见)。只附标签 + 指针,详情引导直查叶节点。
    issues = data.get("known_issues", [])
    if brief and issues:
        titles = "; ".join(_issue_label(i) for i in issues[:3])
        more = f" (+{len(issues) - 3} more)" if len(issues) > 3 else ""
        lines.append(f"  ⚠ {len(issues)} known issue(s): {titles}{more} "
                     f"— query `{fid}` for repro/detail")

    if brief:        # 深展开后代:命令+枚举取值+issue 标签即够,详细 rules/behaviors 留 leaf 直查
        return "\n".join(lines)

    # 判例化渲染(2026-07-08):观察级字段(validity/observed_under)+ 两级提示——
    # ①conflicts_with 人工强化(冲突横幅,A/B 实证能打开实验设计空间);
    # ②观察组自动组头(同节点 ≥2 个互异语境的观察=行为可能条件相关;纯计数触发,
    #   不做机械矛盾判定——矛盾由读者 LLM 识别,与"冲突显式化 +24pp"同机制)。
    rules = data.get("decision_rules", [])
    behaviors = data.get("behaviors", [])

    def _fmt_obs(e: dict) -> str:
        v = e.get("validity", "")
        ou = e.get("observed_under", "")
        tag = "|".join(x for x in (v, ou and f"context:{ou}") if x)
        body = e.get("decision") or e.get("content") or e.get("condition", "")
        return (f"[{tag}] " if tag else "") + body

    by_key = {r.get("fact_key"): r for r in rules if r.get("fact_key")}
    in_conflict: set[str] = set()
    conflict_pairs: list[tuple[dict, dict]] = []
    for r in rules:
        cw = r.get("conflicts_with")
        if cw and cw in by_key and r.get("fact_key") not in in_conflict:
            conflict_pairs.append((r, by_key[cw]))
            in_conflict.add(r.get("fact_key", ""))
            in_conflict.add(cw)

    # 观察组:rules+behaviors 里带语境、且未进冲突横幅的条目;互异语境 ≥2 才成组
    obs_entries = [e for e in (rules + behaviors)
                   if (e.get("observed_under") or "").strip()
                   and e.get("fact_key") not in in_conflict]
    obs_ctxs = {(e.get("observed_under") or "").strip() for e in obs_entries}
    obs_group = obs_entries if len(obs_ctxs) >= 2 else []
    in_group = {id(e) for e in obs_group}

    if rules:
        lines.append(f"\nDecision rules ({len(rules)}):")
        for a, b in conflict_pairs:
            lines.append("  ⚠ Conditional conflict (the same behavior was observed with opposite "
                         "results under different contexts; the discriminating condition is not "
                         "pinned down — exactly what a targeted device experiment should "
                         "arbitrate. Do not treat either side as an unconditional fact):")
            lines.append(f"     A. {_fmt_obs(a)}")
            lines.append(f"     B. {_fmt_obs(b)}")
        rest = [r for r in rules
                if r.get("fact_key") not in in_conflict and id(r) not in in_group]
        for r in rest[:5]:
            cond = r.get("condition", "")[:140]
            dec = r.get("decision", "")
            suffix = ""
            v, ou = r.get("validity", ""), r.get("observed_under", "")
            if v or ou:
                suffix = "〔" + "|".join(x for x in (v, ou and f"context:{ou}") if x) + "〕"
            if dec:
                lines.append(f"  - IF {cond} → {dec}{suffix}")
            else:
                lines.append(f"  - {cond}{suffix}")

    if obs_group:
        lines.append(f"\nObservations ({len(obs_group)}, multi-context observation group):")
        lines.append("  ⚠ Multiple observations of the same topic under different contexts — the "
                     "behavior is likely condition-dependent; use the entry matching your config "
                     "shape. Where observations contradict, a device experiment can arbitrate. "
                     "Entries tagged uncertain come from non-passing rounds and upgrade once "
                     "PASS-verified:")
        for e in obs_group:      # 观察组免配额:全量渲染(截断会隐藏语境分支)
            lines.append(f"  - {_fmt_obs(e)}")

    rest_behaviors = [b for b in behaviors if id(b) not in in_group]
    if rest_behaviors:
        lines.append(f"\nBehaviors ({len(rest_behaviors)}):")
        for b in rest_behaviors[:3]:
            lines.append(f"  - {_fmt_obs(b)[:200]}")

    if issues:
        lines.append(f"\nKnown issues ({len(issues)}):")
        for iss in issues[:5]:
            # 兼容两 schema(#61,leaf 直查=surfacing 指针的「详情终点」):
            #   老 {issue_id,title} / 新观察式 {fact_key,validity,content}。原实现只读 title/issue_id
            #   → 新式渲成 `?: `(空),worker 跟父查 surfacing 指针直查叶子仍看不到陷阱 repro/detail。
            # id 取 issue_id/fact_key,正文取 title/content 全文(此处是详情终点,截断即让指针落空;
            # validity 标签透出「观察级、未 PASS-verify」的临时性,worker 据此可设备实验仲裁)。
            iid = iss.get("issue_id") or iss.get("fact_key") or "?"
            body = (iss.get("title") or iss.get("content") or "").strip()
            v = (iss.get("validity") or "").strip()
            tag = f"〔{v}〕" if v else ""
            lines.append(f"  - {iid}{tag}: {body}" if body else f"  - {iid}{tag}")

    vs = data.get("version_scope", {})
    if vs.get("product_versions"):
        lines.append(f"\nVersions: {', '.join(vs['product_versions'][:5])}")

    return "\n".join(lines)


# 共享 footprint 缓存:并发 draft 反复查**同一命令**(各自孤立 fork、互不知道查过了)→
# 命中即返回。footprint 索引在一次 run 内静态 → 缓存安全;让重复查询即时返回、结果一致。
_FP_CACHE: dict[str, str] = {}
_FP_CACHE_LOCK = threading.Lock()
_FP_CACHE_IDX_ID = None  # 缓存对应的 index 对象 id;index 重载/换(含测试换 index)→ id 变 → 清缓存防 stale


def _version_to_nodes_subdir(version: str) -> str:
    """version 参数 → nodes 子目录名。空 → 默认 nodes/。"""
    v = (version or "").strip()
    if not v:
        return "nodes"
    return f"nodes_{v}"


@tool(parse_docstring=True)
def kb_footprint(command: str, version: str = "") -> str:
    """Query accumulated product knowledge for a CLI command (verified rules, behaviors,
    known issues).

    Use during review or when answering product questions. After reading a CLI command's
    documentation, call this tool to get the knowledge accumulated from past reviews of that
    command, instead of re-searching the raw documents.

    Two query modes are supported:
    - Exact: e.g. "slb mode ircookie" → returns that command's full footprint
    - Prefix: e.g. "slb mode" → lists all subcommands under that prefix

    Args:
        command: CLI command name (exact or prefix).
        version: Product version (e.g. "10.4.6r2"); empty queries the default tree.

    Returns:
        The matched footprint content (CLI syntax, decision rules, behaviors, known issues),
        or a "not found" notice.
    """
    nodes_subdir = _version_to_nodes_subdir(version)
    from main.ist_core.memory.footprint import get_footprint_index
    idx_id = id(get_footprint_index(nodes_subdir))
    key = (command or "").strip().lower()
    cache_key = (key, nodes_subdir)
    global _FP_CACHE_IDX_ID
    with _FP_CACHE_LOCK:
        if idx_id != _FP_CACHE_IDX_ID:   # 索引重载/换 index → 清缓存(防 stale + 保测试隔离)
            _FP_CACHE.clear()
            _FP_CACHE_IDX_ID = idx_id
        if cache_key in _FP_CACHE:
            return _FP_CACHE[cache_key]
    result_text = _kb_footprint_compute(command, nodes_subdir)
    if key:
        with _FP_CACHE_LOCK:
            _FP_CACHE[cache_key] = result_text
    return result_text


def _kb_footprint_compute(command: str, nodes_subdir: str = "nodes") -> str:
    """kb_footprint 的实际计算(被共享缓存包裹;并发 draft 反复查同命令时只算一次)。"""
    try:
        from main.ist_core.memory.footprint import get_footprint_index
        idx = get_footprint_index(nodes_subdir)
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
                    parts = [f"## '{command}' is a parent node; expanding "
                             f"{len(child_nodes)} command-bearing node(s) in its subtree "
                             f"(compact grammar):"]
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
                        parts.append("\n\n(remaining subcommands not expanded; query "
                                     "kb_footprint for them when needed: "
                                     + ", ".join(rest) + ")")
                    return enable_hint + "\n".join(parts)
                # branch 存在但整棵子树都没有命令 → 如实说明，不要用 branch 的 token
                # 去全树模糊匹配（那会返回仅共享一个词的无关节点，误导 draft）。
                return (f"## {result.get('feature_id', command)} "
                        f"is a parent node, but no CLI commands are recorded anywhere in "
                        f"its subtree.")

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
                parts = [f"## No exact match for '{command}'; fuzzy-matched "
                         f"{len(leaf_hits)} related command node(s):"]
                for node in leaf_hits:
                    parts.append("\n" + _format_node(node))
                return enable_hint + "\n".join(parts)
            return (enable_hint + f"Footprint knowledge not found for '{command}'.") if enable_hint \
                else f"Footprint knowledge not found for '{command}'."

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
                out += (f"\n\nSubcommand grammar (expanded {len(shown)} command-bearing "
                        f"descendant(s) — **already fetched for you, do not kb_footprint "
                        f"them one by one again**):")
                out += "".join(shown)
                rest = [n.get("feature_id", "") for n in child_nodes
                        if n.get("feature_id", "") not in shown_fids]
                if rest:
                    out += ("\n\n(remaining subcommands not expanded; query kb_footprint "
                            "for them when needed: " + ", ".join(rest) + ")")
        return enable_hint + out
    except Exception as exc:
        logger.warning("kb_footprint error: %s", exc)
        return f"error: footprint lookup failed: {exc}"
