"""分布区间断言 eval（确定性、可复现）——把「算法类断言形态」回归固化成机读断言。

呼应 CLAUDE.md「改 prompt 前先有 eval」：扫已编译的 case.xlsx，对每个跑 grade_extract，按它产出
的分布信号机读分类（复用 grade_extract 单一事实源，免两套判据漂移）：

- GOOD_DIST       : 配了分布算法(rr/wrr) 且产出了分布区间断言（守恒区间，达标形态）
- BAD_TAUTOLOGY   : 配了分布算法 但断言写成无界 `Hit:\\s+\\d+`（任意数都过=恒真，旧 prompt 的回归）
- BAD_GAP         : 配了分布算法 但既无分布区间断言、也无关系断言（漏测分布，dongkl WEAK_no_count 类）
- REL_OK          : 配了分布算法 但用关系断言（H 捕获）覆盖（如 rr 上的会话保持，合法）
- SKIP            : 非分布算法（ga/一致性哈希/会话保持/无算法），不在本 eval 范围

用法::

    # 扫一个 outputs 根目录，打印分类汇总 + 逐 case
    python -m scripts.debug.eval_distribution_assertions [outputs根目录]

    # 改 prompt 前存基线，改后对比（BAD_* 应降、GOOD_DIST 应升）
    python -m scripts.debug.eval_distribution_assertions <dir> --baseline runtime/logs/dist_eval_base.json
    python -m scripts.debug.eval_distribution_assertions <dir> --compare  runtime/logs/dist_eval_base.json

默认根目录 workspace/outputs。退出码：有 BAD_* 时 exit 1（可作 CI gate），全干净 exit 0。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from main.ist_core.skills.ist_compile_grade.scripts.grade_extract import extract


def classify(ext: dict) -> str:
    """据 grade_extract 信号机读分类一个 case。"""
    if not ext.get("has_distribution_method"):
        return "SKIP"
    if ext.get("has_distribution_assertion"):
        return "GOOD_DIST"
    if ext.get("count_tautology_count", 0) > 0:
        return "BAD_TAUTOLOGY"
    if ext.get("distribution_coverage_gap_suspect"):
        return "BAD_GAP"
    # 配了分布算法、无分布区间断言、无恒真 Hit，但有关系断言（rr 上会话保持等）→ 合法
    if any(c.get("cp_h") for c in ext.get("check_points", [])):
        return "REL_OK"
    return "BAD_GAP"


def _find_cases(root: Path) -> list[Path]:
    return sorted(root.rglob("case.xlsx"))


def scan(root: Path) -> dict:
    """扫 root 下所有 case.xlsx，返回 {autoid_or_path: {verdict, lb_methods, ...}}。"""
    out: dict[str, dict] = {}
    for xlsx in _find_cases(root):
        prov = xlsx.parent / "case.provenance.json"
        prov_arg = str(prov) if prov.is_file() else "-"
        key = xlsx.parent.name
        try:
            ext = extract(str(xlsx), prov_arg)
        except Exception as e:  # noqa: BLE001
            out[key] = {"verdict": "ERROR", "error": str(e)[:200]}
            continue
        out[key] = {
            "verdict": classify(ext),
            "lb_methods": ext.get("lb_methods", []),
            "distribution_assertion_count": ext.get("distribution_assertion_count", 0),
            "count_tautology_count": ext.get("count_tautology_count", 0),
            "gap": ext.get("distribution_coverage_gap_suspect", False),
            "path": str(xlsx),
        }
    return out


def _summary(results: dict) -> dict:
    from collections import Counter
    return dict(Counter(v["verdict"] for v in results.values()))


def main():
    args = [a for a in sys.argv[1:]]
    baseline_path = compare_path = None
    if "--baseline" in args:
        i = args.index("--baseline"); baseline_path = args[i + 1]; del args[i:i + 2]
    if "--compare" in args:
        i = args.index("--compare"); compare_path = args[i + 1]; del args[i:i + 2]
    root = Path(args[0]) if args else (_ROOT / "workspace" / "outputs")
    if not root.is_dir():
        print(f"ERROR: 目录不存在 {root}", file=sys.stderr)
        sys.exit(2)

    results = scan(root)
    summary = _summary(results)
    print(f"=== 分布区间断言 eval：{root} （{len(results)} cases）===\n")
    print("分类汇总:")
    for k in ("GOOD_DIST", "REL_OK", "SKIP", "BAD_TAUTOLOGY", "BAD_GAP", "ERROR"):
        if summary.get(k):
            print(f"  {k}: {summary[k]}")
    bad = {k: v for k, v in results.items() if v["verdict"].startswith("BAD")}
    if bad:
        print("\n⚠ 回归项（算法类断言形态错）:")
        for k, v in bad.items():
            print(f"  [{v['verdict']:14}] {k}  methods={v.get('lb_methods')}  "
                  f"taut={v.get('count_tautology_count')}  gap={v.get('gap')}")
    print("\n逐 case:")
    for k, v in results.items():
        print(f"  [{v['verdict']:14}] {k}  methods={v.get('lb_methods')} "
              f"dist={v.get('distribution_assertion_count')}")

    if baseline_path:
        Path(baseline_path).parent.mkdir(parents=True, exist_ok=True)
        Path(baseline_path).write_text(json.dumps(
            {"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n基线已写: {baseline_path}")

    if compare_path:
        base = json.loads(Path(compare_path).read_text(encoding="utf-8"))
        base_sum = base.get("summary", {})
        print(f"\n=== 与基线对比 {compare_path} ===")
        for k in ("GOOD_DIST", "REL_OK", "BAD_TAUTOLOGY", "BAD_GAP"):
            b = base_sum.get(k, 0); n = summary.get(k, 0)
            arrow = "→" if n == b else ("↑" if n > b else "↓")
            print(f"  {k}: {b} {arrow} {n}")
        # 回归判定：BAD_* 不应增、GOOD_DIST 不应减
        bad_now = summary.get("BAD_TAUTOLOGY", 0) + summary.get("BAD_GAP", 0)
        bad_base = base_sum.get("BAD_TAUTOLOGY", 0) + base_sum.get("BAD_GAP", 0)
        if bad_now > bad_base or summary.get("GOOD_DIST", 0) < base_sum.get("GOOD_DIST", 0):
            print("  ✗ 回归：BAD_* 增加 或 GOOD_DIST 减少")
            sys.exit(1)
        print("  ✓ 无回归")

    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
