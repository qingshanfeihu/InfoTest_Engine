"""Stage 3：HTML → 结构化 JSON。

读 ``knowledge/defect_raw/{backend}/*.html``，调 extractor，落
``knowledge/defect_cleaned/{backend}/{ticket_id}.json``。失败进 ``_quarantine/``。

用法::

    python -m main.ingest.defect_parse --backend bugzilla
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from main.ingest.html_extractors import get_extractor
from main.knowledge_paths import KNOWLEDGE_DEFECTS, KNOWLEDGE_INTERMEDIATE

logger = logging.getLogger(__name__)

# v2 路径（2026-05-19 重组）：
#   原始 HTML 落 .intermediate/（agent 不可见）
#   cleaned JSON 落 knowledge/data/defects/（agent 可见，最终位置）
RAW_ROOT = KNOWLEDGE_INTERMEDIATE / "defect_raw"
CLEAN_ROOT = KNOWLEDGE_DEFECTS


def _meta_lookup(backend: str) -> dict[str, dict]:
    meta_path = RAW_ROOT / backend / "meta.jsonl"
    out: dict[str, dict] = {}
    if meta_path.exists():
        for line in meta_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            tid = str(row.get("ticket_id") or "")
            if tid:
                out[tid] = row
    return out


def parse_backend(backend: str) -> tuple[int, int]:
    raw_dir = RAW_ROOT / backend
    if not raw_dir.exists():
        logger.info("无 raw 目录: %s", raw_dir)
        return 0, 0

    clean_dir = CLEAN_ROOT / backend
    clean_dir.mkdir(parents=True, exist_ok=True)
    quarantine = CLEAN_ROOT / "_quarantine" / backend
    quarantine.mkdir(parents=True, exist_ok=True)

    extractor = get_extractor(backend)
    meta = _meta_lookup(backend)

    ok = 0
    bad = 0
    for html_path in sorted(raw_dir.glob("*.html")):
        try:
            html = html_path.read_text(encoding="utf-8", errors="ignore")
            ticket = extractor.extract(html)
            row = meta.get(ticket.ticket_id, {})
            ticket.source_html_path = str(html_path.relative_to(Path.cwd())) if html_path.is_absolute() else str(html_path)
            if row.get("html_sha256"):
                ticket.html_sha256 = row["html_sha256"]
            ticket.captured_at = row.get("fetched_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            out_json = ticket.to_index_dict()
            out_path = clean_dir / f"{ticket.ticket_id}.json"
            out_path.write_text(json.dumps(out_json, ensure_ascii=False, indent=2), encoding="utf-8")
            ok += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("解析 %s 失败: %s", html_path.name, exc)
            shutil.copy2(html_path, quarantine / html_path.name)
            bad += 1
    return ok, bad


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="HTML 解析 → JSON")
    parser.add_argument("--backend", choices=["bugzilla", "plm"], required=True)
    args = parser.parse_args()

    ok, bad = parse_backend(args.backend)
    print(f"✅ parsed {ok} tickets, {bad} quarantined → {CLEAN_ROOT / args.backend}")


if __name__ == "__main__":
    main()
