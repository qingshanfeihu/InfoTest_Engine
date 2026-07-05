"""E6 双跑实验(V6 步骤0):同一合并卷连跑 2 次,逐 autoid diff verdict。

目的:E3 归档数据里的 5 例 pass→fail→pass 翻转混杂了重编版本,判不了"运行时欠定"
是否真实存在。本实验控制变量:同一份 xlsx(mtime 断言不变)、隔离目录(digest 的
last_run/.frozen 副作用不污染生产卷)、背靠背两跑。

判读(写死,防实验后再议):
- flips >= 1 → 运行时欠定实证存在 → 引擎接 DOUBLE_RUN_JUDGE 分支(V6 支柱4);
- flips == 0 → 全稳定 → 不接入,枚举模型维持唯一欠定粗筛,E3 五例定性为重编版本混杂。

用法:
    python -m scripts.debug.double_run_experiment <merged_xlsx> [--name tag]
产出:
    runtime/logs/double_run_report.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from main.langchain_env import langchain_load_dotenv_if_present  # noqa: E402

langchain_load_dotenv_if_present()


def _load_verdicts(last_run: Path) -> dict[str, dict]:
    data = json.loads(last_run.read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else data.get("results", [])
    out = {}
    for it in items:
        aid = str(it.get("autoid", ""))
        if aid:
            out[aid] = {"verdict": str(it.get("verdict", "?")),
                        "sigs": it.get("_fail_signatures") or []}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx", help="已合并整卷 case.xlsx 路径")
    ap.add_argument("--name", default="e6", help="实验目录后缀")
    ap.add_argument("--max-s", type=int, default=0, help="单跑超时(0=工具自适应)")
    args = ap.parse_args()

    src = Path(args.xlsx)
    if not src.is_absolute():
        src = _ROOT / src
    if not src.is_file():
        print(f"error: 卷不存在 {src}")
        return 2

    # 隔离目录:digest 的 last_run.json/.frozen.json 副作用全落这里,不碰生产卷
    exp_dir = _ROOT / "workspace" / "outputs" / f"_doublerun_{args.name}"
    shutil.rmtree(exp_dir, ignore_errors=True)
    exp_dir.mkdir(parents=True)
    xlsx = exp_dir / "case.xlsx"
    shutil.copy2(src, xlsx)
    mtime0 = xlsx.stat().st_mtime
    print(f"实验卷: {xlsx}(源 {src},mtime={mtime0})")

    from main.ist_core.tools.device.batch_tools import dev_run_batch_digest

    runs: list[dict[str, dict]] = []
    for i in (1, 2):
        assert abs(xlsx.stat().st_mtime - mtime0) < 1e-6, "卷面 mtime 变了——实验作废"
        print(f"== 第 {i} 跑开始 {time.strftime('%H:%M:%S')}")
        for attempt in range(6):
            out = dev_run_batch_digest.func(str(xlsx), max_s_each=args.max_s) if args.max_s \
                else dev_run_batch_digest.func(str(xlsx))
            if "run_in_progress" in out or "device_busy" in out:
                print(f"   设备忙,120s 后重试({attempt + 1}/6)")
                time.sleep(120)
                continue
            break
        lr = exp_dir / "last_run.json"
        if not lr.is_file():
            print("error: last_run.json 未产出——digest 失败,摘要尾部:")
            print(out[-600:])
            return 3
        verdicts = _load_verdicts(lr)
        runs.append(verdicts)
        shutil.copy2(lr, exp_dir / f"run{i}.json")
        n_pass = sum(1 for v in verdicts.values() if v["verdict"] == "pass")
        print(f"== 第 {i} 跑完成: {n_pass}/{len(verdicts)} pass")

    r1, r2 = runs
    aids = sorted(set(r1) | set(r2))
    stable_pass, stable_fail, flips = [], [], []
    for a in aids:
        v1 = r1.get(a, {}).get("verdict", "missing")
        v2 = r2.get(a, {}).get("verdict", "missing")
        if v1 == v2 == "pass":
            stable_pass.append(a)
        elif v1 == v2:
            stable_fail.append({"autoid": a, "verdict": v1,
                                "sig_overlap": sorted(set(map(str, r1.get(a, {}).get("sigs", [])))
                                                      & set(map(str, r2.get(a, {}).get("sigs", []))))})
        else:
            flips.append({"autoid": a, "r1": v1, "r2": v2})

    report = {
        "xlsx": str(src), "n": len(aids), "run_ts": time.time(),
        "stable_pass": len(stable_pass),
        "stable_fail": stable_fail,
        "flips": flips,
        "verdict": ("接入 DOUBLE_RUN_JUDGE(存在运行时欠定)" if flips
                    else "不接入(全稳定;E3 翻转定性为重编版本混杂)"),
    }
    rp = _ROOT / "runtime" / "logs" / "double_run_report.json"
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== E6 结论: flips={len(flips)} stable_fail={len(stable_fail)} "
          f"stable_pass={len(stable_pass)} → {report['verdict']}")
    print(f"报告: {rp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
