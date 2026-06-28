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
    last_obs_idx = None     # 最近一个产出回显的观测步（show/dig/...）
    for i, row in enumerate(rows):
        e = (row.get("E") or "").strip()
        g = (row.get("G") or "").strip()
        if e != "check_point":
            if e.startswith("APV") and g:        # APV 配置/动作命令，累进被测命令链
                for line in g.split("\n"):
                    if line.strip():
                        config_so_far.append(line.strip())
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

        suspect = layer_mismatch or query_object_invalid or spec_conflict_suspect
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

    suspect_count = sum(1 for c in check_points if c["suspect"]) + (1 if weak_v_coverage_suspect else 0)

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
