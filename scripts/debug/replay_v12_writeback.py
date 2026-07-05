"""v12 写回重放门(V6 支柱2a 验收):用归档 PASS 卷构造 device_verified 台账,
重放当年 28/28 skip 的 footprint 写回 → 断言 skip 大幅下降且零幻觉。

写入落临时目录(dry-run),不碰生产 footprint。exit 0=门过。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from main.case_compiler.provenance_ir import parse_provenance  # noqa: E402
from main.ist_core.memory.compile_writeback import writeback_verified_case  # noqa: E402
from main.ist_core.tools.device.batch_tools import _xlsx_apv_lines  # noqa: E402
from main.ist_core.memory.footprint import merger as M  # noqa: E402

ARCH = _ROOT / "workspace" / "outputs" / "_archive_v12_20260705"


def main() -> int:
    lr = json.loads((ARCH / "dongkl_v12" / "last_run.json").read_text(encoding="utf-8"))
    items = lr if isinstance(lr, list) else lr.get("results", [])
    passed = {str(it["autoid"]) for it in items if str(it.get("verdict")) == "pass"}
    print(f"归档真 PASS: {len(passed)} case")

    apv = _xlsx_apv_lines(ARCH / "dongkl_v12" / "case.xlsx")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        # 临时台账 + 临时 footprint(重放隔离)
        led = tmp / "runtime" / "logs" / "verified_runs.jsonl"
        led.parent.mkdir(parents=True)
        run_ts = 1000.0
        with led.open("w", encoding="utf-8") as f:
            for aid in passed:
                f.write(json.dumps({"autoid": aid, "verdict": "pass", "run_ts": run_ts,
                                    "apv_cmds": apv.get(aid, [])}, ensure_ascii=False) + "\n")
        M._project_root = lambda: tmp   # 台账根重定向(与测试同法)
        fdir = tmp / "footprints"

        total_w = total_s = total_dev = n_cases = 0
        skip_reasons: dict[str, int] = {}
        for aid in sorted(passed):
            pv_path = ARCH / aid / "case.provenance.json"
            if not pv_path.is_file():
                continue
            prov = parse_provenance(pv_path.read_text(encoding="utf-8"))
            if prov is None:
                continue
            n_cases += 1
            res = writeback_verified_case(
                prov, fdir, manual_glob="10.5_cli__part1.md", on_device_passed=True,
                device_run_ref={"autoid": aid, "run_ts": run_ts})
            total_w += res.g_facts_written
            total_s += res.g_facts_skipped
            total_dev += res.g_facts_device_verified
            for d in res.details:
                if "skip:" in d:
                    key = d.split("skip:", 1)[1].strip()[:40]
                    skip_reasons[key] = skip_reasons.get(key, 0) + 1

        print(f"重放 {n_cases} case: 写入 {total_w}(其中设备实证 {total_dev}) / 跳过 {total_s}")
        evidence_skips = 0
        for k, v in sorted(skip_reasons.items(), key=lambda x: -x[1]):
            print(f"  skip[{v}] {k}")
            if "evidence" in k:
                evidence_skips += v

        # 零幻觉复核:写进临时 footprint 的每条 cli_syntax 必须在某 PASS 卷面命令里
        all_cmds = {c for aid in passed for c in apv.get(aid, [])}
        halluc = []
        for node in fdir.rglob("*.json"):
            data = json.loads(node.read_text(encoding="utf-8"))
            for c in data.get("cli", {}).get("commands", []) if isinstance(data.get("cli"), dict) else []:
                syntax = c.get("syntax", "") if isinstance(c, dict) else str(c)
                if syntax and syntax not in all_cmds:
                    halluc.append(syntax)
        print(f"幻觉复核: {len(halluc)} 条不在卷面 {halluc[:3]}")

        # 门口径:evidence 类 skip(v12 的 28/28 根因)必须 ≤8;duplicate 类 skip=
        # 知识已在库,是健康去重不计入门。
        ok = evidence_skips <= 8 and not halluc and total_w > 0
        print(f"\n门判定: evidence_skip={evidence_skips}(≤8?) 幻觉={len(halluc)}(==0?) "
              f"写入={total_w}(>0?) → {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
