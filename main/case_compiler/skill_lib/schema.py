"""归纳技能 frontmatter 扩展字段（SkillSpec + 校验）——技能库基建的依赖根。

设计契约（见 plan「Phase 0 / schema.py」+ `skill_lib/__init__.py` 已声明的公开 API）：

1. **复用现有 loader 的容忍性**：`loader.py::_parse_skill_md` 用 ``yaml.safe_load`` 读
   frontmatter，未知 key 静默忽略。归纳技能新增的 ``params`` / ``verify_script`` /
   ``evidence`` 对主 agent 运行时**完全 drop-in**。这里反过来做：``from_frontmatter``
   解析时也要**容忍人写技能无扩展字段**（config-answer / device-verify 等只有
   ``name`` / ``description`` / ``when_to_use`` / ``effort`` 等基础字段）。
2. **借 cc-haha 字段语义**：``version`` / ``effort`` / ``source`` / ``paths`` / ``shell`` /
   ``context`` / ``agent`` / ``user-invocable``（见 plan line 101-106）。
3. **内容寻址确定性**（抄 ``capability_snapshot.py``）：``content_hash()`` = 排序所有
   定义字段（**剔除 evidence/时间戳**——A-B evidence 随版本演进，不进技能内容指纹）→
   ``json.dumps(sort_keys=True)`` → sha256[:16]。同输入同 hash。

**红线**：本模块只做**确定性解析**（已知格式词法），不做意图/语义推断（那是检索器的
事）；不看 autoid，不逐 case 特化。质量契约/反模式拦截在 ``quality_contract.py``。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# cc-haha effort.ts:20 —— 低/中/高/极限四档（亦容忍 int，部分模型按数值预算）
VALID_EFFORTS: frozenset[str] = frozenset({"low", "medium", "high", "max"})
# cc-haha source 语义（bundled/user/project/plugin）+ 本地扩展（hand|induced 溯源）
VALID_SOURCES: frozenset[str] = frozenset(
    {"hand", "induced", "plugin", "bundled", "user", "project"}
)
# 合法 context（inline 注入主对话 / fork 走 subagent）
VALID_CONTEXTS: frozenset[str] = frozenset({"inline", "fork"})


def _as_bool(value: Any, *, default: bool = False) -> bool:
    """解析 frontmatter 布尔（true/yes/1/on）——与 loader._coerce_bool 同语义。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "on"}
    return default


def _as_str_list(value: Any) -> list[str]:
    """frontmatter 字段归一成 str 列表（容忍 str / list / None）。"""
    if value is None:
        return []
    if isinstance(value, str):
        # 逗号或空白分隔
        return [t.strip() for t in value.replace(",", " ").split() if t.strip()]
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


# ── 参数槽 ───────────────────────────────────────────────────────────


@dataclass
class ParamSlot:
    """LLM 只填这些参数槽（plan line 104 ``params``）。

    body 中以 ``$name`` / ``${name}`` 占位符出现；质量契约校验「槽位齐全」即检查
    声明的 name 是否在 body 出现、body 是否有未声明的硬值。
    """

    name: str
    description: str = ""
    required: bool = True
    example: str = ""

    @classmethod
    def from_spec(cls, name: str, spec: Any) -> "ParamSlot":
        """容忍多种声明形态：

        - ``pool_name: 池名``                         → description 字符串
        - ``pool_name: {description: .., required: ..}`` → 完整 dict
        - ``pool_name:``（None）                       → 仅声明名字
        """
        if isinstance(spec, dict):
            return cls(
                name=str(name),
                description=str(spec.get("description", "") or ""),
                required=_as_bool(spec.get("required"), default=True),
                example=str(spec.get("example", "") or ""),
            )
        if spec is None:
            return cls(name=str(name))
        return cls(name=str(name), description=str(spec))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "required": self.required,
            "example": self.example,
        }


def _parse_params(raw: Any) -> dict[str, ParamSlot]:
    """frontmatter ``params`` → {name: ParamSlot}（容忍 dict / list / None）。"""
    out: dict[str, ParamSlot] = {}
    if isinstance(raw, dict):
        for name, spec in raw.items():
            out[str(name)] = ParamSlot.from_spec(str(name), spec)
    elif isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, dict) and "name" in item:
                nm = str(item["name"])
                out[nm] = ParamSlot.from_spec(nm, item)
            elif isinstance(item, str) and item.strip():
                out[item.strip()] = ParamSlot(name=item.strip())
    return out


# ── A-B 闸记录 ───────────────────────────────────────────────────────


@dataclass
class ABTestRecord:
    """A-B 闸首跑对比记录（plan line 104 / 163-170）。

    with_/without_ 为「首跑通过 / 总数」；时间戳 ``ts`` **不进技能内容 hash**。
    """

    with_pass: int = 0
    with_total: int = 0
    without_pass: int = 0
    without_total: int = 0
    sample: list[str] = field(default_factory=list)  # held-out case autoid
    ts: float = 0.0
    insufficient_sample: bool = False

    @classmethod
    def from_dict(cls, d: Any) -> Optional["ABTestRecord"]:
        if not isinstance(d, dict):
            return None
        return cls(
            with_pass=int(d.get("with_pass", d.get("with", 0)) or 0),
            with_total=int(d.get("with_total", 0) or 0),
            without_pass=int(d.get("without_pass", d.get("without", 0)) or 0),
            without_total=int(d.get("without_total", 0) or 0),
            sample=_as_str_list(d.get("sample")),
            ts=float(d.get("ts", 0.0) or 0.0),
            insufficient_sample=_as_bool(d.get("insufficient_sample")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "with_pass": self.with_pass,
            "with_total": self.with_total,
            "without_pass": self.without_pass,
            "without_total": self.without_total,
            "sample": list(self.sample),
            "ts": self.ts,
            "insufficient_sample": self.insufficient_sample,
        }


@dataclass
class Evidence:
    """技能证据（plan line 104）：来源轨迹 + A-B 记录 + 迭代版本号。

    ``version`` 是**迭代计数器**（int），与 frontmatter 的 ``version``（str，技能版本）
    语义分离（见 plan 陷阱 7）。A-B evidence 绑 (content_hash, version) 元组追踪。
    """

    induced_from: list[str] = field(default_factory=list)  # 来源轨迹 autoid
    ab_test: Optional[ABTestRecord] = None
    version: int = 1
    risk: str = ""          # AWM 高风险类目标注（可选）
    degraded: bool = False  # health.py 劣化降级标记（可选）

    @classmethod
    def from_dict(cls, d: Any) -> "Evidence":
        if not isinstance(d, dict):
            return cls()
        return cls(
            induced_from=_as_str_list(d.get("induced_from")),
            ab_test=ABTestRecord.from_dict(d.get("ab_test")),
            version=int(d.get("version", 1) or 1),
            risk=str(d.get("risk", "") or ""),
            degraded=_as_bool(d.get("degraded")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "induced_from": list(self.induced_from),
            "ab_test": self.ab_test.to_dict() if self.ab_test else None,
            "version": self.version,
            "risk": self.risk,
            "degraded": self.degraded,
        }


# ── 技能规格 ─────────────────────────────────────────────────────────


@dataclass
class SkillSpec:
    """一条技能的结构化规格（frontmatter 扩展字段 + body）。

    ``content_hash()`` 是技能**定义**的内容指纹（剔除 evidence/时间戳）；registry 用它
    做内容寻址 + diff 增删改。``evidence.version`` 单独追踪演进。
    """

    name: str
    description: str = ""
    when_to_use: str = ""
    context: str = "inline"
    agent: str = ""
    user_invocable: bool = True
    effort: str = "medium"
    source: str = "hand"
    version: str = ""                 # frontmatter 技能版本（str；与 evidence.version 分离）
    shell: str = ""                   # cc-haha frontmatterParser.ts:57
    paths: list[str] = field(default_factory=list)   # glob 条件激活（cc-haha）
    params: dict[str, ParamSlot] = field(default_factory=dict)
    verify_script: str = ""           # 确定性校验脚本相对路径（纯离线可测）
    evidence: Evidence = field(default_factory=Evidence)
    body: str = ""
    skill_dir: Optional[Path] = None  # 物理目录（不进 hash）

    # ── 解析 ─────────────────────────────────────────────────────────

    @classmethod
    def from_frontmatter(
        cls,
        fm: dict[str, Any],
        body: str = "",
        skill_dir: Optional[Path] = None,
    ) -> "SkillSpec":
        """从 frontmatter dict 构建 SkillSpec。

        **容忍人写技能无扩展字段**：缺 ``params`` / ``verify_script`` / ``evidence`` 时
        取默认值，绝不抛异常（drop-in 双向）。未知 key 静默忽略（与 loader 一致）。
        """
        fm = fm if isinstance(fm, dict) else {}
        effort_raw = fm.get("effort", "medium")
        effort = str(effort_raw).strip().lower() if effort_raw is not None else "medium"
        return cls(
            name=str(fm.get("name", "") or "").strip(),
            description=str(fm.get("description", "") or ""),
            when_to_use=str(fm.get("when_to_use", "") or ""),
            context=str(fm.get("context", "inline") or "inline").strip().lower(),
            agent=str(fm.get("agent", "") or "").strip(),
            user_invocable=_as_bool(fm.get("user-invocable", fm.get("user_invocable")),
                                    default=True),
            effort=effort,
            source=str(fm.get("source", "hand") or "hand").strip().lower(),
            version=str(fm.get("version", "") or "").strip(),
            shell=str(fm.get("shell", "") or "").strip().lower(),
            paths=_as_str_list(fm.get("paths")),
            params=_parse_params(fm.get("params")),
            verify_script=str(fm.get("verify_script", "") or "").strip(),
            evidence=Evidence.from_dict(fm.get("evidence")),
            body=body or "",
            skill_dir=Path(skill_dir) if skill_dir is not None else None,
        )

    # ── 内容寻址 ──────────────────────────────────────────────────────

    def _canonical_payload(self) -> str:
        """用于 hash 的规范化内容：排序所有定义字段，**剔除 evidence/skill_dir**。

        A-B evidence 随版本演进，不进技能内容指纹（plan：hash 稳定、version 单独 bump）。
        """
        payload = {
            "name": self.name,
            "description": self.description,
            "when_to_use": self.when_to_use,
            "context": self.context,
            "agent": self.agent,
            "user_invocable": self.user_invocable,
            "effort": self.effort,
            "source": self.source,
            "version": self.version,
            "shell": self.shell,
            "paths": sorted(self.paths),
            "params": {k: self.params[k].to_dict() for k in sorted(self.params)},
            "verify_script": self.verify_script,
            "body": self.body,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def content_hash(self) -> str:
        return hashlib.sha256(
            self._canonical_payload().encode("utf-8")
        ).hexdigest()[:16]

    # ── 序列化 ────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "when_to_use": self.when_to_use,
            "context": self.context,
            "agent": self.agent,
            "user_invocable": self.user_invocable,
            "effort": self.effort,
            "source": self.source,
            "version": self.version,
            "shell": self.shell,
            "paths": list(self.paths),
            "params": {k: v.to_dict() for k, v in self.params.items()},
            "verify_script": self.verify_script,
            "evidence": self.evidence.to_dict(),
            "body": self.body,
            "content_hash": self.content_hash(),
        }

    # ── 轻量自检（结构合法性；语义/反模式归 quality_contract.py） ───────

    def basic_errors(self) -> list[str]:
        """结构合法性自检（不做反模式/语义判断）。返回错误列表，空=结构合法。"""
        errs: list[str] = []
        if not self.name:
            errs.append("missing name")
        if not self.description:
            errs.append("missing description")
        if self.context not in VALID_CONTEXTS:
            errs.append(f"invalid context: {self.context!r}")
        if self.source not in VALID_SOURCES:
            errs.append(f"invalid source: {self.source!r}")
        # effort 容忍 int 字符串或四档关键字
        if self.effort and self.effort not in VALID_EFFORTS and not self.effort.isdigit():
            errs.append(f"invalid effort: {self.effort!r}")
        # fork 技能必须声明 agent
        if self.context == "fork" and not self.agent:
            errs.append("fork skill missing agent")
        return errs


__all__ = [
    "SkillSpec",
    "ParamSlot",
    "Evidence",
    "ABTestRecord",
    "VALID_EFFORTS",
    "VALID_SOURCES",
    "VALID_CONTEXTS",
]
