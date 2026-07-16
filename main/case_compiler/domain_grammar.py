"""领域对象文法加载器 + 文法驱动的通用引用图查询（三层架构，2026-07-08 P2）。

三层分工：
- **原理层**（本模块的函数 + grade_extract 检测器）：闭合于数学——悬空引用是图论性质、
  锚定是"派生值集合被断言引用过"的集合性质，与具体产品对象无关；
- **文法层**（`knowledge/data/compile_ref/domain_grammar.json`）：产品 CLI 的对象
  定义/引用形态、算法分类、动词表——随产品手册版本演进，更新=编辑 JSON 不改代码；
- **判例层**（footprint 观察）：行为知识随观察演化，文案按引用现取（见 grade_extract）。

新增一类"被引用对象必须有对应定义"的检查 = 在 JSON `reference_closures` 加条目，
`dangling_references()` 自动生效，零代码。锚定链拓扑变化（非 bind→member→resolve
两跳）才需要动 `unanchored_bound_objects()`。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from main.knowledge_paths import KNOWLEDGE_DATA_ROOT

GRAMMAR_PATH = KNOWLEDGE_DATA_ROOT / "compile_ref" / "domain_grammar.json"

_cache: dict = {}


def load_grammar() -> dict:
    """读文法数据（进程内按 mtime 缓存）。文件缺失/坏 JSON 直接抛——文法是检测器的
    事实源，静默回退内置默认=词表漂移隐患（宁可炸得早）。"""
    try:
        mtime = GRAMMAR_PATH.stat().st_mtime_ns
    except OSError as exc:
        raise FileNotFoundError(f"领域文法数据缺失: {GRAMMAR_PATH}") from exc
    if _cache.get("mtime") == mtime:
        return _cache["data"]
    data = json.loads(GRAMMAR_PATH.read_text(encoding="utf-8"))
    # 语句 pattern 预编译（IGNORECASE：CLI/域名比较大小写不敏感，与原实现一致）
    compiled = {sid: re.compile(s["pattern"], re.IGNORECASE)
                for sid, s in data.get("statements", {}).items()}
    _cache.update(mtime=mtime, data=data, compiled=compiled)
    return data


def stmt_re(stmt_id: str) -> re.Pattern:
    load_grammar()
    return _cache["compiled"][stmt_id]


def verbs(class_name: str) -> tuple[str, ...]:
    vc = load_grammar()["verb_classes"][class_name]
    return tuple(vc.get("verbs") or vc.get("words") or ())


def distribution_methods() -> tuple[str, ...]:
    return tuple(load_grammar()["algorithm_classes"]["distribution"]["methods"])


def uniform_rotation_methods() -> tuple[str, ...]:
    """等权严格轮转类算法集(E10b cycle_kind 映射的数据源;fail-open 缺键返回 ()——
    grammar 无该类时序列↔周期检查对一切算法中性放行,未知不误杀)。新算法上机钉死
    等权语义后加 JSON methods 条目零代码。"""
    return tuple(((load_grammar().get("algorithm_classes") or {})
                  .get("uniform_rotation") or {}).get("methods") or ())


def deterministic_mapping_methods() -> tuple[str, ...]:
    """确定性映射类算法集(distribution.provenance 散文知识的机读提升,2026-07-16)。
    verifiability 三分判定用:分布/确定性映射/未知——未知永远 fail-open(原文带
    『等』字=非穷举,封闭世界假设是误杀源)。fail-open 缺键返回 ()。"""
    return tuple(((load_grammar().get("algorithm_classes") or {})
                  .get("deterministic_mapping") or {}).get("methods") or ())


def count_field_words() -> tuple[str, ...]:
    return tuple(load_grammar()["count_field_words"]["words"])


def rejection_hints() -> tuple[str, ...]:
    return tuple(load_grammar()["rejection_semantics"]["hints"])


def dns_record_types() -> tuple[str, ...]:
    return tuple(load_grammar()["dns_record_types"]["words"])


def persistence_patterns() -> tuple[str, ...]:
    """全部持久化通道识别正则(local_disk/peer_node/segment_fs…patterns 并集)。
    消费方:diagnose 批级 s₀ 配对——通道枚举在数据层,新通道加条目零代码。"""
    chans = load_grammar().get("persistence_channels") or {}
    out: list[str] = []
    for key, ch in chans.items():
        if key.startswith("_") or not isinstance(ch, dict):
            continue
        out.extend(str(p) for p in (ch.get("patterns") or []))
    return tuple(out)


def l23_write_patterns() -> tuple[str, ...]:
    """L2/L3 系统对象写形态(复位差集 (32) 内分量;diagnose s₀ 配对用)。"""
    return tuple((load_grammar().get("bed_l23_write_forms") or {}).get("patterns") or ())


def occupancy_semantics() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """「已占用/已存在」回显语义 (patterns, negations)——diagnose 自扰判定用
    (词带边界+否定排除,数据带出处;防 marker 关键字表回潮)。"""
    oc = load_grammar().get("occupancy_semantics") or {}
    return (tuple(oc.get("patterns") or ()), tuple(oc.get("negations") or ()))


def forbidden_mechanism_intents() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """禁令机制的意图侧词表 ((family, patterns), ...)——F6 路由用(§18.11)。
    destructive_commands 是命令正则匹配不到中文意图文本;本表按族给意图词
    (CJK 子串+英文显式边界),author 盖章扫描消费。误报语义=呈报非硬拒,见数据段出处。"""
    fm = load_grammar().get("forbidden_mechanism_intents") or {}
    return tuple((str(f.get("family") or ""), tuple(f.get("patterns") or ()))
                 for f in (fm.get("families") or []))


def reference_closures() -> list[dict]:
    return list(load_grammar().get("reference_closures", []))


def anchoring_chains() -> list[dict]:
    return list(load_grammar().get("anchoring_chains", []))


def co_required_params() -> list[dict]:
    """同语句共需参数规则(B1',2026-07-16)。fail-open:键/rules 缺失返回 []——
    rules 首发空置(572708 两轮两种设备响应,weight/priority 必带性待 C7 上机钉死,
    confirmed_on_device=false 不落条目),空数据=零行为变化。钉死后加 JSON 条目
    零代码生效(schema 见 json `co_required_params._schema_example`)。"""
    return list((load_grammar().get("co_required_params") or {}).get("rules") or [])


def missing_co_required(rules: list[dict], lines: list[str]) -> list[dict]:
    """co-required 参数缺失检测(纯函数,风格同 dangling_references):trigger 语句命中
    ∧ condition 参数值命中 ∧ 同语句行 requires_pattern 零命中 → 报
    ``{rule_id, line, provenance}``(结构事实——消费方 emit 成功路径渲染 advisory 文本,
    非门不拒绝:参数语义是内容依赖判断,硬门化违 (47) 位阶红线,与签名闭集的
    command_existence 结构门不同类)。

    condition.param 指 trigger 语句正则的**命名捕获组**(组缺失回退 ``name`` 组——
    statements 表惯用组名);值比较大小写不敏感(CLI 语义,与语句预编译 IGNORECASE
    一致)。坏规则(trigger 未注册/正则不编译/requires_pattern 空)整条跳过——
    条目质量由 provenance + confirmed_on_device 字段与单测约束,检测器不硬炸。
    """
    out: list[dict] = []
    for rule in rules or []:
        req_pat = str(rule.get("requires_pattern") or "")
        if not req_pat:
            continue
        try:
            trig = stmt_re(str(rule.get("trigger_statement") or ""))
            req = re.compile(req_pat, re.IGNORECASE)
        except (KeyError, re.error):
            continue
        cond = rule.get("condition") or {}
        values = {str(v).lower() for v in (cond.get("values") or [])}
        param = str(cond.get("param") or "")
        for line in lines:
            m = trig.search(line)
            if not m:
                continue
            gd = m.groupdict()
            val = str(gd.get(param) or gd.get("name") or "").lower()
            if values and val not in values:
                continue
            if not req.search(line):
                out.append({"rule_id": str(rule.get("id") or ""),
                            "line": line,
                            "provenance": rule.get("provenance") or {}})
    return out


# ── 文法驱动的通用图查询（原理层：图论/集合性质，对象形态全部来自文法数据） ──────────

def _leading_verb(line: str) -> str:
    toks = (line or "").strip().split()
    return toks[0].strip().strip('"\'').lower() if toks else ""


def _norm_name(name: str, how: str) -> str:
    if how == "dns_name":       # DNS 名字比较大小写不敏感、忽略尾点
        return name.rstrip(".").lower()
    return name


def dangling_references(closure: dict, lines: list[str]) -> list[str]:
    """悬空引用（图论性质）：closure 声明的 references 语句捕获的对象名，若无任一
    defines 语句为其提供定义 → 悬空。返回保序去重的**原始写法**名单（结构事实，
    不判对错——要不要紧由读者对照意图判）。"""
    skip = tuple(closure.get("skip_leading_verbs") or ())
    def_res = [stmt_re(sid) for sid in closure.get("defines", [])]
    ref_res = [stmt_re(sid) for sid in closure.get("references", [])]
    norm = closure.get("normalize", "")

    defined: set[str] = set()
    referenced: list[str] = []
    for line in lines:
        if skip and _leading_verb(line) in skip:
            continue
        matched = False
        for r in def_res:
            m = r.search(line)
            if m:
                defined.add(_norm_name(m.group("name"), norm))
                matched = True
                break
        if matched:
            continue
        for r in ref_res:
            m = r.search(line)
            if m:
                referenced.append(m.group("name"))
                break
    out: list[str] = []
    seen: set[str] = set()
    for name in referenced:
        n = _norm_name(name, norm)
        if n not in defined and n not in seen:
            seen.add(n)
            out.append(name)
    return out


def unanchored_bound_objects(chain: dict, lines: list[str], line_rows: list[int],
                             first_cp_row, expects: list[str],
                             value_pattern) -> list[str]:
    """锚定查询（集合性质）：bind 语句把对象接入解析链后（行号 > 首个断言行 = "中途
    新增"），该对象经 member_edge→resolve 两跳派生出的值集合，若从未被任何断言
    expect 引用（按 value_pattern 生成的匹配式查）→ 未锚定。返回保序对象名单。

    value_pattern(v) -> 正则串：值在 expect 里的写法变体（如 IP 的 `.`/`\\.` 两种），
    协议级形态属原理层由调用方给。
    """
    if first_cp_row is None:
        return []
    bind_re = stmt_re(chain["bind"])
    member_re = stmt_re(chain["member_edge"])
    resolve_re = stmt_re(chain["resolve"])

    members: dict[str, list[str]] = {}
    values: dict[str, str] = {}
    first_bind_row: dict[str, int] = {}
    for line, row_idx in zip(lines, line_rows):
        m = member_re.search(line)
        if m:
            members.setdefault(m.group("from"), []).append(m.group("to"))
            continue
        m = resolve_re.search(line)
        if m:
            values.setdefault(m.group("name"), m.group("value"))
            continue
        m = bind_re.search(line)
        if m:
            name = m.group("name")
            if name not in first_bind_row:
                first_bind_row[name] = row_idx

    unanchored: list[str] = []
    for obj, bind_row in first_bind_row.items():
        if bind_row <= first_cp_row:
            continue                    # 一开始就接入的，不是"中途新增"
        vals = [values[mm] for mm in members.get(obj, []) if mm in values]
        if not vals:
            continue                    # 派生不出值集合（命令变体/拼装不全），结构信息不够不判
        anchored = any(re.search(value_pattern(v), expect)
                       for v in vals for expect in expects)
        if not anchored:
            unanchored.append(obj)
    return unanchored
