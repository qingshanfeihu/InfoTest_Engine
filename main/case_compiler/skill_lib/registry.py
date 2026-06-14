"""技能库索引（内容寻址 sha256[:16] + diff + realpath dedup）。

**抄 ``capability_snapshot.py``** 的内容寻址范式：
- 每条技能 → ``SkillSpec.content_hash()``（剔除 evidence/时间戳，同定义同 hash）。
- 整库 → 按 (name → content_hash) 排序的 manifest → 库级 ``catalog_hash``。
- 落 ``runtime/skill_lib/<catalog_hash>.json`` + ``latest.json`` 指针（同 kp2_snapshot）。
- ``diff_registries`` 出技能集的增 / 删 / 改（hash 变）。

**借 cc-haha ``loadSkillsDir.ts:118-124`` realpath dedup**：扫描时把每个 SKILL.md 的
``realpath`` 规范化，同一真实文件（软链/重叠目录）只收一次，先到先得；同名不同文件
按 ``source`` 优先级裁决（induced 新版本胜 hand 旧版本，见 plan 陷阱 4）。

**确定性**：扫描顺序按 skill name 排序；hash 排序字段；无时间戳进 hash；无随机。
同一 skills 目录 → 同一 catalog。

**红线遵守**：本模块只做「发现 + 内容寻址 + diff」的通用机制，不看 autoid、不逐 case
特化、不做语义推断（意图判断归检索器，反模式拦截归 quality_contract）。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from main.case_compiler.skill_lib.schema import SkillSpec

logger = logging.getLogger(__name__)

# 仓库根（main/case_compiler/skill_lib/registry.py → parents[3] = repo root）
_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_SKILLS_DIR = _ROOT / "main" / "ist_core" / "skills"
_DEFAULT_REGISTRY_DIR = _ROOT / "runtime" / "skill_lib"

# source 覆盖优先级（数值大者胜）：induced 新归纳 > hand 人写 > 其余溯源类。
# 同名不同真实文件时用此裁决（plan 陷阱 4：inducted 新版本胜 hand 旧版本）。
_SOURCE_PRIORITY: dict[str, int] = {
    "induced": 3,
    "hand": 2,
    "project": 1,
    "user": 1,
    "plugin": 1,
    "bundled": 0,
}


def _source_rank(source: str) -> int:
    return _SOURCE_PRIORITY.get((source or "").strip().lower(), 0)


@dataclass
class RegistryEntry:
    """库中一条技能的索引项（spec + 物理溯源 + 内容指纹）。"""

    spec: SkillSpec
    content_hash: str
    real_path: str          # SKILL.md 的 realpath（dedup 键）
    skill_dir: str          # 技能目录（展示用）

    def to_dict(self) -> dict[str, Any]:
        d = self.spec.to_dict()
        d["real_path"] = self.real_path
        d["skill_dir"] = self.skill_dir
        return d


class SkillRegistry:
    """技能库索引：扫描 → 解析 → 内容寻址 → 落盘 / diff。

    用法::

        reg = SkillRegistry.scan()              # 扫默认 skills 目录
        reg = SkillRegistry.scan(some_dir)      # 扫自定目录（测试/插件）
        path = reg.save()                       # 落 runtime/skill_lib/<hash>.json + latest
        prev = SkillRegistry.load_latest()      # 读上一次快照
        report = SkillRegistry.diff(prev, reg)  # 增/删/改
    """

    def __init__(self, entries: Optional[dict[str, RegistryEntry]] = None):
        # name → RegistryEntry（name 唯一，dedup 后）
        self.entries: dict[str, RegistryEntry] = dict(entries or {})

    # ── 扫描 ─────────────────────────────────────────────────────────

    @classmethod
    def scan(
        cls,
        skills_dir: Optional[Path] = None,
        *,
        parser: Any = None,
    ) -> "SkillRegistry":
        """扫描 ``skills_dir`` 下所有 ``<name>/SKILL.md`` → SkillRegistry。

        - **realpath dedup**：同一真实文件只解析一次（软链/重叠目录），先到先得。
        - **同名裁决**：不同真实文件同 skill name → 按 source 优先级胜出（并列保留先到）。
        - 解析失败 / 结构非法（``basic_errors``）的技能跳过并 warning，不污染库。

        ``parser`` 默认用 loader._parse_skill_md（容忍注入测试桩）。
        """
        skills_dir = Path(skills_dir) if skills_dir is not None else _DEFAULT_SKILLS_DIR
        if parser is None:
            from main.ist_core.skills.loader import _parse_skill_md as parser

        entries: dict[str, RegistryEntry] = {}
        seen_realpaths: set[str] = set()

        if not skills_dir.is_dir():
            return cls(entries)

        # 确定性：按目录名排序遍历
        for sub in sorted(skills_dir.iterdir(), key=lambda p: p.name):
            if not sub.is_dir():
                continue
            skill_md = sub / "SKILL.md"
            if not skill_md.is_file():
                continue

            # realpath dedup（同真实文件只收一次）
            try:
                rp = str(skill_md.resolve())
            except OSError:
                rp = str(skill_md)
            if rp in seen_realpaths:
                logger.debug("skill_lib: skip duplicate realpath %s", rp)
                continue
            seen_realpaths.add(rp)

            parsed = parser(skill_md)
            if not parsed:
                logger.warning("skill_lib: failed to parse %s", skill_md)
                continue

            # 防御：合法 YAML 但非 mapping 的 frontmatter（如 bare list / scalar）
            # 只跳过单个技能并 warning，不让 from_frontmatter 在整库扫描时崩溃
            fm = parsed.get("frontmatter")
            if not isinstance(fm, dict):
                logger.warning("skill_lib: skip %s (frontmatter not a mapping: %s)",
                               skill_md, type(fm).__name__)
                continue

            spec = SkillSpec.from_frontmatter(
                fm,
                parsed.get("body") or "",
                sub,
            )
            errs = spec.basic_errors()
            if errs:
                logger.warning("skill_lib: skip %s (structural errors: %s)",
                               sub.name, "; ".join(errs))
                continue

            entry = RegistryEntry(
                spec=spec,
                content_hash=spec.content_hash(),
                real_path=rp,
                skill_dir=str(sub),
            )

            # 同 name 裁决：source 优先级高者胜；并列保留先到
            existing = entries.get(spec.name)
            if existing is not None:
                if _source_rank(spec.source) > _source_rank(existing.spec.source):
                    logger.info("skill_lib: %s overridden by source=%s (was %s)",
                                spec.name, spec.source, existing.spec.source)
                    entries[spec.name] = entry
                else:
                    logger.debug("skill_lib: keep existing %s (source=%s)",
                                 spec.name, existing.spec.source)
                continue

            entries[spec.name] = entry

        return cls(entries)

    # ── 内容寻址（库级） ──────────────────────────────────────────────

    def manifest(self) -> list[dict[str, str]]:
        """按 name 排序的 (name, content_hash, source) 清单——库级 hash 的输入。"""
        return [
            {
                "name": name,
                "content_hash": e.content_hash,
                "source": e.spec.source,
            }
            for name, e in sorted(self.entries.items())
        ]

    def catalog_hash(self) -> str:
        """整库内容指纹：排序 manifest → json → sha256[:16]。确定性。"""
        payload = json.dumps(self.manifest(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def names(self) -> list[str]:
        return sorted(self.entries)

    def get(self, name: str) -> Optional[RegistryEntry]:
        return self.entries.get(name)

    def __len__(self) -> int:
        return len(self.entries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_hash": self.catalog_hash(),
            "skills": {name: e.to_dict() for name, e in sorted(self.entries.items())},
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SkillRegistry":
        """从落盘 dict 还原（spec 字段重建；evidence/version 一并恢复）。"""
        entries: dict[str, RegistryEntry] = {}
        for name, sd in (d.get("skills") or {}).items():
            spec = _spec_from_dict(sd)
            entries[name] = RegistryEntry(
                spec=spec,
                content_hash=sd.get("content_hash") or spec.content_hash(),
                real_path=sd.get("real_path", ""),
                skill_dir=sd.get("skill_dir", ""),
            )
        return cls(entries)

    # ── 落盘 / 读取（抄 capability_snapshot.save_snapshot/load_latest） ──

    def save(self, registry_dir: Optional[Path] = None) -> Path:
        """落 ``<catalog_hash>.json`` + 更新 ``latest.json`` 指针。返回快照路径。"""
        registry_dir = Path(registry_dir) if registry_dir is not None \
            else _DEFAULT_REGISTRY_DIR
        registry_dir.mkdir(parents=True, exist_ok=True)
        h = self.catalog_hash()
        path = registry_dir / f"{h}.json"
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (registry_dir / "latest.json").write_text(
            json.dumps({"catalog_hash": h, "skill_count": len(self.entries)},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, catalog_hash: str,
             registry_dir: Optional[Path] = None) -> Optional["SkillRegistry"]:
        """按 catalog_hash 读快照（缺失→None）。"""
        registry_dir = Path(registry_dir) if registry_dir is not None \
            else _DEFAULT_REGISTRY_DIR
        f = registry_dir / f"{catalog_hash}.json"
        if not f.is_file():
            return None
        try:
            return cls.from_dict(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            logger.warning("skill_lib: failed to load registry %s", f)
            return None

    @classmethod
    def load_latest(cls,
                    registry_dir: Optional[Path] = None) -> Optional["SkillRegistry"]:
        """读 latest 指针指向的库快照（缺失→None）。"""
        registry_dir = Path(registry_dir) if registry_dir is not None \
            else _DEFAULT_REGISTRY_DIR
        ptr = registry_dir / "latest.json"
        if not ptr.is_file():
            return None
        try:
            h = json.loads(ptr.read_text(encoding="utf-8")).get("catalog_hash")
        except (OSError, json.JSONDecodeError):
            return None
        if not h:
            return None
        return cls.load(h, registry_dir)

    # ── diff（增 / 删 / 改） ──────────────────────────────────────────

    @staticmethod
    def diff(old: Optional["SkillRegistry"],
             new: "SkillRegistry") -> dict[str, Any]:
        """对比两库（按 name + content_hash）→ 增 / 删 / 改报告。

        - added：new 有、old 无。
        - removed：old 有、new 无。
        - changed：同 name、content_hash 变（含旧/新 hash 便于追踪）。
        ``old=None`` 视为空库（全部 added）。
        """
        old_entries = old.entries if old is not None else {}
        new_entries = new.entries

        added = sorted(n for n in new_entries if n not in old_entries)
        removed = sorted(n for n in old_entries if n not in new_entries)
        changed = []
        for n in sorted(set(old_entries) & set(new_entries)):
            oh = old_entries[n].content_hash
            nh = new_entries[n].content_hash
            if oh != nh:
                changed.append({"name": n, "old_hash": oh, "new_hash": nh})

        old_hash = old.catalog_hash() if old is not None else ""
        return {
            "catalog_changed": old_hash != new.catalog_hash(),
            "old_catalog_hash": old_hash,
            "new_catalog_hash": new.catalog_hash(),
            "added": added,
            "removed": removed,
            "changed": changed,
        }


def _spec_from_dict(sd: dict[str, Any]) -> SkillSpec:
    """落盘 dict → SkillSpec（重建 params/evidence；走 from_frontmatter 同一路径）。

    把序列化形态转回 frontmatter 形态喂给 ``from_frontmatter``，保证解析逻辑单一来源。
    """
    fm: dict[str, Any] = {
        "name": sd.get("name", ""),
        "description": sd.get("description", ""),
        "when_to_use": sd.get("when_to_use", ""),
        "context": sd.get("context", "inline"),
        "agent": sd.get("agent", ""),
        "user-invocable": sd.get("user_invocable", True),
        "effort": sd.get("effort", "medium"),
        "source": sd.get("source", "hand"),
        "version": sd.get("version", ""),
        "shell": sd.get("shell", ""),
        "paths": sd.get("paths", []),
        "params": sd.get("params", {}),
        "verify_script": sd.get("verify_script", ""),
        "evidence": sd.get("evidence"),
    }
    skill_dir = sd.get("skill_dir") or None
    return SkillSpec.from_frontmatter(
        fm,
        body=sd.get("body", ""),
        skill_dir=Path(skill_dir) if skill_dir else None,
    )


__all__ = [
    "SkillRegistry",
    "RegistryEntry",
]
