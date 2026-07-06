"""compile_footprint_writeback: 把上机真 PASS case 的 G 段文法写回 footprint（自演化 ρ_k）。

verify 子流程步7：对每个**真 PASS**（框架 pass + 断言真覆盖行为）的 case，读它的 provenance，
把 **G 段命令文法**写回 footprint 知识树。evidence 门防幻觉、只写 G 段——V 段断言 / E 段具体 IP /
回填的运行时值**不写**（环境态，进 footprint 会污染）。footprint 越饱，下次同类 draft 越少啃手册。

这是 `memory/compile_writeback.py::writeback_verified_case` 的 @tool 薄包装：从 provenance_path
加载 `CaseProvenance` + 定位 footprint 根（`KNOWLEDGE_FOOTPRINTS`），其余逻辑（route_facts→
merge_fact evidence 门、只写 G 段的红线）全复用它，不在这里重造。
"""

from __future__ import annotations

from langchain_core.tools import tool


@tool(parse_docstring=True)
def compile_footprint_writeback(autoid: str, provenance_path: str,
                                on_device_passed: bool = True,
                                manual_glob: str = "") -> str:
    """把一个已验证 case 的 G 段命令文法写回 footprint 知识树（真 PASS 自演化）。

    verify 步7 用：对上机**真 PASS**的 case（框架 pass 且断言真覆盖目标行为）调它，读该 case 的
    provenance、把 G 段（cli_command）经 evidence 门写回 footprint。**只写 G 段**——V 段断言 /
    E 段具体 IP / 回填的运行时值不写回（环境态会污染 footprint）。provenance 缺失/解析失败则跳过、不报错。

    Args:
        autoid: 该 case 的 autoid（用于报告；实际写回来源是 provenance 内的逐步 layer/source）。
        provenance_path: 该 case 的 `case.provenance.json` 路径（draft v3 旁挂产物）。
        on_device_passed: True=上机真 PASS（provisional=False，正式写回）；False=仅结构门+grade 代理门（provisional=True）。
        manual_glob: 可选，版本手册 glob，作 evidence_file 兜底供 merge 校验命中。

    Returns:
        写回汇总：写入 / 跳过条数 + 明细。provenance 缺失 / 无 G 段则如实报告、不报错。
    """
    from pathlib import Path
    from main.case_compiler.provenance_ir import parse_provenance
    from main.ist_core.memory.compile_writeback import writeback_verified_case
    from main.knowledge_paths import KNOWLEDGE_FOOTPRINTS

    # provenance 读取走 fs_read 同款沙箱解析（防越界）
    try:
        from main.ist_core.tools.deepagent.file_tools import _resolve_inside_root
        p = _resolve_inside_root(provenance_path, must_exist=True)
        text = Path(p).read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return f"跳过写回：provenance 读取失败（{e}）——归因已退化，不写回。"

    prov = parse_provenance(text)
    if prov is None:
        return f"跳过写回：provenance 解析失败（autoid={autoid}）——不写回。"

    # device_verified 第二权威源(V6 支柱2a):上机真 PASS 时,从 verified_runs.jsonl
    # 台账定位该 autoid 最近一条 PASS 记录——手册 evidence 不中的运行时命令
    # (v12 实证 28/28 skip 的根因)经它降级重试,门在 merger 侧三重校验。
    device_run_ref = None
    if on_device_passed:
        try:
            import json as _json
            ledger = Path(__file__).resolve().parents[4] / "runtime" / "logs" / "verified_runs.jsonl"
            if ledger.is_file():
                for line in ledger.read_text(encoding="utf-8", errors="ignore").splitlines():
                    try:
                        rec = _json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
                    if str(rec.get("autoid")) == (autoid or "").strip() and str(rec.get("verdict")) == "pass":
                        device_run_ref = {"autoid": str(rec["autoid"]), "run_ts": rec.get("run_ts")}
        except Exception:  # noqa: BLE001
            device_run_ref = None

    try:
        res = writeback_verified_case(
            prov, KNOWLEDGE_FOOTPRINTS,
            manual_glob=manual_glob, on_device_passed=on_device_passed,
            device_run_ref=device_run_ref,
        )
    except Exception as e:  # noqa: BLE001
        return f"写回异常（autoid={autoid}）：{e}"

    tag = "真PASS(正式)" if on_device_passed else "代理门(provisional)"
    lines = [
        f"footprint 写回 autoid={prov.autoid} [{tag}]："
        f"G 段写入 {res.g_facts_written} / 跳过 {res.g_facts_skipped}"
        + (f"(其中设备实证 {res.g_facts_device_verified})" if res.g_facts_device_verified else "")
    ]
    for d in res.details[:12]:
        lines.append(f"  {d}")
    return "\n".join(lines)
