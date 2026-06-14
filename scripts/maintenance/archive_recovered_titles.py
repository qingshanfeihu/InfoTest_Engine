#!/usr/bin/env python
"""乱码文件名归档器 — 全链重命名 apply（dry-run 默认，自动消歧 + 去重）。

读 ``.recover_titles.py`` 产出的计划（``/tmp/recover_final.json``），把 orgin/ 下
含字面 ``?`` 的乱码名源文件按还原标题重命名，并**同步**所有关联产物，保持 KMS 全链一致：

  1. orgin/ 源文件本身              <old>.ext        → <new>.ext
  2. markdown 产物                  <stem>.md / <stem>__part*.md
  3. mineru 中间产物                <stem>.mineru.zip / .code_format.json / .raw_data.json
  4. source_index (.source_index.json)  by_path key 改名 + by_hash 字段改名

自动消歧（关键）：orgin 保留目录结构，但 md/zip 产物**扁平**堆在 markdown/product/。
不同 orgin 子目录的两个文档若还原成同一标题，产物在扁平目录会撞名互相覆盖。处理：

  - **真重复**（同一标题且源内容 sha256 相同）：去重——保留 rel 最短的 canonical，
    其余源+产物**移到** ``knowledge/.intermediate/.dedup_archive/``（软删除，可回滚），
    不真删。
  - **内容不同的撞名**：给每个加后缀消歧——优先取源名 ASCII 特征（design/spec/Bug号），
    无可用 ASCII 则用源内容 sha256 前 8 位，保证组内唯一。

安全设计：
  - 默认 ``--dry-run`` 只产清单；``--apply`` 真改并写 undo 清单（全部为可逆 move）。
  - 目标已存在（计划外的既有文件）→ 该条整体跳过并计入 conflicts。

用法::

    python -m scripts.maintenance.archive_recovered_titles            # dry-run
    python -m scripts.maintenance.archive_recovered_titles --apply
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from main import knowledge_paths as kp  # noqa: E402
from main.mineru_batch_export import _safe_stem  # noqa: E402
from main.mineru_source_index import INDEX_FILENAME, _sha256_file  # noqa: E402

_MINERU_DIR = kp.KNOWLEDGE_INTERMEDIATE / "mineru"
_MD_DIR = kp.KNOWLEDGE_MARKDOWN_PRODUCT
_ORGIN = kp.KNOWLEDGE_ORGIN
_DEDUP_ARCHIVE = kp.KNOWLEDGE_INTERMEDIATE / ".dedup_archive"

_MINERU_SUFFIXES = (".mineru.zip", ".code_format.json", ".raw_data.json")


def _md_products(stem: str) -> list[Path]:
    out: list[Path] = []
    single = _MD_DIR / f"{stem}.md"
    if single.exists():
        out.append(single)
    out.extend(sorted(_MD_DIR.glob(f"{stem}__part*.md")))
    return out


def _mineru_products(stem: str) -> list[Path]:
    out: list[Path] = []
    for suf in _MINERU_SUFFIXES:
        p = _MINERU_DIR / f"{stem}{suf}"
        if p.exists():
            out.append(p)
        out.extend(sorted(_MINERU_DIR.glob(f"{stem}__part*{suf}")))
    return out


def _rename_stem_in(name: str, old_stem: str, new_stem: str) -> str:
    if name.startswith(old_stem):
        return new_stem + name[len(old_stem):]
    return name


def _rel_orgin(p: Path) -> str:
    try:
        return p.resolve().relative_to(_ORGIN.resolve()).as_posix()
    except ValueError:
        return p.resolve().as_posix()


def _ascii_suffix(old_name: str) -> str:
    bits = re.findall(r"[A-Za-z0-9.#]+", Path(old_name).stem)
    return "_".join(bits)[:30] if bits else ""


def _is_legal_name(name: str) -> bool:
    """新文件名是否合法落盘：剔除含损坏/控制/罕见区字符的乱码标题。

    崩溃根因：.recover_titles 偶尔提取出乱码标题（如版权页噪声、误解码串），
    含控制字符/未分配码位/注音符号区(3100-312F)/泰文组合区(0E00-0E7F)等，
    文件系统 rename 会报 Illegal byte sequence。这类跳过不改名，保留原乱码名待人工。
    """
    for ch in name:
        if unicodedata.category(ch) in ("Cc", "Cn", "Cs", "Co"):
            return False
        cp = ord(ch)
        if 0x3100 <= cp <= 0x312F or 0x0E00 <= cp <= 0x0E7F:
            return False
    try:
        name.encode("utf-8")
    except Exception:
        return False
    return True


def _source_sha(rel: str, cache: dict[str, str]) -> str | None:
    if rel in cache:
        return cache[rel]
    p = _ORGIN / rel
    try:
        h = _sha256_file(p)
    except Exception:
        h = None
    cache[rel] = h
    return h


def resolve_final_names(plan_rows: list[dict]) -> tuple[list[dict], dict]:
    """全局消歧：决定每条的最终 new_name + 动作类型（rename / dedup_drop）。

    返回 (resolved_rows, sha_cache)。每条 row 追加：
      final_name, action('rename'|'dedup_drop'), sha, canonical_rel(仅dedup), disambig(bool)
    """
    sha_cache: dict[str, str] = {}
    # 只处理源存在、且新名合法的
    live = []
    skipped_illegal = []
    for row in plan_rows:
        if not (_ORGIN / row["rel"]).exists():
            continue
        if not _is_legal_name(row["new"]):
            skipped_illegal.append(row)
            continue
        row = dict(row)
        row["sha"] = _source_sha(row["rel"], sha_cache)
        live.append(row)
    if skipped_illegal:
        print(f"[skip] {len(skipped_illegal)} 个乱码标题跳过(保留原名待人工): "
              + ", ".join(r["old"][:25] for r in skipped_illegal[:5]))

    # 按目标 new_name 全局分组（扁平产物空间）
    by_new: dict[str, list[dict]] = defaultdict(list)
    for row in live:
        by_new[row["new"]].append(row)

    resolved: list[dict] = []
    for new_name, group in by_new.items():
        if len(group) == 1:
            r = group[0]
            r["final_name"] = new_name
            r["action"] = "rename"
            r["disambig"] = False
            resolved.append(r)
            continue

        # 撞名组：先按 sha 子分组去重
        by_sha: dict[str, list[dict]] = defaultdict(list)
        for r in group:
            by_sha[r["sha"] or f"__nohash_{r['rel']}"].append(r)

        # 每个 sha 子组：rel 最短者为 canonical，其余 dedup_drop
        canonicals: list[dict] = []
        for sha, members in by_sha.items():
            members.sort(key=lambda x: (len(x["rel"]), x["rel"]))
            canon = members[0]
            canonicals.append(canon)
            for drop in members[1:]:
                drop["action"] = "dedup_drop"
                drop["canonical_rel"] = canon["rel"]
                drop["final_name"] = None
                drop["disambig"] = False
                resolved.append(drop)

        # canonicals 之间：若只剩 1 个唯一内容 → 独占 new_name；否则全部加后缀消歧
        if len(canonicals) == 1:
            c = canonicals[0]
            c["final_name"] = new_name
            c["action"] = "rename"
            c["disambig"] = False
            resolved.append(c)
        else:
            ext = Path(new_name).suffix
            base = Path(new_name).stem
            used: set[str] = set()
            for c in canonicals:
                suf = _ascii_suffix(c["old"]) or (c["sha"] or "")[:8]
                cand = f"{base}_{suf}{ext}"
                if cand in used or suf == "":
                    cand = f"{base}_{(c['sha'] or '')[:8]}{ext}"
                used.add(cand)
                c["final_name"] = cand
                c["action"] = "rename"
                c["disambig"] = True
                resolved.append(c)

    # 大小写不敏感撞名消歧：macOS/SynologyDrive 等大小写不敏感盘上，仅大小写不同的
    # 两个新名是同一文件名 → apply 会互相覆盖丢数据。按 (父目录, 新名小写) 全局
    # 检测，撞组里除第一个外都加源名特征/sha 后缀，确保大小写不敏感下也唯一。
    ci_groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in resolved:
        if r["action"] != "rename":
            continue
        parent = Path(r["rel"]).parent.as_posix()
        ci_groups[(parent, r["final_name"].lower())].append(r)
    for (_parent, _low), members in ci_groups.items():
        if len(members) <= 1:
            continue
        for r in members[1:]:
            ext = Path(r["final_name"]).suffix
            base = Path(r["final_name"]).stem
            suf = _ascii_suffix(r["old"]) or (r["sha"] or "")[:8]
            r["final_name"] = f"{base}_{suf}{ext}" if suf else f"{base}_{(r['sha'] or '')[:8]}{ext}"
            r["disambig"] = True

    return resolved, sha_cache


def build_actions(resolved_rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """对每条已定最终名的 row 构建文件动作。返回 (actions, conflicts)。"""
    actions: list[dict] = []
    conflicts: list[dict] = []

    for row in resolved_rows:
        rel = row["rel"]
        old_name = row["old"]
        old_src = _ORGIN / rel
        old_stem = _safe_stem(old_name)

        if row["action"] == "dedup_drop":
            # 源移到 .dedup_archive/<rel父目录>/，保留 basename。
            # 关键：drop 常与 canonical 同名乱码源 → 共享同一套 stem 产物（扁平目录只一份）。
            # 那套产物属 canonical，不能移走，否则 canonical 重命名时找不到产物。
            # 故只移「drop 独有、canonical 不共享」的产物。
            canon_stem = _safe_stem(Path(row["canonical_rel"]).name)
            canon_products = {
                Path(p).resolve()
                for p in (_md_products(canon_stem) + _mineru_products(canon_stem))
            }
            arch_dir = _DEDUP_ARCHIVE / Path(rel).parent
            moves: list[tuple[str, str]] = [
                (str(old_src), str(arch_dir / old_name))
            ]
            for prod in _md_products(old_stem) + _mineru_products(old_stem):
                if prod.resolve() in canon_products:
                    continue  # 共享产物，归 canonical，不动
                moves.append((str(prod), str(arch_dir / prod.name)))
            actions.append({
                "type": "dedup_drop",
                "rel": rel, "old_name": old_name,
                "old_stem": old_stem,
                "rel_old": _rel_orgin(old_src),
                "sha": row["sha"], "canonical_rel": row["canonical_rel"],
                "renames": moves,
                "md_count": len(_md_products(old_stem)),
                "mineru_count": len(_mineru_products(old_stem)),
            })
            continue

        # rename
        new_name = row["final_name"]
        new_src = old_src.with_name(new_name)
        new_stem = _safe_stem(new_name)
        renames: list[tuple[str, str]] = [(str(old_src), str(new_src))]
        for md in _md_products(old_stem):
            renames.append((str(md), str(md.with_name(_rename_stem_in(md.name, old_stem, new_stem)))))
        for mp in _mineru_products(old_stem):
            renames.append((str(mp), str(mp.with_name(_rename_stem_in(mp.name, old_stem, new_stem)))))

        clash = [dst for src, dst in renames
                 if Path(dst).exists() and Path(src).resolve() != Path(dst).resolve()]
        if clash:
            conflicts.append({
                "rel": rel, "reason": "目标路径已存在(计划外既有文件)",
                "old": old_name, "new": new_name, "clash": clash[:3],
            })
            continue

        actions.append({
            "type": "rename",
            "rel": rel, "old_name": old_name, "new_name": new_name,
            "old_stem": old_stem, "new_stem": new_stem,
            "rel_old": _rel_orgin(old_src), "rel_new": _rel_orgin(new_src),
            "sha": row["sha"], "confidence": row.get("confidence"),
            "source": row.get("source"), "disambig": row.get("disambig", False),
            "renames": renames,
            "md_count": len(_md_products(old_stem)),
            "mineru_count": len(_mineru_products(old_stem)),
        })

    return actions, conflicts


def apply_actions(actions: list[dict], undo_path: Path) -> tuple[list[dict], dict]:
    undo: list[dict] = []
    stats = Counter()

    def _flush_undo():
        undo_path.write_text(json.dumps({"undo": undo}, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    # 先写空 undo，确保即使首个 rename 崩溃也有文件存在
    _flush_undo()

    try:
        for act in actions:
            for src, dst in act["renames"]:
                sp, dp = Path(src), Path(dst)
                if not sp.exists():
                    stats["skip_missing"] += 1
                    continue
                # 覆盖保护：目标已存在且不是 sp 自身（大小写不敏感盘上 samefile 也判同）→ 绝不覆盖
                if dp.exists():
                    try:
                        same = sp.samefile(dp)
                    except OSError:
                        same = False
                    if not same:
                        stats["skip_would_overwrite"] += 1
                        continue
                dp.parent.mkdir(parents=True, exist_ok=True)
                sp.rename(dp)
                undo.append({"from": dst, "to": src})
                stats[f"moved_{act['type']}"] += 1
                _flush_undo()  # 增量持久化：每步落盘，崩溃也可回滚
    except BaseException:
        _flush_undo()
        raise

    # source_index 更新
    idx_path = _MINERU_DIR / INDEX_FILENAME
    if idx_path.exists():
        data = json.loads(idx_path.read_text(encoding="utf-8"))
        by_path = data.get("by_path", {}) or {}
        by_hash = data.get("by_hash", {}) or {}

        for act in actions:
            if act["type"] == "dedup_drop":
                # 删 drop 源的 by_path 条目；by_hash[sha] 保留指向 canonical
                by_path.pop(act["rel_old"], None)
                stats["idx_dedup_path_removed"] += 1
                continue
            # rename
            rel_old, rel_new = act["rel_old"], act["rel_new"]
            old_stem, new_stem = act["old_stem"], act["new_stem"]
            old_name, new_name = act["old_name"], act["new_name"]
            if rel_old in by_path:
                by_path[rel_new] = by_path.pop(rel_old)
                stats["idx_by_path"] += 1
            for h, entry in by_hash.items():
                changed = False
                if entry.get("source") == old_name:
                    entry["source"] = new_name; changed = True
                if entry.get("stem", "").startswith(old_stem):
                    entry["stem"] = _rename_stem_in(entry["stem"], old_stem, new_stem); changed = True
                if entry.get("zip", "").startswith(old_stem):
                    entry["zip"] = _rename_stem_in(entry["zip"], old_stem, new_stem); changed = True
                if changed:
                    stats["idx_by_hash"] += 1

        data["by_path"] = by_path
        data["by_hash"] = by_hash
        tmp = idx_path.with_suffix(idx_path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(idx_path)
        stats["idx_saved"] = 1

    return undo, dict(stats)


def main() -> int:
    ap = argparse.ArgumentParser(description="乱码名归档全链重命名(自动消歧+去重)")
    ap.add_argument("--plan", default="/tmp/recover_final.json")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", default="/tmp/archive_report.json")
    ap.add_argument("--undo-out", default="/tmp/archive_undo.json")
    args = ap.parse_args()

    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    rows = plan["rows"]

    resolved, _ = resolve_final_names(rows)
    actions, conflicts = build_actions(resolved)

    renames = [a for a in actions if a["type"] == "rename"]
    dedups = [a for a in actions if a["type"] == "dedup_drop"]
    disambigs = [a for a in renames if a.get("disambig")]
    total_moves = sum(len(a["renames"]) for a in actions)

    report = {
        "mode": "apply" if args.apply else "dry-run",
        "plan_rows": len(rows),
        "rename_sources": len(renames),
        "disambiguated": len(disambigs),
        "dedup_dropped": len(dedups),
        "conflicts": conflicts,
        "total_file_moves": total_moves,
        "actions": actions,
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[mode] {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"计划: {len(rows)}  重命名源: {len(renames)}（其中消歧加后缀 {len(disambigs)}）")
    print(f"去重移归档: {len(dedups)} 个源  冲突跳过: {len(conflicts)}")
    print(f"总文件移动数(含产物): {total_moves}")
    if conflicts:
        print(f"  冲突: {dict(Counter(c['reason'] for c in conflicts))}")
    print(f"变更清单 → {args.report}")

    if not args.apply:
        print("\n(dry-run，未改任何文件。确认后加 --apply)")
        return 0

    undo, stats = apply_actions(actions, Path(args.undo_out))
    print(f"\n[applied] {stats}")
    print(f"回滚清单 → {args.undo_out}（{len(undo)} 条，全部可逆 move，增量落盘）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
