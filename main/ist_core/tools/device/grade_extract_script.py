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

用法：
    python grade_extract.py <case.xlsx> <case.provenance.json | "-">

输出：
    JSON 到 stdout，exit 0 正常 / exit 1 读 xlsx 失败（打印可读错误）。
"""

import json
import re
import sys
from pathlib import Path


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


# 预期拒绝/不支持语义词表（draft 写的**人类预期**措辞）。spec_conflict 探针专用——
# 断言期望值含"操作被拒绝/参数不支持"语义、且来源 kind=intent（无客观溯源）= 脑图预期设备会拒绝
# 某操作却无手册依据（如"删/清 session ALL 预期不支持ALL"而实机 ALL 合法）。
# ★对抗 review HIGH 修复：刻意**不复用** device_errors.has_cli_error——它面向真实设备统一裁决句
#   (failed to execute/% invalid)、刻意不穷举业务措辞，对人写的 "not support"/"不支持"/"拒绝"
#   几乎全失配（589432 被逮住纯因恰好写了 "Invalid input"，换个措辞就漏）。
# ★刻意**不含** "不存在/not found"——那是合法的删除验证预期（删不存在配置→提示不存在），非预期冲突。
_REJECTION_HINTS = (
    "not support", "not supported", "unsupported", "not allow", "not allowed",
    "not permitted", "invalid", "illegal", "reject", "refus", "denied",
    "syntax error",  # 设备语法错误回显（不依赖 device_errors 避免循环 import）
    "不支持", "不允许", "不被支持", "拒绝", "非法", "无效",
)


def _expect_is_rejection(expect: str) -> bool:
    """断言期望值是否含"操作被拒绝/参数不支持"语义（人写预期措辞）。spec_conflict 探针用。"""
    low = (expect or "").lower()
    return any(h in low for h in _REJECTION_HINTS)


# ── 分布区间断言（算法类 rr/wrr）确定性识别 ─────────────────────────────────────────
# 分布类负载均衡：发 N 次→各后端累计命中∈统计区间（守恒 Σ==N），是合法 V 覆盖；与「ga 优先级 /
# 一致性哈希 / 会话保持」（确定性映射，走 captured_relation 关系断言）区分。
# rr/wrr/grr/gwrr = 均摊/加权轮询（分布类）；ga/hi/topology/rtt 等非分布（命中由优先级/探测/哈希定）。
_DISTRIBUTION_METHODS = ("rr", "wrr", "grr", "gwrr")
_METHOD_LINE_RE = re.compile(r"\bmethod\b\s+\S+\s+\"?([a-z]+)\"?", re.IGNORECASE)
# 命中/计数字段词（断言锚定的统计字段）。
_HIT_FIELD_RE = re.compile(r"(hit|命中|计数|counter|count|statistic)", re.IGNORECASE)
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


# ── 新增 pool 命中归属锚定（结构信号，pool→成员IP 映射由确定文法拼出，不猜领域语义）───────────
_POOL_SERVICE_RE = re.compile(r'sdns\s+pool\s+service\s+"?([\w.-]+)"?\s+"?([\w.-]+)"?', re.IGNORECASE)
_SERVICE_IP_RE = re.compile(r'sdns\s+service\s+ip\s+"?([\w.-]+)"?\s+([0-9a-fA-F:.]+)', re.IGNORECASE)
_HOST_POOL_RE = re.compile(r'sdns\s+host\s+pool\s+"?[\w.-]+"?\s+"?([\w.-]+)"?', re.IGNORECASE)
_HOST_NAME_RE = re.compile(r'sdns\s+host\s+name\s+"?([\w.-]+)"?', re.IGNORECASE)
_CNAME_MEMBER_RE = re.compile(
    r'sdns\s+pool\s+cname\s+member\s+"?[\w.-]+"?\s+"?([\w.-]+)"?', re.IGNORECASE)
# 一行式变体（先例卷观测到 `sdns pool cname <池名> <域名>`）：第二参**含点**才当成员域名
# （池名惯例无点），首参是 name/member/method 子命令词则不是这个形态。
_CNAME_INLINE_RE = re.compile(
    r'sdns\s+pool\s+cname\s+"?([\w-]+)"?\s+"?([\w-]+(?:\.[\w-]+)+)\.?"?\s*$', re.IGNORECASE)


def _ip_literal_pattern(ip: str) -> str:
    """构造能同时匹配 IP 原始写法与正则转义写法（`.`→`\\.`）的检测模式，用于在 check_point
    expect 文本里查这个 IP 是否被引用过（不管是常量断言还是 member/dist 展开的转义正则）。"""
    parts = ip.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return r"\\?\.".join(re.escape(p) for p in parts)
    return re.escape(ip)  # IPv6/其他：原样转义（冒号非正则元字符，不会被转义成 \:）


def _unanchored_new_pools(config_so_far: list, config_line_rows: list,
                           first_cp_row, check_points: list) -> list:
    """找出「中途新增绑定到 host、但成员 IP 从未被任何 check_point 引用过」的 pool 名列表。

    结构性判据（不解析领域语义、不猜 claim 类型）：
    - pool→成员IP 映射由 `sdns pool service`/`sdns service ip` 两条命令的确定文法拼出——
      这是配置的静态事实，不是猜的（对应 EXCEL_FUNCTIONS.md「命中归属锚点」①层）。
    - 「中途新增」= 该 pool 第一次 `sdns host pool` 绑定行的行号 > 该 case 第一个
      check_point 的行号（在这之前就已经在测某些东西了，这个 pool 才第一次接进解析链）。
    - 「未被锚定」= 它的成员 IP 一个都没在任何 check_point 的 expect 里出现过（不管以哪种
      转义形式）——不代表一定是缺陷（这条 case 可能压根没有顺序/归属类 claim），只是把
      「这个结构事实」交给 grade 结合 need_intent 判要不要紧（对齐 new_member_last 的
      成员归属锚序列：判定该在其他信号旁挂参考，不单独下终判）。
    """
    if first_cp_row is None:
        return []
    pool_services: dict[str, list[str]] = {}
    service_ips: dict[str, str] = {}
    first_bind_row: dict[str, int] = {}
    for line, row_idx in zip(config_so_far, config_line_rows):
        m = _POOL_SERVICE_RE.search(line)
        if m:
            pool_services.setdefault(m.group(1), []).append(m.group(2))
            continue
        m = _SERVICE_IP_RE.search(line)
        if m:
            service_ips.setdefault(m.group(1), m.group(2))
            continue
        m = _HOST_POOL_RE.search(line)
        if m:
            pool = m.group(1)
            if pool not in first_bind_row:
                first_bind_row[pool] = row_idx

    all_expects = [c["expect"] for c in check_points if c.get("expect")]
    unanchored: list[str] = []
    for pool, bind_row in first_bind_row.items():
        if bind_row <= first_cp_row:
            continue  # 一开始就绑定的 pool，不是"中途新增"
        member_ips = [service_ips[svc] for svc in pool_services.get(pool, []) if svc in service_ips]
        if not member_ips:
            continue  # 没解出成员 IP（命令变体/拼装不全），结构信息不够，不在此判
        anchored = any(
            re.search(_ip_literal_pattern(ip), expect)
            for ip in member_ips for expect in all_expects
        )
        if not anchored:
            unanchored.append(pool)
    return unanchored


def _cname_members_without_local_host(config_so_far: list) -> list:
    """cname 池成员域名里,未被本案 `sdns host name` 定义为本地域名的那些(结构事实,不判对错)。

    为什么值得报:设备对这种配置**静默接受**(config 全程无报错),但 A/AAAA 查询的 re-query
    需要成员域名自身是本地域名才解析得出 IP——不是的话 dig 只返回 CNAME 记录串,解析链在
    成员域名处断头(2026-07-08 设备实证;dongkl 035413 三轮 escalated 的根因即此,三轮设备
    回显里 dig 恒返回 `cname.a.com.` 而非 IP,无人质疑)。另一面,委托外部 DNS/只验证 CNAME
    记录返回的意图下这个形态又完全合法——所以这里只产结构事实当**提示**,要不要紧由 worker
    对照脑图意图判,不做门。DNS 名字比较大小写不敏感、忽略尾点。
    """
    local_hosts: set[str] = set()
    members: list[str] = []
    for line in config_so_far:
        if _leading_verb(line) in ("no", "clear", "show"):
            continue
        m = _HOST_NAME_RE.search(line)
        if m:
            local_hosts.add(m.group(1).rstrip(".").lower())
            continue
        m = _CNAME_MEMBER_RE.search(line)
        if m:
            members.append(m.group(1))
            continue
        m = _CNAME_INLINE_RE.search(line)
        if m and m.group(1).lower() not in ("name", "member", "method"):
            members.append(m.group(2))
    out: list[str] = []
    seen: set[str] = set()
    for d in members:
        dn = d.rstrip(".").lower()
        if dn not in local_hosts and dn not in seen:
            seen.add(dn)
            out.append(d)
    return out


def _detect_lb_methods(config_so_far: list) -> list:
    """从被测配置链抽负载均衡算法 token（生效的 method 行算法参数，小写；跳过 no/show/clear）。"""
    found: list[str] = []
    for c in config_so_far:
        if re.search(r"\bmethod\b", c, re.IGNORECASE) and _leading_verb(c) not in ("no", "show", "clear"):
            m = _METHOD_LINE_RE.search(c)
            if m:
                tok = m.group(1).lower()
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


def extract(xlsx_path: str, prov_path: str) -> dict:
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
        # 本断言所在 case 此刻是否已配分布算法(rr/wrr)——写死命中落点/固定计数只在分布上下文判可疑
        # （ga 优先级/一致性哈希/会话保持是确定性映射，固定落点合法，不在此误杀）。
        _dist_ctx = any(m in _DISTRIBUTION_METHODS for m in _detect_lb_methods(config_so_far))
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
                f"断言标称 layer=V 却是配置存在性检查（observe=配置查询 show、expect 命中前序配置命令"
                f"「{matched_cfg}」）——实为 G 段、不验业务行为，对覆盖贡献为 0（秩亏/伪 V）")
        elif observe_kind == "config_query" and matched_cfg and layer != "V":
            reasons.append("配置存在性检查（G 段健全性前置，不计入 V 段覆盖）")
        if spec_conflict_suspect:
            reasons.append(
                f"断言期望「{expect[:30]}」是设备错误回显，但来源 kind=intent（仅凭脑图意图、无手册/先例溯源）"
                "——疑似脑图预期与手册/实机冲突（断言设备会报错，却无手册依据、实机未必如此）；"
                "grade 应核 source_ref 后判 CUT 并标根因「用例预期冲突」")
        if query_object_invalid:
            reasons.append("观测步回显语法错误/无有效回显（dangling，对齐 589432）")
        if count_tautology_suspect:
            reasons.append("命中计数断言用无界 \\d+（任意数字都通过=恒真、不验分布）——分布类(rr/wrr)应改成"
                           "守恒区间断言：各后端累计命中∈[N/k±容差]，用 dist 声明确定性展开")
        if count_hardcoded_suspect:
            reasons.append("命中计数断言写死固定数（如 Hit:\\s+1）——分布算法(rr/wrr)下某后端命中数随运行时"
                           "轮转/健康检查变，写死=偶对偶错(observe-then-assert)；应改分布区间(dist)或寄存器关系断言")
        if asserts_literal_hit_ip:
            reasons.append("分布算法(rr/wrr)下 dig 断言写死单个成员 IP——'这一发必中它'由运行时轮转起点定、"
                           "不可证伪(同 absolute_position 偶对偶错)；正确形态是 H 捕获比较(captured_relation)"
                           "或分布区间(dist)，不是写死命中落点")
        if is_distribution_assertion:
            reasons.append("分布区间断言（distribution_derived/有界计数区间）：分布类算法的合法 V 覆盖，"
                           "期望由算法语义离线推导+守恒可验，勿因没写死单次命中数判 CUT；只在区间退化恒真时才 CUT")

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

    # —— case 级：分布类算法（rr/wrr）覆盖 ——
    lb_methods = _detect_lb_methods(config_so_far)
    has_distribution_method = any(m in _DISTRIBUTION_METHODS for m in lb_methods)
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

    # —— case 级：新增 pool 命中归属锚定（结构信号，与算法类型/claim 类型无关）——
    first_cp_row = check_points[0]["row_line"] if check_points else None
    unanchored_new_pools = _unanchored_new_pools(config_so_far, config_line_rows, first_cp_row, check_points)
    new_member_unanchored_suspect = bool(unanchored_new_pools)
    has_membership_anchor = any(c["is_membership_anchor"] for c in check_points)

    # —— case 级：cname 池成员的本地域名闭合（引用图提示；设备静默接受、离线才查得到）——
    cname_members_not_local = _cname_members_without_local_host(config_so_far)
    cname_member_not_local_host_suspect = bool(cname_members_not_local)
    cname_member_not_local_host_note = (
        ("配置把 " + "、".join(cname_members_not_local) + " 作为 cname 池成员引用,但本案没有"
         "对应的 `sdns host name` 把它配成本地域名。两类意图受此影响:①A/AAAA 查询要最终解析出"
         " IP——re-query 需要成员自身是本地域名,否则 dig 只返回 CNAME 记录串、解析链断头;"
         "②域名状态门控类(service down 后不返回别名/按域名状态选池)——域名状态只对本地域名"
         "存在(远端域名恒可用,手册),成员不配本地域名则门控无对象、别名恒返回。设备对这两种"
         "情况都静默接受配置、不报任何错。只有「委托外部 DNS 且仅验证 CNAME 记录字符串返回」"
         "的意图下,现状才合法。对照脑图意图判断属于哪类。")
        if cname_members_not_local else "")

    suspect_count = (sum(1 for c in check_points if c["suspect"])
                     + (1 if weak_v_coverage_suspect else 0)
                     + (1 if distribution_coverage_gap_suspect else 0)
                     + (1 if new_member_unanchored_suspect else 0)
                     + (1 if cname_member_not_local_host_suspect else 0))

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
