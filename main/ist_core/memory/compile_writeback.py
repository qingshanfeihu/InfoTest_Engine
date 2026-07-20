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


def _strip_executor_kwargs(cmd: str) -> str:
    """剥掉 G 段命令尾部的**框架执行器 kwarg**,返回纯 CLI 语法部分。

    `ssl activate certificate vh1,prompt=YES` 里的 `,prompt=YES` 不是设备 CLI 语法,
    是 xlsx 执行器的具名参数(mirror `lib/test_xlsx.py::get_parameter`)。原样写进
    footprint 的 cli.commands 后,worker 检索会读成「这条命令的语法含 prompt 参数」
    ——知识树被交付流程持续污染(gap② 现象,ssl.activate 实证)。

    判据**机械推导自 get_parameter 语义**,不建 {prompt,timeout} 键名白名单:该键集随
    框架版本增长,白名单会漏判(参考文档只写机制、数据按引用)。切法复用 structural_gate
    的引号外逗号正则(test_xlsx.py:57 原样复刻),勿另写第三份——两路切法漂移正是
    缺口①的成因。get_parameter 对 `key=value` 段的 kwarg 判据是「`=` 左侧无空格」
    (test_xlsx.py:71-77:含空格则退回位置参),这里照搬。
    """
    from main.ist_core.tools.device.structural_gate import _PARAM_SPLIT_RE
    raw = str(cmd or "")
    if "\n" in raw or "," not in raw:
        return raw.strip()   # 含真实换行时框架整段单参(不切),无 kwarg 可言
    segs = [p.strip() for p in _PARAM_SPLIT_RE.findall(raw) if p.strip()]
    if not segs:
        return raw.strip()
    kept = [segs[0]]
    for seg in segs[1:]:
        if "=" in seg:
            key = seg.split("=", 1)[0].strip()
            # get_parameter:键无空格 ∧ 是标识符 → 具名参数;否则仍是位置参(属命令)
            if key and " " not in key and key.replace("_", "").isalnum() \
                    and not key[0].isdigit():
                continue   # 执行器 kwarg,剥除
        kept.append(seg)
    return ",".join(kept).strip()


@dataclass
class WritebackResult:
    """一次写回的结果汇总，供编排器/日志观测 ρ_k 增长。"""
    case_autoid: str
    provisional: bool = True
    g_facts_written: int = 0
    g_facts_skipped: int = 0
    g_facts_device_verified: int = 0   # 经 device_verified 第二权威源写入的条数(⊆ written)
    precedent_appended: bool = False
    details: list[str] = field(default_factory=list)

    def summary(self) -> str:
        tag = "代理门(未上机)" if self.provisional else "上机PASS"
        return (f"写回[{self.case_autoid}/{tag}]: G段事实 写{self.g_facts_written}/"
                f"跳{self.g_facts_skipped}, 先例追加={'是' if self.precedent_appended else '否'}")


def _g_step_to_rawfacts(step, autoid: str, manual_glob: str) -> list[RawFact]:
    """把一个 G 层 provenance step 转成 cli_command RawFact 列表（供 merge_fact 写回）。

    收 E∈{APV_0, APV_1}(双机原生槽)且 F∈{cmd_config, cmds_config} 的命令步;
    **cmds_config 多行逐条拆**——旧版整段多行文本当一条 fact_key,手册永远命不中、
    也和 footprint 单命令节点对不上(V6 支柱2a 取证:写回候选缺失的一半)。
    footprint/skeleton/emit_auto:命令原文作 quote,evidence_file 取 manual_glob;
    manual:ref 形如 "cli_10.5_Chapter11:1234",取文件名部分。evidence 对不上则
    merge skip(防幻觉,不在这里自己判)。
    """
    if step.layer != "G":
        return []
    if step.E not in ("APV_0", "APV_1") or step.F not in ("cmd_config", "cmds_config"):
        return []
    ref = step.source.ref or ""
    evidence_file = ""
    if step.source.kind == "manual" and ":" in ref:
        evidence_file = ref.split(":", 1)[0]
    elif manual_glob:
        evidence_file = manual_glob
    out: list[RawFact] = []
    for raw_cmd in (step.G or "").splitlines():
        raw_cmd = raw_cmd.strip()
        if not raw_cmd:
            continue
        # 语法位剥执行器 kwarg;**原文另存 evidence_quote**,审计要回溯「设备上实际
        # 发的是什么」时不丢(gap② S1)。
        cmd = _strip_executor_kwargs(raw_cmd)
        if not cmd:
            continue
        # feature_path 与 footprint 命名约定对齐:剥操作前缀(no/show/clear)再取
        # 命令主体 token——否则 show 类观测命令落 show.* 节点,与配置命令的
        # statistics.*/sdns.* 树分裂,行为知识和文法散在两处(2026-07-06 实证)。
        toks = [w for w in cmd.split() if w.lower() not in ("no", "show", "clear")]
        head = toks or cmd.split()
        feature_path = head[:2] if len(head) >= 2 else head[:1]
        if not feature_path:
            continue
        out.append(RawFact(
            fact_kind="cli_command",
            feature_path=list(feature_path),
            fact_key=cmd,
            cli_syntax=cmd,
            evidence_file=evidence_file,
            evidence_quote=cmd,      # 门的针:剥净后更易在手册命中(原文含 kwarg 恒不中)
            raw_invocation=raw_cmd,  # 设备实发原文,审计回溯用
            source_thread=f"compile_writeback:{autoid}",
        ))
    return out


def writeback_verified_case(
    provenance: CaseProvenance,
    footprint_dir: Path | str,
    *,
    manual_glob: str = "",
    on_device_passed: bool = False,
    append_precedent=None,
    device_run_ref: dict | None = None,
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
        rawfacts.extend(_g_step_to_rawfacts(step, provenance.autoid, manual_glob))
    # 去重(拆行后同命令可能重复出现;fact_key=命令原文)
    _seen: set[str] = set()
    rawfacts = [rf for rf in rawfacts if not (rf.fact_key in _seen or _seen.add(rf.fact_key))]

    if rawfacts:
        try:
            routed_list = route_facts(rawfacts, fdir)
        except Exception as e:  # noqa: BLE001
            routed_list = []
            result.details.append(f"路由失败: {e}")
        for routed in routed_list:
            try:
                mres = merge_fact(routed, fdir)
                if (mres.action == "skip" and on_device_passed and device_run_ref
                        and "evidence" in str(mres.detail)):
                    # 第二权威源降级重试(V6 支柱2a):手册 evidence 不中(运行时命令
                    # 不在 CLI 手册——v12 实证 28/28 skip 的根因),而该 case 上机真
                    # PASS——用 device_verified 台账重试一次,门在 merger 侧三重校验。
                    routed.fact.device_evidence = dict(device_run_ref)
                    mres = merge_fact(routed, fdir)
                    if mres.action != "skip":
                        result.g_facts_device_verified += 1
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
