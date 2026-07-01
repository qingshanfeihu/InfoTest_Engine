"""命中归属锚点 eval（确定性、可复现）——把「new_member_last 类产物必须真正锚定新增 pool」
这个回归固化成机读断言。

呼应 CLAUDE.md「改 prompt 前先有 eval」：扫已编译的 case.xlsx，对每个跑 grade_extract，按它产出
的 `new_member_unanchored_suspect` / `unanchored_new_pools` 信号（单一事实源，免两套判据漂移）
机读分类：

- BAD_UNANCHORED  : 中途新增绑定到 host 的 pool，其成员 IP 从没在任何 check_point 里出现过
                    （778012 型回归：全程只用 H 捕获比同异，从未拿新增 pool 的成员集合去锚）
- GOOD_ANCHORED   : 有中途新增 pool，且用命中归属锚点（membership_derived）真正锚定过它
- OK_NO_NEW_POOL  : 没有"中途新增 pool"这个结构模式，本 eval 不适用（不是缺陷，只是没这个场景）

⚠ BAD_UNANCHORED 是**结构事实**、非领域语义判断——它对"中途新增 pool + 从未被任何断言引用
它的成员 IP"这一模式无差别命中，包括那些压根不测流量命中/只测绑定数量上限的 case（如"能绑定
几个 pool"类，pool 的成员 IP 本就不该出现在断言里）。这类 case 出现在 BAD_UNANCHORED 里是
**预期内的假阳性**，不代表 grade 该判 CUT——是否要紧交给 grade 结合 need_intent 判（同
grade_extract.py 的 `new_member_unanchored_suspect` 文档）。用本 eval 追踪 new_member_last
类场景的回归时，逐条核对 need_intent 再下结论，不要只看汇总数字。

用法::

    python -m scripts.debug.eval_membership_assertions [outputs根目录]
    python -m scripts.debug.eval_membership_assertions <dir> --baseline runtime/logs/member_eval_base.json
    python -m scripts.debug.eval_membership_assertions <dir> --compare  runtime/logs/member_eval_base.json

默认根目录 workspace/outputs。退出码：有 BAD_UNANCHORED 时 exit 1（可作 CI gate），全干净 exit 0。
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
    if ext.get("new_member_unanchored_suspect"):
        return "BAD_UNANCHORED"
    has_membership = any(
        c.get("source_kind") == "membership_derived" for c in ext.get("check_points", []))
    if has_membership:
        return "GOOD_ANCHORED"
    return "OK_NO_NEW_POOL"


def _find_cases(root: Path) -> list[Path]:
    return sorted(root.rglob("case.xlsx"))


def scan(root: Path) -> dict:
    """扫 root 下所有 case.xlsx，返回 {autoid_or_path: {verdict, unanchored_new_pools, ...}}。"""
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
            "unanchored_new_pools": ext.get("unanchored_new_pools", []),
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
    print(f"=== 命中归属锚点 eval：{root} （{len(results)} cases）===\n")
    print("分类汇总:")
    for k in ("GOOD_ANCHORED", "OK_NO_NEW_POOL", "BAD_UNANCHORED", "ERROR"):
        if summary.get(k):
            print(f"  {k}: {summary[k]}")
    bad = {k: v for k, v in results.items() if v["verdict"] == "BAD_UNANCHORED"}
    if bad:
        print("\n⚠ 回归项（中途新增 pool 未被任何断言锚定）:")
        for k, v in bad.items():
            print(f"  [{v['verdict']:14}] {k}  unanchored={v.get('unanchored_new_pools')}")
    print("\n逐 case:")
    for k, v in results.items():
        print(f"  [{v['verdict']:14}] {k}")

    if baseline_path:
        Path(baseline_path).parent.mkdir(parents=True, exist_ok=True)
        Path(baseline_path).write_text(json.dumps(
            {"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n基线已写: {baseline_path}")

    if compare_path:
        base = json.loads(Path(compare_path).read_text(encoding="utf-8"))
        base_sum = base.get("summary", {})
        print(f"\n=== 与基线对比 {compare_path} ===")
        for k in ("GOOD_ANCHORED", "BAD_UNANCHORED"):
            b = base_sum.get(k, 0); n = summary.get(k, 0)
            arrow = "→" if n == b else ("↑" if n > b else "↓")
            print(f"  {k}: {b} {arrow} {n}")
        # 回归判定：BAD_UNANCHORED 不应增
        if summary.get("BAD_UNANCHORED", 0) > base_sum.get("BAD_UNANCHORED", 0):
            print("  ✗ 回归：BAD_UNANCHORED 增加")
            sys.exit(1)
        print("  ✓ 无回归")

    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
