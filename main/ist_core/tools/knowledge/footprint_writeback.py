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
    """Write a verified case's G-segment command grammar back into the footprint knowledge
    tree (true-PASS self-evolution).

    Used by verify step 7: call it for each case that **truly PASSed** on device (framework
    pass and assertions genuinely cover the target behavior). It reads the case's provenance
    and writes the G segment (cli_command) back through the evidence gate. **G segment only**
    — V-segment assertions / E-segment concrete IPs / backfilled runtime values are never
    written back (environment state would pollute the footprint). Missing or unparseable
    provenance is skipped, not an error.

    Args:
        autoid: This case's autoid (for reporting; the actual writeback source is the
            per-step layer/source inside the provenance).
        provenance_path: Path to this case's `case.provenance.json` (draft v3 side product).
        on_device_passed: True = truly PASSed on device (provisional=False, official
            writeback); False = structural gates + grade proxy gate only (provisional=True).
        manual_glob: Optional version-manual glob, used as an evidence_file fallback so merge
            validation can hit.

    Returns:
        Writeback summary: written / skipped counts plus details. Missing provenance or no
        G segment is reported as-is, not an error.
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
        return f"writeback skipped: failed to read provenance ({e}) — attribution degraded, nothing written."

    prov = parse_provenance(text)
    if prov is None:
        return f"writeback skipped: failed to parse provenance (autoid={autoid}) — nothing written."

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
                        if rec.get("build"):   # K 锚 build 位透传(理论 §5.1)
                            device_run_ref["build"] = str(rec["build"])
        except Exception:  # noqa: BLE001
            device_run_ref = None

    try:
        res = writeback_verified_case(
            prov, KNOWLEDGE_FOOTPRINTS,
            manual_glob=manual_glob, on_device_passed=on_device_passed,
            device_run_ref=device_run_ref,
        )
    except Exception as e:  # noqa: BLE001
        return f"error: writeback failed (autoid={autoid}): {e}"

    tag = "true-PASS (official)" if on_device_passed else "proxy-gate (provisional)"
    lines = [
        f"footprint writeback autoid={prov.autoid} [{tag}]: "
        f"G facts written {res.g_facts_written} / skipped {res.g_facts_skipped}"
        + (f" ({res.g_facts_device_verified} device-verified)" if res.g_facts_device_verified else "")
    ]
    for d in res.details[:12]:
        lines.append(f"  {d}")
    return "\n".join(lines)
