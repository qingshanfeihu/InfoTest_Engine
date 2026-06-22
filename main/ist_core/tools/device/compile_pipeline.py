"""确定性编译流水线（V3 approach A）：把 prep→draft→grade→merge 锁成一个工具调用。

为什么存在（颗粒度修正）：
编译流水线本质是**低自由度**任务——固定序列 prep→fanout(draft)→fanout(grade)→筛 PASS→merge，
脆弱、一致性关键、跑偏就废。此前用 inline skill 的散文让主 agent 自己编排这 5 个细粒度工具，
实测主 agent 失控（prep×3、fanout×2、误调 review-verification）。

对照标杆（Cursor create-skill §"Degrees of Freedom"：脆弱操作=低自由度=脚本；
ngs-analysis：重活在 scripts/*.py、skill 只调脚本不叙述步骤），把固定流水线降级成
**一个确定性工具**，主 agent 只调一次。论文口径：确定性机制执行流程，语义模型只在
draft/grade fork 内部（查命令/断言）自由——自由度配在 fork 内，不配在编排层。

brief 五要素从 manifest 字段**机械模板化**生成（autoid/title/step_intents/group_path
都在 manifest 里），不是语义判断——故可确定性产出，无需主 agent 逐条写。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_MAX_REWORK_ROUNDS = 3
# transient 端点错误(丢连接/限流/流中断)退避重试：与"质量重做≤3轮"分开，不消耗质量预算。
_TRANSIENT_RETRIES = 4
_TRANSIENT_BASE_SLEEP = 3.0


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


# 低置信先例不内联(提速 + 去误导):召回最佳相似度 < 此阈值 → 视作"无好先例",不塞 7.5K 大块,
# draft 回落到 footprint 自查(footprint 是手册事实,比烂先例更可靠)。算法类(ga/wrr)先例普遍只
# 0.16(匹配差且常带错算法),listener/forward 类 0.4+(好匹配)——0.20 正好分界。env 可调。
import os as _os
_PRECEDENT_MIN_SCORE = float(_os.environ.get("IST_PRECEDENT_MIN_SCORE", "0.20"))
_PRECEDENT_SCORE_RE = re.compile(r"意图([\d.]+)|配置([\d.]+)\+意图([\d.]+)")


def _precedent_best_score(text: str) -> float:
    best = 0.0
    for m in _PRECEDENT_SCORE_RE.finditer(text or ""):
        if m.group(1) is not None:
            best = max(best, float(m.group(1)))
        else:
            best = max(best, float(m.group(2)) + float(m.group(3)))
    return best


def _preretrieve_precedent(case: dict) -> str:
    """确定性预检索：用 case 意图召回最像的已验证先例（含完整配置基线），供 brief 内联。

    轨迹缩减核心：把"draft 自己在 ReAct 轮里调 qa_lookup_pattern"前移到流水线确定性预跑，
    draft 拿到现成先例 → 少几轮往返。检索是客观结构相似召回（非硬编码答案），draft 仍自由改写。

    **低置信不内联**：最佳相似度 < `_PRECEDENT_MIN_SCORE` 时返回 ""——烂先例(尤其算法类常带错变体)
    内联只会白塞 token + 先例支配误导,不如让 draft 回落 footprint 自查(已含手册事实)。
    """
    from main.ist_core.tools.device.precedent_tools import qa_lookup_pattern
    intent = " ".join(filter(None, [
        str(case.get("title", "")),
        " ".join(str(s.get("desc", "")) for s in (case.get("step_intents") or [])),
    ])).strip()
    if not intent:
        return ""
    try:
        out = qa_lookup_pattern.invoke({"my_config": "", "intent": intent, "limit": 2})
    except Exception:  # noqa: BLE001
        return ""
    if _precedent_best_score(out) < _PRECEDENT_MIN_SCORE:
        return ""   # 低置信 → 不塞大块,走 _precedent_block 的轻量降级提示
    return out


def _precedent_block(precedent_text: str) -> str:
    """把预检索先例渲染成 brief 末尾的内联块（空召回时给降级提示）。"""
    if not precedent_text or not precedent_text.strip():
        return "\n\n（预检索未召回先例——分布外/新类型，自己 qa_footprint_lookup + grep 手册推断。）"
    return ("\n\n=== 预检索先例（确定性结构相似召回；含完整配置基线 + 触发→断言链 + 本测试床网络事实源）"
            "===\n照它改写，别再为它已给的东西重复检索。\n" + precedent_text.strip())


_SAVE_VARIANT_RE = re.compile(r"write\s+(mem\w*|file|all|net)", re.IGNORECASE)


def _derive_save_variant(case: dict) -> str:
    """从脑图 case 文本派生「配置保存」变体(memory|file|all|net),非保存类返回空。

    确定性解析作者意图(脑图原文写 "执行 write all 后..." → all),供持久化门校验 draft 没偷换
    保存变体。零硬编码(按命令词解析,不按 autoid)。
    """
    parts = [str(case.get("title", ""))]
    for s in (case.get("step_intents") or []):
        parts.append(str(s.get("desc", "")))
        parts.append(str(s.get("expected", "")))
    m = _SAVE_VARIANT_RE.search(" ".join(parts))
    if not m:
        return ""
    t = m.group(1).lower()
    return "memory" if t.startswith("mem") else t


# ── 变体保真(B 层):需求点名某枚举维度的变体,产出必须真用那个,不许偷换同枚举里别的 ──
# _SDNS_METHODS:手册 7190/7566 的算法枚举**快照**(footprint method 节点尚未结构化存枚举,
#   故此处冻结;手册改版需手动同步;TODO 待 footprint 补全后改运行时派生)。长在前(正则左优先)。
_SDNS_METHODS = ("gwrr", "grr", "wrr", "rtt", "rr", "ga", "hi", "snmp", "drop", "topology")
# 全局变体可替基础变体:点名 rr 用 grr(全局rr)、点名 wrr 用 gwrr,是合法严格实现,不算偷换(防误杀)。
_GLOBAL_OF = {"rr": "grr", "wrr": "gwrr"}
# intent 端:算法 token 前加边界(挡 xrr算法 粘连)+ 紧跟"算法"
_METHOD_INTENT_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(_SDNS_METHODS) + r")\s*算法")
# config 端:method 命令行整行判定(跳过 no/show/clear 非生效行)+ 按位置取算法参数(防域名误命中)
_METHOD_LINE_RE = re.compile(r"\bsdns\s+(?:host|pool)\s+method\b", re.IGNORECASE)
_OP_PREFIX_RE = re.compile(r"^\s*(?:no|show|clear)\b", re.IGNORECASE)
_HOST_METHOD_ARG_RE = re.compile(r"\bsdns\s+host\s+method\s+\S+\s+\"?(\w+)\"?", re.IGNORECASE)
_POOL_METHOD_ARG_RE = re.compile(
    r"\bsdns\s+pool\s+method\s+(?:(?:primary|secondary|fallback|default)\s+)?\"?[\w.]+\"?\s+\"?(\w+)\"?",
    re.IGNORECASE)


def _intent_methods(case: dict) -> set:
    """需求点名的算法集合。只从 title + step desc(动作)抽,**不含 expected**——断言文本常有
    "与 rr 算法不同" 类对比叙述会污染。findall 取全部(覆盖多算法用例),不只首个。"""
    parts = [str(case.get("title", ""))]
    for s in (case.get("step_intents") or []):
        parts.append(str(s.get("desc", "")))
    text = " ".join(parts)
    return {m.group(1).lower() for m in _METHOD_INTENT_RE.finditer(text)}


def _actual_methods(config_text: str) -> tuple[set, bool]:
    """返回(实际配的算法集合, 是否出现过 method 配置行)。逐行处理,跳过 no/show/clear(非生效配置)。"""
    fams: set = set()
    seen = False
    for line in (config_text or "").splitlines():
        if not _METHOD_LINE_RE.search(line) or _OP_PREFIX_RE.match(line):
            continue
        seen = True
        for rx in (_HOST_METHOD_ARG_RE, _POOL_METHOD_ARG_RE):
            m = rx.search(line)
            if m and m.group(1).lower() in _SDNS_METHODS:
                fams.add(m.group(1).lower())
    return fams, seen


def _method_satisfied(named: str, actual: set) -> bool:
    """点名 named 是否被产出满足:用本身,或(点名基础 rr/wrr 时)用其全局变体 grr/gwrr 也算。"""
    if named in actual:
        return True
    g = _GLOBAL_OF.get(named)
    return bool(g and g in actual)


def _actual_save_variants(config_text: str) -> tuple[set, bool]:
    out: set = set()
    seen = False
    for line in (config_text or "").splitlines():
        if _OP_PREFIX_RE.match(line):  # no/show/clear 非生效
            continue
        for m in re.finditer(r"\bwrite\s+(memory|mem|file|all|net)\b", line, re.IGNORECASE):
            out.add("memory" if m.group(1).lower() in ("mem", "memory") else m.group(1).lower())
            seen = True
    return out, seen


def _read_xlsx_apv_config(xlsx_path: "Path") -> str:
    """读产出 xlsx 的 APV 配置命令文本(供保真校验抽实际变体)。"""
    try:
        from openpyxl import load_workbook
        ws = load_workbook(str(xlsx_path), data_only=True).active
    except Exception:
        return ""
    lines = []
    for r in ws.iter_rows(values_only=True):
        if str(r[0] or "").startswith("999"):
            break
        e = str(r[4] or "").strip() if len(r) > 4 else ""
        g = str(r[6] or "") if len(r) > 6 else ""
        if e.startswith("APV"):
            lines.append(g)
    return "\n".join(lines)


def _check_variant_fidelity(case: dict, xlsx_path: "Path") -> str:
    """B 层保真校验:需求点名的变体 vs 产出实际用的变体,偷换/缺配则返回回流反馈(无则空串)。

    数据驱动(非 per-case);需求没点名某维度 → 跳过(no-op,零回归)。每维度三态:
    满足(放行)/ 换族(偷换违规)/ 缺配(点名了但产出没配该类命令,也违规,堵"空配静默放行")。
    全局变体(grr/gwrr)算满足基础 rr/wrr(防误杀正确草稿)。多算法用例 findall 全查(required ⊆ actual)。
    """
    cfg = _read_xlsx_apv_config(xlsx_path)
    viol: list[str] = []

    req_m = _intent_methods(case)
    if req_m:
        actual, seen = _actual_methods(cfg)
        missing = sorted(v for v in req_m if not _method_satisfied(v, actual))
        if missing:
            if seen or actual:
                viol.append(
                    f"算法变体不符:需求点名 {missing} 算法,产出 method 配的是 {sorted(actual) or '识别不出'}。"
                    f"算法以需求为准、别照抄先例——改用 sdns host/pool method … {missing[0]}"
                    f"(查 footprint 拿语法+行为;ga=优先级故障切换非轮转,用 sdns pool member priority 设优先级)。")
            else:
                viol.append(
                    f"算法缺配:需求点名 {missing} 算法,但产出没有任何 sdns host/pool method 配置行"
                    f"(疑漏配或用了非常规语法)。必须显式配 sdns host/pool method … {missing[0]}。")

    sv = _derive_save_variant(case)
    if sv:
        actual, seen = _actual_save_variants(cfg)
        if sv not in actual:
            if seen or actual:
                viol.append(
                    f"保存变体不符:需求点名 write {sv},产出却用了 write {sorted(actual)}。"
                    f"保存命令以需求为准,改回 write {sv} + 同族 config {sv} 恢复。")
            else:
                viol.append(
                    f"保存变体缺配:需求点名 write {sv},但产出没有任何 write 保存命令。"
                    f"显式配 write {sv} + 同族 config {sv} 恢复。")

    return "；".join(viol)


def _build_case_brief(case: dict, *, product_version: str, manual_glob: str,
                      groups: dict, precedent_text: str = "") -> str:
    """从 manifest 的一个 case 机械生成 draft 的五要素 brief（模板，非语义判断）。

    五要素：需求(autoid/title/step_intents) + 现状(模块/版本/分组+组级基线) +
    规则(溯源/不observe-then-assert/自包含) + 指路(先例已预检索内联) + 边界。
    命令/期望值不写进 brief（零硬编码红线）；precedent_text 是**确定性预检索**的已验证先例
    （非硬编码答案，是 qa_lookup_pattern 的客观结构相似召回），内联进来让 draft 少跑检索轮次
    （轨迹缩减：把确定性检索移出 ReAct 轮循环，draft 退化成近单发生成）。
    """
    autoid = str(case.get("autoid", ""))
    title = str(case.get("title", ""))
    group_path = case.get("group_path") or []
    group_str = " / ".join(str(g) for g in group_path)
    steps = case.get("step_intents") or []
    step_lines = []
    for i, s in enumerate(steps, 1):
        desc = str(s.get("desc", "")).strip()
        exp = str(s.get("expected", "")).strip()
        line = f"  {i}. {desc}"
        if exp:
            line += f" → 期望：{exp}"
        step_lines.append(line)
    steps_block = "\n".join(step_lines) if step_lines else "  (脑图未列步骤，按标题推断)"

    # 配置保存/持久化类用例:派生意图变体 + 不重启的 clear→恢复范式引导(命令靠 footprint 现查,不写死)
    save_variant = _derive_save_variant(case)
    persist_block = ""
    if save_variant:
        persist_block = f"""

【本用例是「配置保存/持久化」测试,意图保存变体 = write {save_variant}】绝不真重启设备(共享设备 + 框架不重连)。
用不重启的 clear→恢复 范式(查 footprint config {save_variant} / write {save_variant} 的语法,参考先例 log_backup):
  配 listener → show/found → write {save_variant} <参数>(就用 {save_variant} 这个变体,别换成别的)
  → no sdns listener <ip>(或 clear sdns,先清运行配置)→ config {save_variant} <同参数>(同族恢复)→ show → 断言。
基线 init 里【不要】放任何 write 保存命令(会污染恢复快照)。
调 qa_emit_xlsx 时【必须传 expected_save_variant="{save_variant}"】。"""

    # 算法变体类用例(rr/wrr/ga/…):对冲"先例支配"——算法以需求为准,别照抄先例的算法
    _algos = _intent_methods(case)
    algo = sorted(_algos)[0] if _algos else ""
    algo_block = ""
    if algo:
        algo_block = f"""

【本用例算法 = {algo}】先例可能用的是别的算法(如 wrr),**算法这一项以需求为准,绝不照抄先例的算法**。
配 sdns host/pool method … {algo}(查 footprint「{algo}」拿语法+行为)。注意各算法断言形态不同:
轮询类(rr/wrr)断言轮转命中分布;ga(全局可用性)是优先级故障切换→断言「始终命中最高优先级成员」、
用 sdns pool member priority 设优先级,不是轮转。"""

    return f"""需求：autoid={autoid}，标题={title}
脑图步骤 + 期望：
{steps_block}

现状：目标产品+版本={product_version}；对版本手册 glob={manual_glob}；
本 case 属分组「{group_str}」。同组若有共享基线，纳入本 case 自包含 init。

规则：期望值溯源先例/手册/作者意图，不许 observe-then-assert（不看设备这次输出啥就抄成期望）；
轮询/会话保持类按确定顺序逐次断言不同命中值；每个 case 自包含（init 自建全部前置）。
写不准就留空（绝不编）：期望值离线根本无法定（运行时才产生——dig 轮转解析的具体 IP、Hit/统计计数、
会话/连接保持的具体值、哈希、脚本运行时值）时，**不许凭空编一个值**。优先写部分模式
（前缀溯源手册/先例，只把不可知值槽位留 <RUNTIME>，如 "Hits:\\s*<RUNTIME>"）；连结构都无从溯源
才整值填 <RUNTIME>。这类步标 source.kind=device_runtime（<RUNTIME>⟺device_runtime 自洽，emit 强制）。
真实值由后续 ist_verify_v3 上机回填锁死——draft 只负责诚实留空，不为过机编值。

指路（先例已为你预检索，见下方「预检索先例」）：**优先照预检索先例的完整配置基线改写**——
启用步如 sdns on、数据中心/池法/监听器等基线步一个不能漏（漏了服务不起、dig 零解析、断言全 fail）；
触发(dig 类型/次数)+断言形态照先例配套写。**只有先例里缺的命令**才 qa_footprint_lookup
（你没有手册全文 grep 工具——footprint+先例就是全部命令源；缺的用 qa_probe_show 探设备或推断，绝不空转）。
IP 取下方「本测试床网络事实源」的可达值，绝不照抄示例 IP。
**listener/VIP 选址(dig/curl 必须够得着)**：listener/VIP 的 IP、以及 check 步骤里 dig/curl 的
目标 IP 必须**一致**，且只能取事实源里标 ★ 的「触发设备够得着的 APV 接口 IP」。标 ⚠ 的接口段
没有路由器/客户端(触发源够不着)，配上去上机必不解析、断言全 fail——绝不能用。
{_precedent_block(precedent_text)}{persist_block}{algo_block}

边界：只生成 draft（emit 必须 strict_structural=True + 传 provenance_json），不上机、不自评。"""


def _extract_xlsx_path(fork_output: str, autoid: str, since: float = 0.0) -> Path | None:
    """从 draft fork 的文本输出里定位它产的 case.xlsx（落盘规律 outputs/<autoid>/case.xlsx）。

    **新鲜度校验（治旧草稿污染）**：since>0 时，文件 mtime 必须晚于 since（本次 draft 开工时间），
    否则视作"本轮 draft 没真产出新文件"（沿用了上一轮旧草稿）→ 返回 None，让上层重试/escalate，
    绝不把旧 buggy 草稿当本轮产物合并进去。
    """
    root = _project_root()
    # 落盘规律固定：out_name 默认 autoid
    cand = root / "workspace" / "outputs" / autoid / "case.xlsx"
    if not cand.is_file():
        return None
    if since > 0:
        try:
            if cand.stat().st_mtime < since - 1:   # 容 1s 时钟抖动
                return None
        except OSError:
            return None
    return cand


def _parse_grade_verdict(out: str) -> bool:
    """解析 grade fork 的最终裁定是否 PASS。

    grade 报告会**先讨论** qa_confidence_score 工具给的分（可能含 "CUT"），**再下**自己的
    结论。朴素的 `"PASS" in out and "CUT" not in out` 会把"工具说 CUT 但我判 PASS"误读成
    重做 → 无谓 churn。改为取**最后出现**的裁定词（结论总在末尾），ERROR 一律不通过。
    """
    if not out or out.startswith("ERROR:"):
        return False
    last_pass = out.rfind("PASS")
    last_cut = out.rfind("CUT")
    if last_pass < 0 and last_cut < 0:
        return False          # 两词都没有 → 视为未明确通过
    return last_pass > last_cut


def _run_pipeline(mindmap_path: str, product_version: str, out_name: str,
                  *, draft_skill: str, grade_skill: str) -> dict:
    """确定性跑完 prep→draft→grade→筛→merge。返回结构化结果 dict（不抛，错误进 result）。"""
    from main.ist_core.tools.device.compile_prep import qa_compile_prep
    from main.ist_core.tools.device.batch_tools import qa_compile_fanout
    from main.ist_core.tools.device.emit_xlsx_tool import qa_emit_xlsx_merged
    from main.ist_core.tools.device.precedent_tools import _load_case_rows

    result: dict[str, Any] = {"mindmap": mindmap_path, "out_name": out_name,
                              "phases": [], "errors": []}
    root = _project_root()
    manual_glob = f"{product_version}_cli__part*.md"

    # 1. prep（一次）
    prep_out = qa_compile_prep.invoke({"mindmap_path": mindmap_path, "out_name": out_name})
    manifest_path = root / "workspace" / "outputs" / out_name / "manifest.json"
    if not manifest_path.is_file():
        result["errors"].append(f"prep 未产 manifest: {prep_out[:200]}")
        return result
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = manifest.get("cases", [])
    groups = manifest.get("groups", {})
    result["phases"].append(f"prep: {len(cases)} cases")
    if not cases:
        result["errors"].append("manifest 无 case")
        return result

    # 2. 每 case 独立流水线：draft→grade→(CUT 重做≤N 轮) 串成一个任务，N 个任务并发。
    #    消除 P7 屏障——不再"全部 draft 完才开 grade"；case A 在 grade 时 case B 还能 draft。
    #    并发**自适应**(AIMD)：端点健康缓升、丢连接/限流骤降——替代手动调 IST_FANOUT_CONCURRENCY。
    import time as _time
    from main.ist_core.skills.loader import execute_fork_skill
    from main.ist_core.tools.device.batch_tools import _resolve_concurrency
    from main.ist_core.resilience import AdaptiveLimiter, is_transient_error

    ceiling = _resolve_concurrency(0, n_items=len(cases))   # env 可设上限；默认 auto
    limiter = AdaptiveLimiter(start=max(2, ceiling // 2), min_limit=1, max_limit=ceiling)

    def _fork_call(skill: str, brief: str) -> str:
        """调 fork：遇 transient 端点错误(丢连接/限流/流中断)→降并发+退避重试，非真失败。"""
        last = ""
        for attempt in range(_TRANSIENT_RETRIES + 1):
            out = execute_fork_skill(skill, brief)
            if isinstance(out, str) and out.startswith("ERROR:") and is_transient_error(out):
                limiter.record_overload()
                last = out
                if attempt < _TRANSIENT_RETRIES:
                    _time.sleep(_TRANSIENT_BASE_SLEEP * (2 ** attempt))
                    continue
                return out
            limiter.record_success()
            return out if out is not None else ""
        return last

    def _draft_once(case: dict, aid: str, feedback: str, rnd: int,
                    precedent_text: str = "") -> Path | None:
        brief = _build_case_brief(case, product_version=product_version,
                                  manual_glob=manual_glob, groups=groups,
                                  precedent_text=precedent_text)
        if feedback:
            brief += (f"\n\n重做（第{rnd}轮）：上一版 grade 反馈——{feedback}\n"
                      "基于上一版针对问题改，保留正确部分。")
        t0 = _time.time()                       # 开工时间戳，校验产物新鲜度（治旧草稿污染）
        out = _fork_call(draft_skill, brief)
        if isinstance(out, str) and out.startswith("ERROR:"):
            return None
        return _extract_xlsx_path(out, aid, since=t0)

    def _grade_once(case: dict, aid: str, xp: Path) -> tuple[bool, str]:
        prov = xp.parent / "case.provenance.json"
        intents = case.get("step_intents") or []
        need = "; ".join(f"{s.get('desc','')}→{s.get('expected','')}" for s in intents)
        brief = (f"xlsx_path={xp}\nprovenance_path={prov if prov.exists() else '(无)'}\n"
                 f"原始需求={need}")
        out = _fork_call(grade_skill, brief) or ""
        is_pass = _parse_grade_verdict(out)
        return is_pass, out

    def _compile_one_case(case: dict) -> dict:
        """一个 case 的完整流水线：draft→grade，CUT 带反馈重做≤N 轮。返回终态。

        用自适应限流器 acquire/release 闸住并发——名额随端点健康自动伸缩。
        """
        aid = str(case["autoid"])
        precedent_text = _preretrieve_precedent(case)   # 确定性预检索一次（轨迹缩减）
        with limiter:                       # 阻塞直到有名额（名额数=当前自适应 limit）
            feedback = ""
            for rnd in range(_MAX_REWORK_ROUNDS):
                xp = _draft_once(case, aid, feedback, rnd, precedent_text)
                if xp is None:
                    feedback = "draft 未产出 xlsx（生成失败），重试"
                    continue
                # B 层保真:需求点名的变体(算法/保存)不许偷换;违规当回流反馈重做
                vfb = _check_variant_fidelity(case, xp)
                if vfb:
                    feedback = vfb
                    continue
                ok, gout = _grade_once(case, aid, xp)
                if ok:
                    return {"autoid": aid, "case": case, "xlsx": xp, "state": "done"}
                feedback = gout[:600]
            return {"autoid": aid, "case": case,
                    "state": "escalated", "reason": (feedback[:200] or "连续重做仍未通过")}

    result["phases"].append(
        f"per-case pipeline: {len(cases)} cases, 自适应并发(start={limiter.current} max={ceiling})")
    done: dict[str, dict] = {}
    escalated: dict[str, str] = {}
    import concurrent.futures as _cf
    # 线程池开到上限；实际并发由 limiter 闸住（阻塞在 acquire），随端点健康自适应。
    with _cf.ThreadPoolExecutor(max_workers=ceiling) as ex:
        futs = {ex.submit(_compile_one_case, c): str(c["autoid"]) for c in cases}
        for fut in _cf.as_completed(futs):
            aid = futs[fut]
            try:
                r = fut.result()
            except Exception as e:  # noqa: BLE001
                escalated[aid] = f"流水线异常: {e}"
                continue
            if r["state"] == "done":
                done[r["autoid"]] = {"case": r["case"], "xlsx": r["xlsx"]}
            else:
                escalated[r["autoid"]] = r.get("reason", "")
    if limiter.history:
        result["phases"].append(f"并发自适应轨迹: {' '.join(limiter.history[-12:])} (终值={limiter.current})")

    result["done"] = list(done.keys())
    result["escalated"] = escalated

    # 3. merge（一次，把 done 的 case 读回 steps 合并）
    if done:
        merged_cases = []
        for aid, info in done.items():
            try:
                rows = _load_case_rows(str(info["xlsx"]))
            except Exception as e:  # noqa: BLE001
                result["errors"].append(f"{aid} 读回 steps 失败: {e}")
                continue
            # init = 首个 APV cmds_config（_load_case_rows 不含 init 行，留空让 merge 用默认）
            merged_cases.append({"autoid": aid, "title": info["case"].get("title", ""),
                                 "steps": rows})
        if merged_cases:
            merge_out = qa_emit_xlsx_merged.invoke(
                {"cases_json": json.dumps(merged_cases, ensure_ascii=False), "out_name": out_name})
            result["phases"].append(f"merge: {len(merged_cases)} cases → {out_name}/case.xlsx")
            result["merge_output"] = merge_out[:300]
    return result


@tool(parse_docstring=True)
def qa_compile_pipeline(mindmap_path: str, product_version: str, out_name: str = "") -> str:
    """【确定性编译流水线】一次跑完一个脑图的 prep→draft→grade→筛→合并，产出 case.xlsx。

    把固定编译序列锁在工具内部——你只调这一次，不要自己逐步调 qa_compile_prep /
    qa_compile_fanout / qa_emit_xlsx_merged（那会让序列失控：prep 重复、fanout 多发、误调别的 skill）。
    工具内部固定：解析 manifest → 每个 case 独立流水线(draft 产 provenance → grade 验 provenance
    → CUT 带反馈重做≤3 轮)，N 个 case 并发且无屏障(case A 在 grade 时 case B 还能 draft，
    不必等全部 draft 完才开 grade) → grade-PASS 合并成一个 excel。命令/断言全由 draft fork
    现场查（零硬编码），自由度在 fork 内不在编排层。

    不上机（上机走 ist_verify_v3 独立环节）。多脑图请逐个调本工具（每脑图一次）。

    Args:
        mindmap_path: 脑图 txt 路径。
        product_version: 产品版本（如 "10.5"），决定查哪个版本手册。从用户请求提取，缺失则先问用户。
        out_name: 输出子目录名（workspace/outputs/<out_name>/case.xlsx），默认用脑图文件名。

    Returns:
        结构化结果：各阶段进度、done/escalated 的 autoid、合并 excel 路径。
    """
    mp = (mindmap_path or "").strip()
    if not mp:
        return "error: 必须提供 mindmap_path"
    ver = (product_version or "").strip()
    if not ver:
        return "error: 必须提供 product_version（如 10.5）——版本决定查哪个手册，不可臆测，缺失请先 qa_ask_user 问用户"
    if not out_name:
        out_name = Path(mp).stem
    out_name = out_name.strip().replace("/", "_")

    try:
        result = _run_pipeline(mp, ver, out_name,
                               draft_skill="ist_draft_v3", grade_skill="ist_grade_v3")
    except Exception as e:  # noqa: BLE001
        logger.exception("compile_pipeline 失败")
        return f"error: 流水线异常: {e}"

    lines = [f"=== qa_compile_pipeline: {out_name} ==="]
    lines += [f"  {p}" for p in result.get("phases", [])]
    lines.append(f"done: {len(result.get('done', []))} cases")
    if result.get("escalated"):
        lines.append(f"escalated(N轮CUT未过): {len(result['escalated'])} — {list(result['escalated'].keys())}")
    if result.get("errors"):
        lines.append(f"errors: {result['errors']}")
    if result.get("merge_output"):
        lines.append(f"产出: workspace/outputs/{out_name}/case.xlsx")
    return "\n".join(lines)

