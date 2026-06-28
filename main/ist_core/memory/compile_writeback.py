"""闭环写回（V3 步骤4，论文 §3.14 定理3.22：扩库推高 ρ_k 把 G/E 段错误驱向本征下限）。

把**已验证**（上机 PASS，或本轮代理门：结构门通过 + grade PASS）的 case 的
Provenance IR 里的 G 段事实写回 footprint——ρ_k 随编译单调上升，第 N 个同族 case
比第 1 个便宜。这是 V3 的灵魂：fork 从无状态冷函数变成自演化。

复用现成安全闸（不新建）：
- footprint.merger.merge_fact()：evidence_quote 必须在 evidence_file 真实命中否则 skip
  → 写回不会注入幻觉文法（draft 标的 source.ref 对不上手册就被挡）。
- 整 case 追加先例库：写 mirror xlsx 目录 + 触发 intent_index 重建（懒，下次 lookup 生效）。

红线（§3.7ter）：只写回**已验证的 G/E 段事实**（命令文法/可达 IP 这类确定性可复用的），
**绝不写回 V 段业务断言或"意图→命令映射规则"**——那是 H_G/H_V'，写回它=把语义决策
固化成硬编码，重蹈被删的纯代码管线。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from main.case_compiler.provenance_ir import CaseProvenance
from main.ist_core.memory.footprint.schema import RawFact

logger = logging.getLogger(__name__)


@dataclass
class WritebackResult:
    """一次写回的结果汇总，供编排器/日志观测 ρ_k 增长。"""
    case_autoid: str
    provisional: bool = True
    g_facts_written: int = 0
    g_facts_skipped: int = 0
    precedent_appended: bool = False
    details: list[str] = field(default_factory=list)

    def summary(self) -> str:
        tag = "代理门(未上机)" if self.provisional else "上机PASS"
        return (f"写回[{self.case_autoid}/{tag}]: G段事实 写{self.g_facts_written}/"
                f"跳{self.g_facts_skipped}, 先例追加={'是' if self.precedent_appended else '否'}")


def _g_step_to_rawfact(step, autoid: str, manual_glob: str) -> RawFact | None:
    """把一个 G 层 provenance step 转成 cli_command RawFact（供 merge_fact 写回）。

    只处理 source.kind in (footprint, manual, skeleton) 且 G 是配置命令的步骤。
    evidence_file/quote 取 source.ref——merge_fact 会校验 quote 在 file 真实命中，
    对不上则 skip（这是防幻觉的关键，不在这里自己判）。
    """
    if step.layer != "G":
        return None
    if step.E not in ("APV_0",) or step.F not in ("cmd_config", "cmds_config"):
        return None
    cmd = (step.G or "").strip()
    if not cmd:
        return None
    # feature_path：取命令头 token 作为特征路径（与 footprint 节点命名一致）
    head = cmd.split()
    feature_path = head[:2] if len(head) >= 2 else head[:1]
    if not feature_path:
        return None
    ref = step.source.ref or ""
    # evidence：footprint/skeleton 类用命令原文作 quote（merge 会在手册里找）；
    # manual 类 ref 形如 "cli_10.5_Chapter11:1234"，evidence_file 取文件名部分。
    evidence_file = ""
    if step.source.kind == "manual" and ":" in ref:
        evidence_file = ref.split(":", 1)[0]
    elif manual_glob:
        evidence_file = manual_glob
    return RawFact(
        fact_kind="cli_command",
        feature_path=list(feature_path),
        fact_key=cmd,
        cli_syntax=cmd,
        evidence_file=evidence_file,
        evidence_quote=cmd,
        source_thread=f"compile_writeback:{autoid}",
    )


def writeback_verified_case(
    provenance: CaseProvenance,
    footprint_dir: Path | str,
    *,
    manual_glob: str = "",
    on_device_passed: bool = False,
    append_precedent=None,
) -> WritebackResult:
    """把已验证 case 的 G 段事实写回 footprint（+ 可选先例追加）。

    provenance: draft 产的 CaseProvenance（含逐步 layer/source）。
    footprint_dir: footprint 根目录。
    manual_glob: 对版本手册 glob（作 evidence_file 兜底，供 merge_fact 校验命中）。
    on_device_passed: True=上机真 PASS（provisional=False）；False=本轮代理门
        （结构门+grade PASS，provisional=True）。两者都写回，但标记不同。
    append_precedent: 可选回调 (provenance)->bool，把整 case 追加进先例库（解耦，便于测试）。

    红线：只写回 G 段（cli_command）。V 段断言/E 段具体 IP 不写回 footprint
    （IP 是环境态会变；V 是业务语义不可固化）。
    """
    from main.ist_core.memory.footprint.router import route_facts
    from main.ist_core.memory.footprint.merger import merge_fact

    fdir = Path(footprint_dir)
    result = WritebackResult(case_autoid=provenance.autoid,
                             provisional=not on_device_passed)

    rawfacts = []
    for step in provenance.layer_steps("G"):
        rf = _g_step_to_rawfact(step, provenance.autoid, manual_glob)
        if rf is not None:
            rawfacts.append(rf)

    if rawfacts:
        try:
            routed_list = route_facts(rawfacts, fdir)
        except Exception as e:  # noqa: BLE001
            routed_list = []
            result.details.append(f"路由失败: {e}")
        for routed in routed_list:
            try:
                mres = merge_fact(routed, fdir)
                if mres.action == "skip":
                    result.g_facts_skipped += 1
                    result.details.append(f"✗ {routed.fact.fact_key[:40]} skip: {mres.detail}")
                else:
                    result.g_facts_written += 1
                    result.details.append(f"✓ {routed.fact.fact_key[:40]} → {mres.action}")
            except Exception as e:  # noqa: BLE001
                result.g_facts_skipped += 1
                result.details.append(f"✗ {routed.fact.fact_key[:40]} error: {e}")

    if append_precedent is not None:
        try:
            result.precedent_appended = bool(append_precedent(provenance))
        except Exception as e:  # noqa: BLE001
            result.details.append(f"先例追加失败: {e}")

    logger.info(result.summary())
    return result
