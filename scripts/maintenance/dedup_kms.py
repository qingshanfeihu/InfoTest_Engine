#!/usr/bin/env python
"""源+产物联动去重（治本）——dry-run 默认，--apply 真改（move 软删，绝不硬删）。

两条独立去重链路，各自按内容 sha256 分组、组内留 1 个「最干净名」、其余移归档：

  1. product 产物去重：扫 ``knowledge/data/markdown/product/*.md`` 算 sha256，
     内容完全相同的为一组。冗余 md 移到 ``.dedup_cleanup_archive/product/``。
     产物可由 mineru 重生，故**不动** source_index。
  2. source 源文件去重：扫 ``knowledge/data/orgin/`` 全部源文件算 sha256
     （命中 source_index 且 mtime+size 未变则复用索引哈希，否则现算）。
     冗余源移到 ``.dedup_cleanup_archive/source/``，并**同步** source_index：
       - 删冗余源的 by_path 条目；
       - by_hash[sha] 保留并指向 canonical（若原先指向被移走的源，改写为 canonical）。

另外把 3 个已知垃圾产物（backend.md 只空标题、DCC traffic flow×2 正文 0 字）
强制纳入 product 移走清单（即使它们恰好不是去重冗余）。

「最干净名」评分（小者优先，逐项比较）：
  含中文 > 无哈希尾(_a1b2c3) > 无 (1) 拷贝标记 > 无下划线占位(____) > 越短越好 > 字典序

关键安全闸：
  - 保留名之间做**大小写不敏感**(.lower()) 撞名检测（按父目录分组）。
    macOS / SynologyDrive 等大小写不敏感盘上，仅大小写不同的两名是同一文件，
    apply 时会互相覆盖丢数据 → 一旦发现撞名**报错不执行**。
  - 清理一律 MOVE 到归档目录（软删除，可回滚），绝不硬删。
  - apply 期间 overwrite 保护：目标已存在且非自身 → 跳过不覆盖。
  - 增量写 undo 清单（每步落盘，崩溃也可回滚）。

用法::

    python -m scripts.maintenance.dedup_kms              # dry-run（默认）
    python -m scripts.maintenance.dedup_kms --apply      # 真改
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from main import knowledge_paths as kp  # noqa: E402
from main.mineru_source_index import INDEX_FILENAME, _sha256_file  # noqa: E402

_ORGIN = kp.KNOWLEDGE_ORGIN
_MD_PRODUCT = kp.KNOWLEDGE_MARKDOWN_PRODUCT
_MINERU_DIR = kp.KNOWLEDGE_INTERMEDIATE / "mineru"
_INDEX_PATH = _MINERU_DIR / INDEX_FILENAME
_ARCHIVE = kp.KNOWLEDGE_INTERMEDIATE / ".dedup_cleanup_archive"
_ARCHIVE_PRODUCT = _ARCHIVE / "product"
_ARCHIVE_SOURCE = _ARCHIVE / "source"

# 3 个已知垃圾产物（按 basename），强制移走（与去重分组无关）
_GARBAGE_PRODUCT = {
    "backend.md",
    "DCC traffic flow.md",
    "DCC traffic flow_c214cee9.md",
}

_CJK = re.compile(r"[一-鿿]")
_HASH_TAIL = re.compile(r"_[0-9a-fA-F]{6,8}$")
_COPY_MARK = re.compile(r"[\(（]\s*\d+\s*[\)）]\s*$|[ _]copy(\s*\d*)?$", re.IGNORECASE)
_UNDERSCORE_PLACEHOLDER = re.compile(r"_{4,}")


def _cleanliness_key(name: str) -> tuple:
    """返回排序键，**小者最干净**（逐项优先级见模块 docstring）。"""
    stem = Path(name).stem
    has_chinese = bool(_CJK.search(name))
    has_hash = bool(_HASH_TAIL.search(stem))
    has_copy = bool(_COPY_MARK.search(stem))
    has_placeholder = bool(_UNDERSCORE_PLACEHOLDER.search(stem))
    return (
        0 if has_chinese else 1,
        1 if has_hash else 0,
        1 if has_copy else 0,
        1 if has_placeholder else 0,
        len(name),
        name,
    )


def _rel_orgin(p: Path) -> str:
    try:
        return p.resolve().relative_to(_ORGIN.resolve()).as_posix()
    except ValueError:
        return p.resolve().as_posix()


# ---------------------------------------------------------------- product

def _scan_product(md_dir: Path | None = None) -> tuple[list[dict], list[Path]]:
    """扫 <md_dir>/*.md 分组（默认 product 桶）。返回 (dedup_groups, garbage_paths)。

    dedup_groups: [{sha, keep: Path, drop: [Path,...]}]（仅 size>=2 的组）。
    garbage_paths: 命中 _GARBAGE_PRODUCT 的全部路径（强制移走，排除出去重分组）。
    """
    scan_dir = md_dir if md_dir is not None else _MD_PRODUCT
    by_sha: dict[str, list[Path]] = defaultdict(list)
    garbage: list[Path] = []
    for md in sorted(scan_dir.glob("*.md")):
        if md.name in _GARBAGE_PRODUCT:
            garbage.append(md)
            continue
        try:
            sha = _sha256_file(md)
        except Exception:
            continue
        by_sha[sha].append(md)

    groups: list[dict] = []
    for sha, members in by_sha.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda p: _cleanliness_key(p.name))
        groups.append({"sha": sha, "keep": members[0], "drop": members[1:]})
    return groups, garbage


# ---------------------------------------------------------------- source

def _load_index() -> dict:
    if _INDEX_PATH.exists():
        return json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    return {"version": 1, "by_hash": {}, "by_path": {}}


def _scan_source(index: dict) -> list[dict]:
    """扫 orgin/ 全部源文件分组。复用索引哈希（mtime+size 未变时）否则现算。

    返回 [{sha, keep: Path, drop: [Path,...]}]（仅 size>=2 的组）。
    """
    by_path = index.get("by_path", {}) or {}
    by_sha: dict[str, list[Path]] = defaultdict(list)

    for p in sorted(_ORGIN.rglob("*")):
        if not p.is_file():
            continue
        rel = _rel_orgin(p)
        sha = None
        entry = by_path.get(rel)
        if entry:
            try:
                st = p.stat()
                if (abs(st.st_mtime - entry.get("mtime", -1)) < 1e-6
                        and st.st_size == entry.get("size")):
                    sha = entry.get("hash")
            except OSError:
                pass
        if not sha:
            try:
                sha = _sha256_file(p)
            except Exception:
                continue
        by_sha[sha].append(p)

    groups: list[dict] = []
    for sha, members in by_sha.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda p: _cleanliness_key(p.name))
        groups.append({"sha": sha, "keep": members[0], "drop": members[1:]})
    return groups


# ---------------------------------------------------------------- safety gate

def _case_collision(kept_paths: list[Path]) -> list[tuple[str, list[str]]]:
    """保留名之间大小写不敏感撞名检测（按父目录分组）。

    返回撞名清单 [(父目录小写+名小写, [实际路径,...])]，空列表表示无撞名。
    """
    buckets: dict[tuple[str, str], list[str]] = defaultdict(list)
    for p in kept_paths:
        key = (p.parent.as_posix().lower(), p.name.lower())
        buckets[key].append(str(p))
    collisions = []
    for (_pl, _nl), members in buckets.items():
        # 去重实际路径（同一路径不算撞）
        uniq = sorted(set(members))
        if len(uniq) > 1:
            collisions.append((f"{_pl}/{_nl}", uniq))
    return collisions


# ---------------------------------------------------------------- apply

def _archive_dest(src: Path, archive_root: Path, sub_rel: Path | None) -> Path:
    """归档目标路径。source 保留 orgin 下相对目录结构；product 扁平。"""
    if sub_rel is not None:
        return archive_root / sub_rel
    return archive_root / src.name


def _do_move(src: Path, dst: Path, undo: list, stats: Counter, kind: str) -> None:
    if not src.exists():
        stats["skip_missing"] += 1
        return
    if dst.exists():
        try:
            same = src.samefile(dst)
        except OSError:
            same = False
        if not same:
            stats["skip_would_overwrite"] += 1
            return
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    undo.append({"from": str(dst), "to": str(src)})
    stats[f"moved_{kind}"] += 1


def main() -> int:
    ap = argparse.ArgumentParser(description="源+产物联动去重(dry-run 默认)")
    ap.add_argument("--apply", action="store_true", help="真改(默认 dry-run)")
    ap.add_argument("--product-only", action="store_true",
                    help="只跑 product 产物去重，完全跳过 source(orgin) 扫描与移动")
    ap.add_argument("--report", default="/tmp/dedup_report.json")
    ap.add_argument("--undo-out", default="/tmp/dedup_undo.json")
    args = ap.parse_args()

    index = _load_index()

    prod_groups, garbage = _scan_product()
    src_groups = [] if args.product_only else _scan_source(index)

    # ---- 保留名集合 + 大小写撞名安全闸 ----
    prod_keep = [g["keep"] for g in prod_groups]
    src_keep = [g["keep"] for g in src_groups]
    prod_collisions = _case_collision(prod_keep)
    src_collisions = _case_collision(src_keep)
    has_collision = bool(prod_collisions or src_collisions)

    prod_removable = sum(len(g["drop"]) for g in prod_groups)
    src_removable = sum(len(g["drop"]) for g in src_groups)
    total_product_moves = prod_removable + len(garbage)

    report = {
        "mode": "apply" if args.apply else "dry-run",
        "product_only": args.product_only,
        "product": {
            "dup_groups": len(prod_groups),
            "removable_dups": prod_removable,
            "garbage_forced": len(garbage),
            "total_moves": total_product_moves,
            "garbage_files": [str(p) for p in garbage],
        },
        "source": {
            "dup_groups": len(src_groups),
            "removable_dups": src_removable,
        },
        "case_collision": {
            "product": prod_collisions,
            "source": src_collisions,
            "blocked": has_collision,
        },
    }
    Path(args.report).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"[mode] {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"product: 重复组 {len(prod_groups)}  可移冗余 {prod_removable}"
          f"  + 垃圾 {len(garbage)}  = 共移 {total_product_moves}")
    print(f"source : 重复组 {len(src_groups)}  可移冗余 {src_removable}")
    print(f"大小写撞名检测: product {len(prod_collisions)} 组, "
          f"source {len(src_collisions)} 组")
    print(f"清单 → {args.report}")

    if has_collision:
        print("\n[ABORT] 保留名存在大小写不敏感撞名，拒绝执行（防覆盖丢数据）。")
        for label, members in (prod_collisions + src_collisions):
            print(f"  撞名 {label}: {members}")
        return 2

    if not args.apply:
        print("\n(dry-run，未改任何文件。确认后加 --apply)")
        return 0

    # ---- APPLY ----
    undo: list[dict] = []
    stats: Counter = Counter()
    undo_path = Path(args.undo_out)

    def _flush():
        undo_path.write_text(
            json.dumps({"undo": undo}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    _flush()
    try:
        # product 去重冗余 + 垃圾 → archive/product/（扁平）
        for g in prod_groups:
            for d in g["drop"]:
                _do_move(d, _archive_dest(d, _ARCHIVE_PRODUCT, None),
                         undo, stats, "product_dup")
                _flush()
        for d in garbage:
            _do_move(d, _archive_dest(d, _ARCHIVE_PRODUCT, None),
                     undo, stats, "product_garbage")
            _flush()

        # source 去重冗余 → archive/source/<orgin相对目录>/
        src_dropped_rels: list[str] = []
        for g in src_groups:
            for d in g["drop"]:
                rel = Path(_rel_orgin(d))
                _do_move(d, _archive_dest(d, _ARCHIVE_SOURCE, rel),
                         undo, stats, "source_dup")
                _flush()
                src_dropped_rels.append((g["sha"], rel.as_posix(),
                                         _rel_orgin(g["keep"])))
    except BaseException:
        _flush()
        raise

    # ---- source_index 同步（仅 source 链路）----
    if src_groups and _INDEX_PATH.exists():
        data = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
        by_path = data.get("by_path", {}) or {}
        by_hash = data.get("by_hash", {}) or {}

        for sha, drop_rel, keep_rel in src_dropped_rels:
            if by_path.pop(drop_rel, None) is not None:
                stats["idx_path_removed"] += 1
            # by_hash[sha] 保留并指向 canonical
            entry = by_hash.get(sha)
            if entry is not None:
                keep_name = Path(keep_rel).name
                if entry.get("source") and entry.get("source") != keep_name:
                    # 若原指向被移走的源 basename，改写为 canonical
                    drop_name = Path(drop_rel).name
                    if entry.get("source") == drop_name:
                        entry["source"] = keep_name
                        stats["idx_hash_repointed"] += 1

        data["by_path"] = by_path
        data["by_hash"] = by_hash
        tmp = _INDEX_PATH.with_suffix(_INDEX_PATH.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(_INDEX_PATH)
        stats["idx_saved"] = 1

    print(f"\n[applied] {dict(stats)}")
    print(f"回滚清单 → {undo_path}（{len(undo)} 条，全部可逆 move，增量落盘）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
