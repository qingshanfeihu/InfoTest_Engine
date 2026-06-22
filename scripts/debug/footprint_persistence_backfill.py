"""定向补全:把手册「配置保存/恢复」命令族(write↔config memory/file/all/net + clear)
灌进 footprint。复用 footprint_backfill 的「切片→extract→route→merge(60% evidence 门)」全链,
只过滤出含这些命令的片(零编造:evidence 门保证;零新建机制:走既有链)。

用法: .venv/bin/python -m scripts.debug.footprint_persistence_backfill [--dry-run]
"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("persist_backfill")

# 只要这些命令族(配置保存/恢复/清除)所在的片
_PERSIST_RE = re.compile(
    r"\b(write\s+(memory|file|all|net)|config\s+(memory|file|all|net)|"
    r"clear\s+config|show\s+startup|config\s+consistency)\b",
    re.IGNORECASE,
)


def main(argv: list[str] | None = None) -> int:
    from main.langchain_env import langchain_load_dotenv_if_present
    langchain_load_dotenv_if_present()

    from scripts.maintenance.footprint_backfill import (
        slice_manual, pack_batches, render_batch, build_backfill_llm,
    )
    from main import knowledge_paths as kp
    from main.ist_core.memory.footprint import (
        extract_facts, route_facts, merge_fact, reconcile,
    )
    from main.ist_core.memory.dream import _load_existing_facts

    dry = "--dry-run" in (argv or sys.argv[1:])
    root = Path(__file__).resolve().parents[2]

    # 配置保存/恢复命令集中在 part3(系统配置章节)
    manuals = sorted((root / "knowledge/data/markdown/product").glob("10.5_cli__part3*.md"))
    chunks = []
    for md in manuals:
        rel = md.relative_to(root).as_posix()
        for ch in slice_manual(md, rel):
            if _PERSIST_RE.search(ch.body):
                chunks.append(ch)
    logger.info("命中持久化命令片: %d", len(chunks))
    for ch in chunks:
        sig = ch.body.splitlines()[0][:60]
        logger.info("  片: %s", sig)

    batches = pack_batches(chunks)
    logger.info("打包: %d 批", len(batches))
    if dry:
        return 0

    llm = build_backfill_llm()
    if llm is None:
        logger.error("无 LLM key")
        return 1

    fp_dir = kp.KNOWLEDGE_FOOTPRINTS
    kp.KNOWLEDGE_FOOTPRINTS_NODES.mkdir(parents=True, exist_ok=True)
    existing = _load_existing_facts(fp_dir)

    all_facts = []
    for i, b in enumerate(batches):
        facts = extract_facts(render_batch(b), llm_chat=llm, existing_facts=existing)
        all_facts.extend(facts)
        logger.info("批 %d/%d → %d facts(累计 %d)", i + 1, len(batches), len(facts), len(all_facts))

    create = append = update = skip = 0
    skip_detail: dict = {}
    for rf in route_facts(all_facts, fp_dir):
        r = merge_fact(rf, fp_dir)
        if r.action == "create": create += 1
        elif r.action == "append": append += 1
        elif r.action == "update": update += 1
        else:
            skip += 1
            skip_detail[r.detail] = skip_detail.get(r.detail, 0) + 1
    rec = reconcile(fp_dir)
    print(f"\n=== 持久化 footprint 补全 ===")
    print(f"facts: {len(all_facts)}  create={create} append={append} update={update} skip={skip}")
    print(f"skip detail: {skip_detail}")
    print(f"reconcile: {rec}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
