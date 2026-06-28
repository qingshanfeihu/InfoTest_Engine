"""KMS 转换后处理 —— 把"语法修复 + 去重 + 垃圾清理"固化为 KMS 流程的常驻环节。

背景：早先这些是事后手动跑的零散 maintenance 脚本。本模块把已验证安全的几项
收口成单一入口 ``run_postprocess()``，由 ``kms_cli`` 在 ``mineru_batch_export``
转换完成后自动调用，使 ``infotest kms product update`` 一条命令即可产出干净、
命令语法完整、已去重的 KMS 知识库，无需人工事后补。

三个环节（全部幂等、可逆）：

1. **命令手册语法修复**：MinerU 对"命令名独占一行 + 参数另起行"的跨行语法块
   系统性丢参数（CLI 手册截断率 98.8%）。对注册表 ``_SYNTAX_MANUALS`` 里的 CLI
   手册，用本地 pypdf 重抽的完整语法行精确覆盖（完整命令头匹配 + 防折叠铁律 +
   残缺行跳过不猜）。复用 ``scripts.maintenance.fix_manual_command_syntax``。
   app 手册结构不同（命令散在示例/回显/正文）不适合自动修，已排除。

2. **product 内容去重**：同内容 sha256 的重复 md 留最干净名、其余 move 到归档。
   产物可重生，不动 source_index。复用 ``scripts.maintenance.dedup_kms``。

3. **垃圾文件清理**：仅空标题/正文极少的废产物 move 到归档。

安全铁律（血泪教训）：一切 move 不硬删；大小写不敏感撞名检测；知识库不在 git，
归档目录是唯一兜底。``apply=False`` 时只报告不动文件。
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 纳入自动语法修复的命令手册（stem）。app 手册不在此列（结构不支持安全自动修）。
# 新增 CLI 手册时在此登记，且需确认 orgin/ 下有对应 PDF 源。
# 10.5 手册已切到 manual_10.5/（按章节切 cli_10.5_Chapter*），不走本 partN 语法修复链；
# cli_74（旧版）已清理。当前无按 partN 切分的 CLI 手册需走本修复链。
_SYNTAX_MANUALS = ()


def _fix_command_syntax(apply: bool) -> dict:
    """对注册表里的 CLI 手册跑命令语法修复。返回各手册统计。"""
    from scripts.maintenance.fix_manual_command_syntax import fix_manual, _MANUALS, _ORGIN

    results: dict[str, dict] = {}
    for stem in _SYNTAX_MANUALS:
        if stem not in _MANUALS:
            results[stem] = {"skipped": "未在 _MANUALS 注册"}
            continue
        pdf_name = _MANUALS[stem][0]
        if not (_ORGIN / pdf_name).exists():
            # 源 PDF 不在（如已冷归档）→ 无法本地重抽，跳过（不报错）
            results[stem] = {"skipped": f"源 PDF 缺失: {pdf_name}"}
            continue
        try:
            results[stem] = fix_manual(stem, apply)
        except Exception as exc:  # noqa: BLE001
            results[stem] = {"error": str(exc)}
    return results


def _dedup_products(apply: bool, bucket: str = "product") -> dict:
    """指定桶(product/qa)内容去重 + 垃圾清理（不碰 source/orgin）。返回统计。"""
    from collections import Counter
    from scripts.maintenance.dedup_kms import (
        _scan_product, _case_collision, _archive_dest, _do_move,
        _ARCHIVE,
    )
    from main import knowledge_paths as kp

    md_dir = kp.KNOWLEDGE_MARKDOWN_QA if bucket == "qa" else kp.KNOWLEDGE_MARKDOWN_PRODUCT
    prod_groups, garbage = _scan_product(md_dir)
    keep_names = [g["keep"] for g in prod_groups]
    collisions = _case_collision(keep_names)
    if collisions:
        return {"blocked": "保留名存在大小写不敏感撞名", "collisions": collisions[:5]}

    removable = sum(len(g["drop"]) for g in prod_groups)
    stats = {"dup_groups": len(prod_groups), "removable": removable,
             "garbage": len(garbage), "moved": 0}

    if not apply:
        return stats

    undo: list = []
    move_stats: Counter = Counter()
    archive_root = _ARCHIVE / bucket
    for g in prod_groups:
        for drop in g["drop"]:
            dp = Path(drop)
            if dp.exists():
                _do_move(dp, _archive_dest(dp, archive_root, None), undo, move_stats, "product-dup")
    for gf in garbage:
        gp = Path(gf)
        if gp.exists():
            _do_move(gp, _archive_dest(gp, archive_root, None), undo, move_stats, "product-garbage")
    stats["moved"] = sum(move_stats.values())

    # undo 落盘到仓库内持久路径（非 /tmp，防重启丢失）
    import json
    undo_path = _PROJECT_ROOT / "knowledge" / ".intermediate" / ".kms_postprocess_undo.json"
    undo_path.parent.mkdir(parents=True, exist_ok=True)
    undo_path.write_text(json.dumps({"undo": undo}, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    stats["undo_path"] = str(undo_path)
    return stats


def run_postprocess(apply: bool = True, *, bucket: str = "product",
                    do_syntax: bool = True, do_dedup: bool = True) -> dict:
    """KMS 转换后处理统一入口。

    Args:
        apply: True 真改（move 软删），False 只报告。
        bucket: 处理哪个桶("product" 或 "qa")。qa 桶无命令手册，语法修复自动跳过。
        do_syntax: 跑命令手册语法修复（仅 product 桶有效）。
        do_dedup: 跑内容去重 + 垃圾清理。

    Returns:
        各环节统计 dict。
    """
    report: dict = {"mode": "apply" if apply else "dry-run", "bucket": bucket}
    # 命令手册只在 product 桶，qa 桶跳过语法修复
    if do_syntax and bucket == "product":
        report["syntax_fix"] = _fix_command_syntax(apply)
    if do_dedup:
        report["dedup"] = _dedup_products(apply, bucket)
    return report


def _print_report(report: dict) -> None:
    print(f"\n[kms postprocess] {report['mode']}")
    sf = report.get("syntax_fix", {})
    if sf:
        print("  命令语法修复:")
        for stem, s in sf.items():
            if "skipped" in s:
                print(f"    {stem}: 跳过({s['skipped']})")
            elif "error" in s:
                print(f"    {stem}: 错误({s['error']})")
            else:
                print(f"    {stem}: {'已改' if report['mode']=='apply' else '将改'} "
                      f"{s.get('patched',0)} 行 / 匹配 {s.get('matched',0)} / "
                      f"跳过不猜 {s.get('no_local',0)} / 防折叠拦截 {s.get('corrupt_blocked',0)}")
    dd = report.get("dedup", {})
    if dd:
        if "blocked" in dd:
            print(f"  product去重: 已阻断({dd['blocked']})")
        else:
            print(f"  product去重: {dd.get('dup_groups',0)}组重复 / "
                  f"可移{dd.get('removable',0)} / 垃圾{dd.get('garbage',0)} / "
                  f"实移{dd.get('moved',0)}")


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="KMS 转换后处理(语法修复+去重)")
    ap.add_argument("--apply", action="store_true", help="真改(默认 dry-run)")
    ap.add_argument("--no-syntax", action="store_true", help="跳过语法修复")
    ap.add_argument("--no-dedup", action="store_true", help="跳过去重")
    args = ap.parse_args()
    report = run_postprocess(apply=args.apply, do_syntax=not args.no_syntax,
                             do_dedup=not args.no_dedup)
    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
