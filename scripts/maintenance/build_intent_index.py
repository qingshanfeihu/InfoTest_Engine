"""阶段一·补：先例库意图标签索引（PLAN_footprint_v2_compile.md §阶段一·补）。

从 pairs_manifest_full.csv 读 `xlsx_file → intent_path` 映射，生成
`knowledge/framework/mirror_intent_index.json`（`{xlsx文件名: [intent_path,...]}`）。
一个 xlsx 可对多意图。纯数据生成，不改任何代码逻辑。

compile_precedent 的 intent 轴检索读这个索引：传了 intent 时，除 config Jaccard 外，
再算 intent 与该 xlsx 的 intent_path 文本相似度，让"没想好配啥命令但知道要测啥"也能检索到。

用法：
    .venv/bin/python -m scripts.maintenance.build_intent_index
    .venv/bin/python -m scripts.maintenance.build_intent_index --csv <path>
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger("build_intent_index")

_DEFAULT_CSV = "/Users/jiangyongze/Downloads/files/pairs_manifest_full.csv"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_index(csv_path: Path) -> dict[str, list[str]]:
    """读 csv → {xlsx_basename: [intent_path, ...]}（去重、保序）。"""
    index: dict[str, list[str]] = {}
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            xlsx = (row.get("xlsx_file") or "").strip()
            intent = (row.get("intent_path") or "").strip()
            if not xlsx or not intent:
                continue
            paths = index.setdefault(xlsx, [])
            if intent not in paths:
                paths.append(intent)
    return index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建先例库意图标签索引")
    parser.add_argument("--csv", default=_DEFAULT_CSV, help="pairs_manifest_full.csv 路径")
    parser.add_argument("--out", default="", help="输出 json 路径（默认 knowledge/framework/mirror_intent_index.json）")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    csv_path = Path(args.csv)
    if not csv_path.is_file():
        logger.error("csv 不存在: %s", csv_path)
        return 1

    index = build_index(csv_path)
    out_path = Path(args.out) if args.out else (
        _project_root() / "knowledge" / "framework" / "mirror_intent_index.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    n_intents = sum(len(v) for v in index.values())
    logger.info("索引落盘: %s", out_path)
    logger.info("xlsx 文件数: %d，意图路径总数: %d", len(index), n_intents)
    return 0


if __name__ == "__main__":
    sys.exit(main())
