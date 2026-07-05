"""Skill 标准包校验门(2026-07-04,对标 Anthropic Agent Skills 官方规范)。

依据 platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices:
frontmatter 必填 name(≤64,小写字母数字连字符)+ description(非空≤1024,禁 XML tag);
body ≤500 行;引用文件一层深且必须存在;skill 包内不放 tests/(pytest 从不收集
skill 包内测试——config-automation 曾挂着一份永不运行的"死测试")。

本项目扩展字段(loader 消费,同样机读校验):
- context: inline|fork —— 加载语义必须显式声明(inline=body 注入主对话;
  fork=渲染后交给 agents/<agent>.md 定义的子 agent)
- fork 必须带 agent 且 agents/<agent>.md 存在
- user-invocable: true 必须带 when_to_use(per-turn listing 的触发/SKIP 条件来源)

审计全文见 docs/AUDIT_skill_standard_alignment.md。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_SKILLS_DIR = _ROOT / "main" / "ist_core" / "skills"
_AGENTS_DIR = _ROOT / "main" / "ist_core" / "agents"

# B1(2026-07-05)连字符化完成:全部 skill 名已符合官方字符集,白名单清空。
# 旧下划线名经 loader.resolve_skill_dirname 别名互通(历史对话/旧脚本兼容)。
# 新 skill 禁止使用下划线名——本表保持为空。
_UNDERSCORE_NAME_GRANDFATHERED: set[str] = set()


def _iter_skill_mds() -> list[Path]:
    return sorted(_SKILLS_DIR.glob("*/SKILL.md"))


def _frontmatter_and_body(p: Path) -> tuple[dict, str]:
    text = p.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    assert m, f"{p.parent.name}: SKILL.md 缺 YAML frontmatter"
    fm = yaml.safe_load(m.group(1))
    assert isinstance(fm, dict), f"{p.parent.name}: frontmatter 不是 YAML 映射"
    return fm, m.group(2)


def test_skills_exist():
    assert len(_iter_skill_mds()) >= 10, "skills 目录异常(应有 10+ 个 SKILL.md)"


def test_frontmatter_name_and_description():
    seen: dict[str, str] = {}
    for p in _iter_skill_mds():
        fm, _ = _frontmatter_and_body(p)
        sk = p.parent.name
        name = str(fm.get("name") or "")
        desc = str(fm.get("description") or "")
        assert name, f"{sk}: 缺 name"
        assert len(name) <= 64, f"{sk}: name 超 64 字符"
        if name not in _UNDERSCORE_NAME_GRANDFATHERED:
            assert re.fullmatch(r"[a-z0-9-]+", name), (
                f"{sk}: name {name!r} 不合规——官方要求仅小写字母/数字/连字符。"
                "存量下划线名走 B1 协同重命名,新 skill 直接用连字符。")
        assert name not in seen, f"name 重复: {name}({sk} 与 {seen[name]})"
        seen[name] = sk
        assert desc.strip(), f"{sk}: 缺 description"
        assert len(desc) <= 1024, f"{sk}: description {len(desc)} 字符(官方≤1024)"
        assert not re.search(r"<[a-zA-Z][^>]*>", desc), f"{sk}: description 含 XML tag(官方禁止)"


def test_context_declared_and_fork_agent_resolves():
    for p in _iter_skill_mds():
        fm, _ = _frontmatter_and_body(p)
        sk = p.parent.name
        ctx = fm.get("context")
        assert ctx in ("inline", "fork"), (
            f"{sk}: context={ctx!r}——加载语义必须显式声明 inline 或 fork")
        if ctx == "fork":
            agent = str(fm.get("agent") or "")
            assert agent, f"{sk}: fork skill 缺 agent 引用"
            assert (_AGENTS_DIR / f"{agent}.md").is_file(), (
                f"{sk}: agent 引用不可解析——agents/{agent}.md 不存在")


def test_user_invocable_has_when_to_use():
    for p in _iter_skill_mds():
        fm, _ = _frontmatter_and_body(p)
        if fm.get("user-invocable") in (True, "true"):
            assert str(fm.get("when_to_use") or "").strip(), (
                f"{p.parent.name}: user-invocable 但缺 when_to_use——"
                "per-turn listing 靠它给出触发/SKIP 条件")


def test_body_size_and_reference_links():
    for p in _iter_skill_mds():
        _, body = _frontmatter_and_body(p)
        sk = p.parent.name
        n = body.count("\n") + 1
        assert n <= 500, f"{sk}: body {n} 行(官方≤500——拆 references/ 渐进披露)"
        # 引用的相对路径文件必须存在(官方:引用一层深、路径正斜杠)
        for ref in re.findall(r"\]\((?!https?://|#)([^)]+\.(?:md|py|json|txt))\)", body):
            assert "\\" not in ref, f"{sk}: 引用 {ref} 用了反斜杠(官方要求正斜杠)"
            assert (p.parent / ref).exists(), f"{sk}: 引用文件不存在 {ref}"


def test_no_tests_dir_inside_skill_packages():
    for p in _iter_skill_mds():
        assert not (p.parent / "tests").exists(), (
            f"{p.parent.name}: skill 包内不放 tests/(pytest 不收集,必成死测试;"
            "可执行物放 scripts/,真测试放顶层 tests/)")


def test_agent_definitions_have_metadata():
    mds = sorted(_AGENTS_DIR.glob("*.md"))
    assert mds, "agents 目录无定义"
    for p in mds:
        text = p.read_text(encoding="utf-8")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        assert m, f"agents/{p.stem}: 缺 frontmatter"
        fm = yaml.safe_load(m.group(1))
        for k in ("name", "description", "tools"):
            assert fm.get(k), (
                f"agents/{p.stem}: 缺 {k}"
                + ("(工具白名单必须显式声明,不默认全量)" if k == "tools" else ""))


def test_underscore_alias_resolution():
    """B1 别名兼容:旧下划线名(历史对话/旧脚本)经 loader 互通到连字符目录。"""
    from main.ist_core.skills.loader import resolve_skill_dirname
    assert resolve_skill_dirname("ist_compile") == "ist-compile"
    assert resolve_skill_dirname("ist_compile_grade") == "ist-compile-grade"
    assert resolve_skill_dirname("compile_worker") == "compile-worker"
    assert resolve_skill_dirname("ist-verify") == "ist-verify"          # 新名直通
    assert resolve_skill_dirname("no_such_skill") == "no_such_skill"    # 未知原样返回


def test_agent_bodies_have_role_task_rules_structure():
    """B2(2026-07-04):agent body 统一 <role>→<task>→<rules> 骨架。

    rules 收尾紧邻 $ARGUMENTS/brief 注入点(注意力最高位);这也是后续
    动态生成 agent 的模板契约——生成物过不了本门就不许派发。
    """
    for p in sorted(_AGENTS_DIR.glob("*.md")):
        body = p.read_text(encoding="utf-8")
        for tag in ("role", "task", "rules"):
            assert body.count(f"<{tag}>") == 1 and body.count(f"</{tag}>") == 1, (
                f"agents/{p.stem}: <{tag}> 缺失或未闭合(B2 骨架 role→task→rules)")
        assert body.index("<role>") < body.index("<task>") < body.index("<rules>"), (
            f"agents/{p.stem}: 骨架顺序漂移(应 role→task→rules)")
