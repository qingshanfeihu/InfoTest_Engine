"""Grade 子流程 — 确定性脏活脚本（缺陷①：observe-then-assert 恒真假断言探针）。

仿 anthropics/skills 脚本模式（参 test-list-review/scripts/sanity_check.py）：
- 顶层入口极简，sys.argv 直接用，无 argparse；
- stdout 输出单一 JSON（json.dumps ensure_ascii=False），只 print 结论；
- 既可命令行跑（main()），也可被 import（extract()）。

═══ 判据严格对齐论文三层分解模型（不自造启发式）═══
依据：docs/theory_to_implementation_mapping.md §一/§四、docs/linalg_formalization.md §9/§10、
      main/case_compiler/provenance_ir.py（Layer = G/E/V）。
- 三层分解（论文 §3.5-3.7）：每个断言按来源分
    G = 骨架/配置存在（验命令配上了/配置在不在，零自由度，查表/检索可定）
    E = 环境常量（验 IP/设备标识，查拓扑表可定）
    V = 业务语义（验解析结果/命中/计数/动态行为——意图特有，只有它"覆盖目标行为"）
- 覆盖只由 V 段判定（§四 grade 修法 + linalg §10）：
    Cov(T,I) = dim(span(A) ∩ B) / dim(B)，弱断言 = 秩亏方向。
    G/E 段配置存在性检查是**健全性前置、不算覆盖**；只有 V 段断言贡献 Cov。
- 算子代数（§3.2）：配置查询 show（看配置在不在）是 G 性质观测；
    dig/客户端请求/show statistics（看运行时行为/解析/计数）是 V 性质观测。

**恒真假断言的论文本质**（本脚本要确定性探出）：
  一条断言**标称 layer=V**，实际却只是"配了 X → show X → found X"的**配置存在性检查**
  （G 性质：观测是配置查询 show，且 expect 只是 found 一条前序配置命令的回显）——
  它名为 V、实为 G，不验任何业务行为，故无论被测行为成败都恒成立 = 秩亏 = 假覆盖。
  真实反例 588990：被测 `clear sdns session persistence … ALL`（要测 ALL 参数/ session 清除效果），
  断言却是 `found "sdns host persistence 3600 …"`（show 配置、found 自己前面配的那条）——
  draft 误标 layer=V，实为 G 段配置存在性检查；真正的 V 段行为（ALL 是否被拒/session 是否清）
  无任何断言覆盖 → V 段覆盖 = 0 → 弱覆盖。

**红线**：本脚本只产**确定性信号**（layer 名实核对、观测算子类型、expect 是否匹配前序配置命令、
回显是否语法错）。它**不下 PASS/CUT 终判**——终判由 grade LLM 结合需求意图与 source_ref 现场判。

═══ 三层架构（2026-07-08 P2 重构：新坑的响应路径 = 纯数据变化）═══
本模块只保留 **5 个通用原理检测器**（闭合于数学，零领域词面）；领域词面全在文法数据
`knowledge/data/compile_ref/domain_grammar.json`（随产品手册演进，改 JSON 不改代码）；
坑叙事/行为知识在判例层（footprint 观察，文案运行时按引用现取）。

  原理（闭合于什么）              → 本文件的信号
  ① 零信息断言（信息论：断言对任意结果恒成立）
       → count_tautology_suspect（无界 \\d）、is_config_existence_check（found 前序配置）
  ② 秩亏 / 弱覆盖（线代 §10：V 段覆盖维度不足）
       → weak_v_coverage_suspect、distribution_coverage_gap_suspect、layer_mismatch
  ③ 出处缺失（期望值与观测同源、无独立溯源 = observe-then-assert）
       → count_hardcoded_suspect、asserts_literal_hit_ip / hardcoded_hit_ip_suspect
  ④ 引用图（图论：悬空引用 / 派生值集合未被断言锚定）
       → cname_member_not_local_host_suspect、new_member_unanchored_suspect
       （对象文法来自 JSON reference_closures / anchoring_chains——新增同类检查零代码）
  ⑤ 预期冲突（期望=拒绝语义 ∧ 出处=intent，无客观溯源）
       → spec_conflict_suspect

用法：
    python grade_extract.py <case.xlsx> <case.provenance.json | "-">

输出：
    JSON 到 stdout，exit 0 正常 / exit 1 读 xlsx 失败（打印可读错误）。
"""

import json
import re
import sys
from pathlib import Path

from main.case_compiler import domain_grammar as _dg

# observe_kind / object_tokens / 配置存在性检查 + 瞬时态动词表 收敛到单一事实源（与 confidence_f
# 共用，免两套实现/常量漂移给 grade 矛盾信号）。瞬时态动词：操作运行时状态/连接表、不改静态配置——
# 一个 case 含这类命令时意图通常是测其「运行时行为效果」（应有 V 段断言覆盖）。
from main.case_compiler.observe_ops import (
    object_tokens as _object_tokens,
    observe_kind as _observe_kind,
    config_existence_check as _config_existence_check,
    is_observe_command as _is_observe_command,
    MUTATING_VERBS as _MUTATING_VERBS,
)


def _leading_verb(cmd: str) -> str:
    """命令首词（小写）——判它是否瞬时态动词(clear/no/reset/flush)。"""
    toks = (cmd or "").strip().split()
    return toks[0].strip().strip('"\'').lower() if toks else ""


def _expect_is_rejection(expect: str) -> bool:
    """断言期望值是否含"操作被拒绝/参数不支持"语义（原理⑤预期冲突的语义面）。
    词表在文法数据 rejection_semantics（出处/刻意取舍见其 provenance：不复用
    has_cli_error、不含"不存在/not found"）。"""
    low = (expect or "").lower()
    return any(h in low for h in _dg.rejection_hints())


# ── 分布区间断言（分布类算法）确定性识别 ─────────────────────────────────────────
# 分布类负载均衡：发 N 次→各后端累计命中∈统计区间（守恒 Σ==N），是合法 V 覆盖；与确定性映射
# （命中由优先级/探测/哈希定，固定落点合法）区分。算法分类与 method 行形态都是文法数据。
# 命中/计数字段词（断言锚定的统计字段，词面在文法数据 count_field_words）。
_HIT_FIELD_RE = re.compile("(" + "|".join(_dg.count_field_words()) + ")", re.IGNORECASE)
# 有界区间标志：emit 区间正则签名 (?<!\d)…(?!\d)、数字字符类 [d-d]、或数字交替 (?:d…。
_BOUNDED_RANGE_RE = re.compile(r"\(\?<!\\d\)|\[\d-\d\]|\(\?:\d")
# 无界数字标志：\d（任意数字，对计数断言＝恒真）。
_UNBOUNDED_DIGIT_RE = re.compile(r"\\d")
# 字面 IPv4 标志：expect 写死一个成员 IP（点可能转义成 \.）——dig found 它＝断言"这一发必中它"。
# 分布算法(rr/wrr)下命中哪个由运行时轮转起点定，写死单次命中落点＝observe-then-assert（偶对偶错）。
_LITERAL_IPV4_RE = re.compile(r"\d{1,3}(?:\\?\.\d{1,3}){3}")
# 命中归属锚点结构签名：emit member_regex_for_ips 生成的形态 `\b(?:ip1|ip2|...)\b`（哪怕只有
# 1 个 IP 也套非捕获组）。跟 _BOUNDED_RANGE_RE 同样的理由——compile-worker 目前不传
# provenance_json（架构现状，非本模块能改），只靠 source_kind==membership_derived 排除会在
# 主链路里失效；这个"\b(?:…)\b 非捕获组"形状本身就跟手写裸字面量 `\b172\.16\.35\.213\b`
# （没有 (?:...)包裹）不同，可离线识别、不依赖 provenance。
_MEMBER_ANCHOR_SHAPE_RE = re.compile(r"\\b\(\?:.+\)\\b")


def _ip_literal_pattern(ip: str) -> str:
    """构造能同时匹配 IP 原始写法与正则转义写法（`.`→`\\.`）的检测模式，用于在 check_point
    expect 文本里查这个 IP 是否被引用过（不管是常量断言还是 member/dist 展开的转义正则）。"""
    parts = ip.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return r"\\?\.".join(re.escape(p) for p in parts)
    return re.escape(ip)  # IPv6/其他：原样转义（冒号非正则元字符，不会被转义成 \:）


def _closure_case_law_note(closure: dict, names: list[str]) -> str:
    """引用闭合发现的**判例层文案**：运行时从 footprint 节点取观察（数据按引用流，
    坑叙事随观察演化/升级，不写死在代码——P2-3）。取不到时只留一句零领域兜底。"""
    accepted = ("The device silently accepts this form with no error. " if closure.get("silently_accepted")
                else "")   # closure 级事实,来自文法数据字段(带 provenance),不对所有 closure 通用
    head = ("The config references " + ", ".join(names) + " as members, but this case has no matching "
            f"definition command (reference-closure check {closure.get('id', '')}). {accepted}"
            "Behavior varies with intent and config form. ")
    node_id = (closure.get("footprint_node") or "").strip()
    obs_lines: list[str] = []
    if node_id:
        try:
            from main.knowledge_paths import KNOWLEDGE_FOOTPRINTS_NODES
            node = json.loads((Path(KNOWLEDGE_FOOTPRINTS_NODES) / f"{node_id}.json")
                              .read_text(encoding="utf-8"))
            for e in (node.get("decision_rules", []) + node.get("behaviors", [])):
                ou = (e.get("observed_under") or "").strip()
                body = (e.get("decision") or e.get("content") or e.get("condition") or "").strip()
                if not body:
                    continue
                tag = "|".join(x for x in ((e.get("validity") or ""), ou and f"ctx: {ou}") if x)
                obs_lines.append(f"[{tag}] {body}" if tag else body)
        except Exception:  # noqa: BLE001
            obs_lines = []
    if obs_lines:
        return (head + "Footprint case-law observations (validity tagged per entry; pick by your config context; "
                "contradictions are arbitrable by a targeted device experiment): "
                + " ".join(f"◇{ln}" for ln in obs_lines[:6])
                + " Judge which category this case falls into against the mindmap intent.")
    return (head + f"Query behavior observations via kb_footprint (node {node_id or 'not yet created'}) "
            "and judge against the mindmap intent whether this matters.")


def _detect_lb_methods(config_so_far: list) -> list:
    """从被测配置链抽负载均衡算法 token（生效的 method 行算法参数，小写；跳过 no/show/clear）。
    method 行形态是文法数据（statements.method_algorithm_line）。"""
    found: list[str] = []
    method_re = _dg.stmt_re("method_algorithm_line")
    for c in config_so_far:
        if _leading_verb(c) in ("no", "show", "clear"):
            continue
        m = method_re.search(c)
        if m:
            tok = m.group("name").lower()
            if tok and tok not in found:
                found.append(tok)
    return found


def _count_assertion_kind(expect: str, source_kind: str) -> str:
    """计数断言性质：'range'（有界区间＝分布类正确形态）/ 'unbounded'（Hit:\\d+ 任意数字＝恒真）
    / 'hardcoded'（Hit:固定数＝写死单计数，分布算法下偶对偶错）/ ''（非计数断言）。
    source.kind=distribution_derived（emit 展开标的）直接认 'range'。"""
    if source_kind == "distribution_derived":
        return "range"
    if not expect:
        return ""
    if _BOUNDED_RANGE_RE.search(expect):
        return "range"
    if _HIT_FIELD_RE.search(expect):
        if _UNBOUNDED_DIGIT_RE.search(expect):
            return "unbounded"          # Hit:\d+ 无界＝任意数字都过＝恒真
        if re.search(r"[0-9]", expect):
            return "hardcoded"          # Hit:固定数（如 Hit:\s+1）＝写死单次计数
    return ""


def _load_rows(xlsx_path: str) -> list[dict]:
    """读 case.xlsx 数据区为 [{E,F,G,H,...}...]。复用 precedent_tools._load_case_rows
    （lazy import：它顶层 import openpyxl，路径走 main 包）。"""
    from main.ist_core.tools.device.precedent_tools import _load_case_rows
    return _load_case_rows(xlsx_path)


def _load_provenance(prov_path: str):
    """读 provenance（"-" 或空或不存在 → None）。复用 parse_provenance（lazy import）。"""
    if not prov_path or prov_path == "-":
        return None
    p = Path(prov_path)
    if not p.is_file():
        return None
    try:
        from main.case_compiler.provenance_ir import parse_provenance
        return parse_provenance(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _prov_step(provenance, step_idx: int):
    """取 provenance 第 step_idx 个 emit 步（缺/越界 → None）。steps 与 xlsx 数据区同序（emit 契约）。"""
    if provenance is None:
        return None
    steps = getattr(provenance, "steps", None) or []
    return steps[step_idx] if 0 <= step_idx < len(steps) else None


def _prov_layer(provenance, step_idx: int) -> str:
    """第 step_idx 步的 layer（G/E/V）；缺则空。"""
    s = _prov_step(provenance, step_idx)
    return (getattr(s, "layer", "") or "") if s is not None else ""


def _prov_source(provenance, step_idx: int) -> tuple[str, str]:
    """第 step_idx 步的 (source.kind, source.ref)；缺则 ("","")。"""
    s = _prov_step(provenance, step_idx)
    if s is None:
        return "", ""
    src = getattr(s, "source", None)
    return (getattr(src, "kind", "") or "", getattr(src, "ref", "") or "")


def _intent_record_type_gap(intent_text: str, rows: list) -> list:
    """意图↔卷面 DNS 记录类型覆盖比对(原理②秩亏的意图侧;类型闭集是协议文法数据)。

    意图文本按词边界命中的记录类型,若在卷面任一 dig 观测命令中零出现 → 缺口列表。
    只产结构事实交读者判(意图可能是否定语境如"不支持 AAAA"),不做门。实证 2026-07-09
    selfheal2 035644:意图『请求A或AAAA类型』,worker 在 frozen override 压力下删掉会
    fail 的 AAAA 断言——覆盖面被静默砍掉、假 PASS 交付+毒先例写回,离线只有这个比对能查到。
    """
    intent_types = {t for t in _dg.dns_record_types()
                    if re.search(rf"(?<![A-Za-z0-9]){t}(?![A-Za-z0-9])", intent_text)}
    if not intent_types:
        return []
    digs = " ".join(str(r.get("G") or "") for r in rows
                    if _is_observe_command(str(r.get("G") or "")))
    return sorted(t for t in intent_types
                  if not re.search(rf"(?<![A-Za-z0-9]){t}(?![A-Za-z0-9])", digs))


def extract(xlsx_path: str, prov_path: str, intent_text: str = "") -> dict:
    """逐 check_point 产确定性信号 + case 级 V 段覆盖判断。返回 dict（见模块 docstring 模型）。

    每个 check_point 字段：
      idx, row_line, mode, expect, cp_h, layer(provenance G/E/V),
      query_object, query_object_tokens,
      observe_command, observe_kind(behavior/config_query/''),
      matched_config_command(expect 命中的前序配置命令；为配置存在性检查的证据),
      is_config_existence_check, is_genuine_v_assertion, layer_mismatch(标称 V 实为 G),
      source_kind, source_ref, query_object_invalid, suspect, suspect_reason

    case 级（顶层）字段：
      has_mutating_under_test(case 含 clear/no… 瞬时态命令，意图通常要测其运行时行为),
      mutating_commands, genuine_v_count(名副其实的 V 段断言数),
      weak_v_coverage_suspect(被测瞬时态行为却无任何真 V 段断言覆盖 → 弱 V 覆盖 / 恒真嫌疑),
      unanchored_new_pools(中途新增绑定到 host、成员 IP 从未被任何 check_point 引用过的 pool 名),
      new_member_unanchored_suspect(unanchored_new_pools 非空 → 疑似漏用命中归属锚定该新增 pool，
        是否要紧交给 grade 结合 need_intent 判——不是所有 case 都有顺序/归属类 claim），
      has_membership_anchor(该 case 是否用过命中归属锚点/member 声明；双通道识别——source_kind
        精确 + G 列形状签名兜底，不依赖 provenance 是否存在），
      suspect_count

    确定性判据（脏活，非终判；严格按论文三层）：
      observe_kind            = 配置查询 show（G 性质）/ dig·统计（V 性质）          —— §3.2 算子代数
      is_config_existence_check = observe_kind=='config_query' 且 expect 命中前序配置命令   —— G 段配置存在性
      is_genuine_v_assertion  = layer=='V' 且 不是配置存在性检查（验的是行为观测产物）    —— 真 V 覆盖
      layer_mismatch          = layer=='V' 但实为配置存在性检查（名 V 实 G，伪覆盖）
      weak_v_coverage_suspect = has_mutating_under_test 且 genuine_v_count==0          —— 秩亏/弱覆盖
      query_object_invalid    = offline 恒 False（xlsx G 列是观测命令非设备回显；dangling 由上机/结构门另判）
    """
    rows = _load_rows(xlsx_path)
    provenance = _load_provenance(prov_path)

    # provenance.steps 与 _load_rows 行号可能差偏移（init 行等），故 layer/source 不按行号对齐，
    # 而按「第 k 个 check_point」对齐：provenance 里第 k 个 check_point 步 ↔ xlsx 第 k 个 check_point。
    prov_cp_layers: list[str] = []
    prov_cp_sources: list[tuple] = []
    for s in (getattr(provenance, "steps", None) or []):
        if (getattr(s, "E", "") or "").strip() == "check_point":
            src = getattr(s, "source", None)
            prov_cp_layers.append(getattr(s, "layer", "") or "")
            prov_cp_sources.append(((getattr(src, "kind", "") or ""), (getattr(src, "ref", "") or "")))

    check_points: list[dict] = []
    # 截至当前的 APV 配置/动作命令链（被测命令链，含 clear/no）；与 link_assertion_to_config 同口径。
    config_so_far: list[str] = []
    config_line_rows: list[int] = []   # 与 config_so_far 逐位对应的行号（_unanchored_new_pools 用）
    last_obs_idx = None     # 最近一个产出回显的观测步（show/dig/...）
    for i, row in enumerate(rows):
        e = (row.get("E") or "").strip()
        g = (row.get("G") or "").strip()
        if e != "check_point":
            if e.startswith("APV") and g:        # APV 配置/动作命令，累进被测命令链
                for line in g.split("\n"):
                    if line.strip():
                        config_so_far.append(line.strip())
                        config_line_rows.append(i)
            # 带 H 的观测步仅存寄存器、不刷 result（对齐框架 test_xlsx:308 / structural_gate:201 /
            # confidence_f）。漏 `not h` → 带 H 的 dig 被误当后续 check_point 的观测源 → IP 断言
            # (断错缓冲)被误判 behavior/真 V、genuine_v_count 虚高 → grade 干净体检单放过（GA 假
            # PASS 根因，681783 实测 4→0）。
            if g and _is_observe_command(g) and not (row.get("H") or "").strip():
                last_obs_idx = i
            continue

        mode = (row.get("F") or "").strip()         # found / not_found
        expect = (row.get("G") or "").strip()       # 断言期望值（字面量；寄存器引用时常为空）
        cp_h = (row.get("H") or "").strip()         # 寄存器引用名（关系断言非空）
        cp_idx = len(check_points)                  # 第几个 check_point（与 provenance 同序对齐）
        layer = prov_cp_layers[cp_idx] if cp_idx < len(prov_cp_layers) else ""        # draft 标的 G/E/V
        cp_src_kind, cp_src_ref = prov_cp_sources[cp_idx] if cp_idx < len(prov_cp_sources) else ("", "")

        query_object = expect
        query_tokens = _object_tokens(expect)

        # 观测算子性质（产生本断言回显的那条 show/dig）——客观判据，不依赖 draft 标注。
        observe_cmd = (rows[last_obs_idx].get("G") or "").strip() if last_obs_idx is not None else ""
        observe_kind = _observe_kind(observe_cmd)
        # offline grade：xlsx 观测步 G 列存的是**命令**（show/dig…），不是设备回显。
        # 回显仅上机后才有（dev_run / probe），此处无法判 dangling → 恒 False，避免把命令文本
        # 误当回显跑 has_cli_error（如命令里碰巧含 "invalid" 子串的假阳性）。
        query_object_invalid = False

        # 配置存在性检查（G 性质恒真）：observe_ops 单一事实源（与 confidence_f 同实现）。传 mode（F 列
        # 算子）——only `found(配置)` 恒真→is_config_existence_check=True；`not_found/abs_found` 命中配置
        # →(False, matched_cfg)：matched_cfg 非空（确曾配过）但非恒真。
        is_config_existence_check, matched_cfg = _config_existence_check(observe_cmd, expect, config_so_far, mode)
        # 真 V 段断言（贡献 Cov）两类：① 行为观测（dig/统计/session 回显）验业务行为；② **show 上的状态
        # 变更验证**——`not_found/abs_found(配过的配置)` 验「配置被移除/覆盖后消失」（应急池覆盖、删除配置
        # 类：产品上只能用 show 观测、无 dig/统计能暴露哪个生效），它非恒真（配置还在就 fail）、是真行为
        # 验证。漏了②正是「只能 show 观测的状态变更类」被钉死 genuine_v=0、连续 CUT 的根（105969）。
        # ★用客观算子性质判，不轻信 draft 标的 layer（draft 会误标）。
        _is_state_change = (observe_kind == "config_query") and (mode in ("not_found", "abs_found")) \
            and bool(matched_cfg)
        is_genuine_v_assertion = (not query_object_invalid) and (
            (observe_kind == "behavior" and mode in ("found", "not_found", "abs_found"))
            or _is_state_change)
        # 名实不符（辅助信号给 grade）：draft 标 layer=V，实为 G 段配置存在性检查（伪覆盖/秩亏）。
        layer_mismatch = (layer == "V") and is_config_existence_check
        # 预期冲突探针（缺陷②/论文"期望值必须溯源"）：断言期望值是设备错误回显（Invalid input/not support…），
        # 但来源 kind=intent（仅凭脑图意图、无手册/先例/config 客观溯源）——典型"脑图说设备会拒绝/报错 X，
        # 却无手册依据、实机未必如此"。这是 588990 配置存在性伪覆盖之外的另一类假阳性：589432 删 ALL 断言
        # found "Invalid input"，来源仅脑图意图，而实机 ALL 合法不报此错 → 应 escalate 标「用例预期冲突」。
        # spec_conflict 用「预期拒绝语义」词表（人写措辞），不复用面向真实回显的 has_cli_error（对抗 review HIGH 修复）。
        expect_is_error_echo = _expect_is_rejection(expect)
        spec_conflict_suspect = (cp_src_kind == "intent") and expect_is_error_echo

        # 计数断言性质：有界区间(分布正确) / 无界 \d+(恒真) / 写死固定数(偶对偶错) / 非计数。
        count_kind = _count_assertion_kind(expect, cp_src_kind)
        is_distribution_assertion = count_kind == "range"
        count_tautology_suspect = count_kind == "unbounded"
        # 本断言所在 case 此刻是否已配分布算法——写死命中落点/固定计数只在分布上下文判可疑
        # （确定性映射类算法固定落点合法，不在此误杀；分类见文法数据 algorithm_classes）。
        _dist_ctx = any(m in _dg.distribution_methods() for m in _detect_lb_methods(config_so_far))
        count_hardcoded_suspect = (count_kind == "hardcoded") and _dist_ctx
        # D：写死单次命中落点 IP——分布算法下 dig found 一个字面成员 IP＝断言"这一发必中它"，但命中哪个
        # 由运行时轮转起点定(同 absolute_position 不可证伪)。寄存器关系(cp_h)/分布区间/命中归属锚点/
        # <RUNTIME> 除外——membership_derived(member 声明展开)断言的是"这次输出∈某 pool 的成员集合"
        # (归属判定，可能是多成员 alternation 也可能是单成员 pool)，不是"这一发必中这一个写死的值"，
        # 结构上都含字面 IP 但语义不同，漏排会把合法的命中归属断言误判成偶对偶错的假断言。
        # 排除双通道：source_kind（有 provenance 时精确）+ _MEMBER_ANCHOR_SHAPE_RE（provenance
        # 缺失时兜底——compile-worker 目前不传 provenance_json，纯靠 source_kind 会在主链路失效）。
        asserts_literal_hit_ip = bool(
            _dist_ctx and mode == "found" and observe_kind == "behavior" and not cp_h
            and cp_src_kind not in ("captured_relation", "distribution_derived",
                                    "membership_derived", "device_runtime")
            and not _MEMBER_ANCHOR_SHAPE_RE.search(expect)
            and _LITERAL_IPV4_RE.search(expect))
        # 命中归属锚点识别（案例级 has_membership_anchor 用）：同上双通道——source_kind 精确 +
        # 形状签名兜底，不依赖 provenance 是否存在（compile-worker 主路现状不传）。
        is_membership_anchor = bool(
            mode in ("found", "not_found")
            and (cp_src_kind == "membership_derived" or _MEMBER_ANCHOR_SHAPE_RE.search(expect)))

        suspect = (layer_mismatch or query_object_invalid or spec_conflict_suspect
                   or count_hardcoded_suspect or asserts_literal_hit_ip)
        reasons = []
        if layer_mismatch:
            reasons.append(
                f"Assertion claims layer=V but is a config-existence check (observe = config-query show; expect matches the "
                f"prior config command '{matched_cfg}') — actually G-layer, verifies no business behavior, contributes 0 to coverage (rank-deficient / pseudo-V)")
        elif observe_kind == "config_query" and matched_cfg and layer != "V":
            reasons.append("Config-existence check (G-layer sanity precondition; not counted toward V coverage)")
        if spec_conflict_suspect:
            reasons.append(
                f"Expected value '{expect[:30]}' is a device error echo, but source kind=intent (mindmap only; no manual/precedent provenance) "
                "— suspected intent-vs-reality conflict (asserts the device will reject, without manual grounds; the real device may not). "
                "Verify source_ref, then treat as CUT with root cause 'intent expectation conflict'")
        if query_object_invalid:
            reasons.append("Observation step echo has syntax error / no valid echo (dangling observation)")
        if count_tautology_suspect:
            reasons.append("Hit-count assertion uses unbounded \\d+ (any number passes = always-true, verifies no distribution) — "
                           "distribution classes (rr/wrr) need conserving interval assertions: each backend's cumulative hits ∈ [N/k±tolerance], expanded deterministically via the dist declaration")
        if count_hardcoded_suspect:
            reasons.append("Hit-count assertion hardcodes a fixed number (e.g. Hit:\\s+1) — under distribution algorithms (rr/wrr) a backend's "
                           "hit count varies with runtime rotation/health checks; hardcoding = right-by-luck (observe-then-assert). Use a distribution interval (dist) or a register relation assertion")
        if asserts_literal_hit_ip:
            reasons.append("Under distribution algorithms (rr/wrr) the dig assertion hardcodes a single member IP — 'this query must hit it' is decided "
                           "by the runtime rotation start and is unfalsifiable (right-by-luck, same as absolute_position). Correct forms are H capture-compare (captured_relation) "
                           "or a distribution interval (dist), never a hardcoded landing IP")
        if is_distribution_assertion:
            reasons.append("Distribution interval assertion (distribution_derived / bounded count interval): legitimate V coverage for distribution classes; "
                           "expectations derive offline from algorithm semantics and are conservation-checkable. Do not CUT for lacking a hardcoded per-query hit; CUT only when the interval degenerates to always-true")

        check_points.append({
            "idx": len(check_points),
            "row_line": i,
            "mode": mode,
            "expect": expect,
            "cp_h": cp_h,
            "layer": layer,
            "query_object": query_object,
            "query_object_tokens": query_tokens,
            "observe_command": observe_cmd,
            "observe_kind": observe_kind,
            "matched_config_command": matched_cfg,
            "is_config_existence_check": is_config_existence_check,
            "is_genuine_v_assertion": is_genuine_v_assertion,
            "layer_mismatch": layer_mismatch,
            "source_kind": cp_src_kind,
            "source_ref": cp_src_ref,
            "query_object_invalid": query_object_invalid,
            "expect_is_error_echo": expect_is_error_echo,
            "spec_conflict_suspect": spec_conflict_suspect,
            "is_distribution_assertion": is_distribution_assertion,
            "count_tautology_suspect": count_tautology_suspect,
            "count_hardcoded_suspect": count_hardcoded_suspect,
            "asserts_literal_hit_ip": asserts_literal_hit_ip,
            "is_membership_anchor": is_membership_anchor,
            "suspect": suspect,
            "suspect_reason": "；".join(reasons),
        })

    # —— case 级：V 段覆盖（论文：覆盖只由 V 段断言判定）——
    mutating_commands = [c for c in config_so_far if _leading_verb(c) in _MUTATING_VERBS]
    has_mutating_under_test = bool(mutating_commands)
    genuine_v_count = sum(1 for c in check_points if c["is_genuine_v_assertion"])
    # 被测了瞬时态行为（clear/no…），却无任何名副其实的 V 段断言覆盖其效果 → 秩亏/弱 V 覆盖。
    weak_v_coverage_suspect = has_mutating_under_test and genuine_v_count == 0 and bool(check_points)
    # case 级预期冲突：任一断言是「kind=intent 错误回显」（断言设备报错却无手册依据）→ 疑似脑图预期冲突。
    spec_conflict_suspect = any(c["spec_conflict_suspect"] for c in check_points)

    # —— case 级：分布类算法覆盖（原理②秩亏 + ③出处缺失的分布上下文）——
    lb_methods = _detect_lb_methods(config_so_far)
    has_distribution_method = any(m in _dg.distribution_methods() for m in lb_methods)
    distribution_assertion_count = sum(1 for c in check_points if c["is_distribution_assertion"])
    has_distribution_assertion = distribution_assertion_count > 0
    count_tautology_count = sum(1 for c in check_points if c["count_tautology_suspect"])
    # 分布算法下写死单次命中落点 IP / 写死固定命中计数 = observe-then-assert（偶对偶错，778012 根因）。
    count_hardcoded_count = sum(1 for c in check_points if c["count_hardcoded_suspect"])
    asserts_literal_hit_ip_count = sum(1 for c in check_points if c["asserts_literal_hit_ip"])
    hardcoded_count_suspect = has_distribution_method and count_hardcoded_count > 0
    hardcoded_hit_ip_suspect = has_distribution_method and asserts_literal_hit_ip_count > 0
    has_register_relation = any(c["cp_h"] for c in check_points)
    # 配了分布算法(rr/wrr)却既无分布区间断言、也无关系断言 → 疑似漏测分布（dongkl WEAK_no_count 类）。
    # 注：无界 Hit:\d+ 因 observe=show statistics=behavior 会被 is_genuine_v 计为真 V、骗过 weak_v；
    # 本信号据「有界分布区间」而非「有没有 Hit 字段」判，专抓这类恒真伪覆盖。
    distribution_coverage_gap_suspect = (
        has_distribution_method and not has_distribution_assertion and not has_register_relation)

    # —— case 级：原理④引用图（对象文法来自 JSON，新增同类检查=加数据条目零代码）——
    # 锚定链：中途新增接入解析链的对象，其派生值集合从未被断言引用（结构信号，不判对错）。
    first_cp_row = check_points[0]["row_line"] if check_points else None
    all_expects = [c["expect"] for c in check_points if c.get("expect")]
    unanchored_new_pools: list = []
    for chain in _dg.anchoring_chains():
        found = _dg.unanchored_bound_objects(chain, config_so_far, config_line_rows,
                                             first_cp_row, all_expects, _ip_literal_pattern)
        if chain["id"] == "new_pool_member_anchoring":
            unanchored_new_pools = found
    new_member_unanchored_suspect = bool(unanchored_new_pools)
    has_membership_anchor = any(c["is_membership_anchor"] for c in check_points)

    # 引用闭合：被引用对象无对应定义命令（悬空引用；设备静默接受、离线才查得到）。
    # 文案是判例层——运行时从 footprint 观察取，不写死在代码（P2-3）。
    cname_members_not_local: list = []
    cname_member_not_local_host_note = ""
    for closure in _dg.reference_closures():
        found = _dg.dangling_references(closure, config_so_far)
        if closure["id"] == "cname_member_needs_local_host":
            cname_members_not_local = found
            if found:
                cname_member_not_local_host_note = _closure_case_law_note(closure, found)
    cname_member_not_local_host_suspect = bool(cname_members_not_local)

    # —— case 级:意图记录类型覆盖(原理②意图侧;条件字段——intent_text 非空才输出,
    # 默认调用输出结构与旧版逐比特一致,等价性反扫兼容)——
    intent_gap: list = _intent_record_type_gap(intent_text, rows) if intent_text else []

    suspect_count = (sum(1 for c in check_points if c["suspect"])
                     + (1 if weak_v_coverage_suspect else 0)
                     + (1 if distribution_coverage_gap_suspect else 0)
                     + (1 if new_member_unanchored_suspect else 0)
                     + (1 if cname_member_not_local_host_suspect else 0)
                     + (1 if intent_gap else 0))

    return {
        "status": "success",
        "xlsx": xlsx_path,
        "provenance_loaded": provenance is not None,
        "total_check_points": len(check_points),
        "mutating_commands": mutating_commands,
        "has_mutating_under_test": has_mutating_under_test,
        "genuine_v_count": genuine_v_count,
        "weak_v_coverage_suspect": weak_v_coverage_suspect,
        "spec_conflict_suspect": spec_conflict_suspect,
        "lb_methods": lb_methods,
        "has_distribution_method": has_distribution_method,
        "distribution_assertion_count": distribution_assertion_count,
        "has_distribution_assertion": has_distribution_assertion,
        "count_tautology_count": count_tautology_count,
        "count_hardcoded_count": count_hardcoded_count,
        "hardcoded_count_suspect": hardcoded_count_suspect,
        "asserts_literal_hit_ip_count": asserts_literal_hit_ip_count,
        "hardcoded_hit_ip_suspect": hardcoded_hit_ip_suspect,
        "distribution_coverage_gap_suspect": distribution_coverage_gap_suspect,
        "unanchored_new_pools": unanchored_new_pools,
        "new_member_unanchored_suspect": new_member_unanchored_suspect,
        "has_membership_anchor": has_membership_anchor,
        "cname_members_not_local": cname_members_not_local,
        "cname_member_not_local_host_suspect": cname_member_not_local_host_suspect,
        "cname_member_not_local_host_note": cname_member_not_local_host_note,
        "suspect_count": suspect_count,
        "check_points": check_points,
        **({"intent_record_type_gap": intent_gap,
            "intent_record_type_gap_suspect": True,
            "intent_record_type_gap_note": (
                "The intent text mentions DNS record type(s) " + ", ".join(intent_gap)
                + " but no dig observation on the sheet ever queries them. If the intent truly requires verifying "
                  "that type's resolution behavior, this is a coverage gap (add the dig observation and assertion; "
                  "removing coverage to dodge a failure is forbidden). If the intent is a negative/exclusion context "
                  "(e.g. 'does not support X'), ignore this hint and say so in your return.")}
           if intent_gap else {}),
    }


def main():
    if len(sys.argv) < 3:
        print("Usage: python grade_extract.py <case.xlsx> <case.provenance.json | \"-\">",
              file=sys.stderr)
        print("\n确定性探针（对齐论文三层 G/E/V）：逐 check_point 核 layer 名实 + 算子性质，",
              file=sys.stderr)
        print("产 is_genuine_v_assertion / layer_mismatch / weak_v_coverage_suspect 等信号"
              "供 grade LLM 据真证据与需求意图判（脚本不下终判）。", file=sys.stderr)
        sys.exit(1)

    xlsx_path = sys.argv[1]
    prov_path = sys.argv[2]
    try:
        result = extract(xlsx_path, prov_path)
    except Exception as exc:  # noqa: BLE001 — 读 xlsx 失败给可读错误并退 1
        print(f"ERROR: 读取/解析失败 xlsx={xlsx_path!r}: {exc}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
