"""一次性脚本：把历史评审 findings.md archive 到子目录。

背景：
- ``main/ist_core/skills/test-case-review/memory_adapter.py:review_finalizer``
  历史版本会把评审结论（P 级别 + finding 列表）写到
  ``memory/reviews/cases/<case>/findings.md`` +
  ``memory/reviews/tickets/<id>/findings.md``
- 这些文件被 ``review_key_resolvers`` 注入回主 agent，导致下次评审复用历史
  结论（trace 实证 LLM thought 出现"memory context 里提到已有评审结果"）
- 2026-05-26 起 ``review_finalizer`` 改为返回 None（不再写入），但**历史存量**
  仍会被 inject

本脚本：把 ``memory/reviews/cases/`` 与 ``memory/reviews/tickets/`` 整体移到
``memory/reviews/archive/<时间戳>/`` 子目录；移走后 ``review_key_resolvers``
注入这两个路径不会有内容（resolver 只看 path 不存在不会报错），等于 inject
端自然干净。

跑法（**只跑一次**）::

    .venv/bin/python -m scripts.maintenance.archive_review_findings

环境变量：
- ``IST_MEMORY_ROOT``：memory 根目录（默认 ``<repo>/memory``）
不存评审结论到 memory，所以无存量需清。InfoTest_Engine 是历史负担，需要
一次性脚本切干净反馈环。
"""

from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

def _project_root() -> Path:
    """回退查找：脚本所在 → parents 直到含 ``main/ist_core/`` 目录."""
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "main" / "ist_core").is_dir():
            return parent
    return Path.cwd()

def archive_review_findings(memory_root: Path | None = None) -> dict[str, Path]:
    """把 reviews/cases + reviews/tickets 移到 archive/<时间戳>/.

    Returns:
        ``{"cases": <archive_path>, "tickets": <archive_path>}``，
        没有源目录的 key 跳过。
    """
    if memory_root is None:
        env_root = os.environ.get("IST_MEMORY_ROOT")
        if env_root:
            memory_root = Path(env_root).resolve()
        else:
            memory_root = (_project_root() / "memory").resolve()

    reviews_root = memory_root / "reviews"
    if not reviews_root.is_dir():
        print(f"[archive] {reviews_root} 不存在，无需 archive")
        return {}

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_root = reviews_root / "archive" / timestamp
    archive_root.mkdir(parents=True, exist_ok=True)

    moved: dict[str, Path] = {}
    for sub in ("cases", "tickets"):
        src = reviews_root / sub
        if not src.exists():
            print(f"[archive] {src} 不存在，跳过")
            continue
        if not src.is_dir():
            print(f"[archive] {src} 不是目录，跳过")
            continue
        dst = archive_root / sub
        shutil.move(str(src), str(dst))
        moved[sub] = dst
        print(f"[archive] moved: {src} -> {dst}")

    if not moved:
        archive_root.rmdir()
        print(f"[archive] 没有内容需要 archive；已移除空目录 {archive_root}")
    else:
        print(f"[archive] 完成：{len(moved)} 个目录移到 {archive_root}")
    return moved

def main() -> int:
    try:
        archive_review_findings()
    except Exception as exc:  # noqa: BLE001
        print(f"[archive] 错误：{exc}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
