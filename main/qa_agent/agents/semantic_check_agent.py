"""Backward-compat shim — review-verification 真源在 skills/review-verification/SKILL.md.

运行时由 ``main.qa_agent.skills.loader.load_fork_skills()`` 注册 subagent。
本模块仅保留测试/旧 import 用的符号。
"""

from __future__ import annotations

from pathlib import Path

_SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"
_SKILL_MD = _SKILLS_DIR / "review-verification" / "SKILL.md"


def _load_skill_body() -> str:
    text = _SKILL_MD.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return text


# 测试与文档引用：prompt 正文与 fork SKILL body 一致
_REVIEW_VERIFICATION_PROMPT = _load_skill_body()


def build_review_verification_subagent():
    """Deprecated: use load_fork_skills() instead."""
    from main.qa_agent.skills.loader import load_fork_skills

    for spec in load_fork_skills():
        if spec.get("name") == "review-verification":
            return spec
    raise RuntimeError("review-verification fork skill not loaded")


__all__ = [
    "build_review_verification_subagent",
    "_REVIEW_VERIFICATION_PROMPT",
]
