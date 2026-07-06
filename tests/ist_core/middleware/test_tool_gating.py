"""工具渐进披露 middleware 回归(C2,2026-07-05)。

守三件事:①默认关=零行为变化;②激活语义(invoke_skill 映射/既有使用粘性/
未知 skill fail-open);③审计验收量化——基础模式下可见工具 schema ≤35k 字符
(52k 常驻的根治项,防止将来加工具悄悄退化)。
"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import main.ist_core.middleware.tool_gating as tg
from main.ist_core.agents.main_agent import _default_generic_tools


def _mk_request(messages, tools):
    """最小 ModelRequest 替身:middleware 只碰 messages/tools/override。"""
    class _Req:
        def __init__(self, messages, tools):
            self.messages = messages
            self.tools = tools
        def override(self, **kw):
            r = _Req(self.messages, self.tools)
            for k, v in kw.items():
                setattr(r, k, v)
            return r
    return _Req(messages, tools)


def _filtered_names(monkeypatch, messages, enabled=True):
    monkeypatch.setenv("IST_TOOL_GATING_ENABLED", "1" if enabled else "0")
    tools = [t for t in _default_generic_tools()]
    req = _mk_request(messages, tools)
    out = tg.ToolGatingMiddleware()._filtered(req)
    return [getattr(t, "name", "") for t in out.tools]


def _ai_with_call(name, args=None):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args or {}, "id": "c1"}])


def test_explicit_off_is_passthrough(monkeypatch):
    names = _filtered_names(monkeypatch, [
        HumanMessage(content="随便聊聊"),
    ], enabled=False)
    all_names = [t.name for t in _default_generic_tools()]
    assert names == all_names


def test_default_is_enabled(monkeypatch):
    # 2026-07-05 翻默认(对照轮验收通过):不设 env 时 gating 生效,基础模式隐藏 gated 组。
    monkeypatch.delenv("IST_TOOL_GATING_ENABLED", raising=False)
    tools = [t for t in _default_generic_tools()]
    req = _mk_request([HumanMessage(content="随便聊聊")], tools)
    out = tg.ToolGatingMiddleware()._filtered(req)
    names = [getattr(t, "name", "") for t in out.tools]
    assert not any(n.startswith("compile_") or n.startswith("dev_") for n in names)


def test_fresh_conversation_hides_gated_groups(monkeypatch):
    names = _filtered_names(monkeypatch, [HumanMessage(content="评审这份用例")])
    assert "fs_read" in names and "invoke_skill" in names and "kb_footprint" in names
    assert not any(n.startswith("compile_") or n.startswith("dev_") or n.startswith("submit_")
                   for n in names), f"gated 工具泄漏: {names}"


def test_invoke_skill_activates_mapped_groups(monkeypatch):
    names = _filtered_names(monkeypatch, [
        HumanMessage(content="编译这批脑图"),
        _ai_with_call("invoke_skill", {"skill": "ist_compile", "brief": "…"}),
    ])
    assert "compile_prep" in names and "compile_fanout" in names
    assert "dev_run_batch_digest" in names   # ist_compile → compile+device


def test_review_skill_stays_base_only(monkeypatch):
    names = _filtered_names(monkeypatch, [
        _ai_with_call("invoke_skill", {"skill": "test-list-review", "brief": "…"}),
    ])
    assert "fs_grep" in names and "kb_bug_search" in names
    assert not any(n.startswith("compile_") for n in names)


def test_prior_gated_tool_use_is_sticky(monkeypatch):
    # 续聊/恢复线程:历史里已用过 dev_run_batch_digest → device 组不消失
    names = _filtered_names(monkeypatch, [
        ToolMessage(content="…", name="dev_run_batch_digest", tool_call_id="x"),
    ])
    assert "dev_run_batch" in names and "dev_probe" in names
    assert not any(n.startswith("compile_") for n in names)   # compile 仍隐藏


def test_unknown_skill_fails_open(monkeypatch):
    names = _filtered_names(monkeypatch, [
        _ai_with_call("invoke_skill", {"skill": "dyn-new-agent", "brief": "…"}),
    ])
    all_names = [t.name for t in _default_generic_tools()]
    assert names == all_names


def test_invoke_skill_unparseable_args_fails_open(monkeypatch):
    names = _filtered_names(monkeypatch, [
        _ai_with_call("invoke_skill", None),   # 参数缺失(截断)→ 保守全开
    ])
    all_names = [t.name for t in _default_generic_tools()]
    assert names == all_names


def test_dict_tools_untouched(monkeypatch):
    monkeypatch.setenv("IST_TOOL_GATING_ENABLED", "1")
    provider_tool = {"type": "web_search_20250305", "name": "dev_fake"}
    req = _mk_request([HumanMessage(content="hi")],
                      [provider_tool] + list(_default_generic_tools()))
    out = tg.ToolGatingMiddleware()._filtered(req)
    assert provider_tool in out.tools   # dict 型不参与过滤


def test_base_mode_schema_weight_within_budget(monkeypatch):
    """审计 C 验收:基础模式常驻工具 schema ≤35k 字符(修复前全量 52k+)。"""
    names = set(_filtered_names(monkeypatch, [HumanMessage(content="问答")]))
    total = 0
    for t in _default_generic_tools():
        if t.name not in names:
            continue
        desc = t.description or ""
        schema = ""
        if getattr(t, "args_schema", None):
            try:
                schema = json.dumps(t.args_schema.model_json_schema(), ensure_ascii=False)
            except Exception:  # noqa: BLE001
                pass
        total += len(desc) + len(schema)
    assert total <= 35_000, f"基础模式常驻 schema {total} 字符超预算(35k)"


def test_all_main_agent_skills_are_mapped_or_intentionally_absent():
    """_SKILL_GROUPS 覆盖 skills 目录全部 skill——新 skill 上架没配映射时,
    fail-open 兜底能用但费重量;本测提醒补映射(unknown→全量放行是安全网不是常态)。"""
    from pathlib import Path
    skills_dir = Path(tg.__file__).resolve().parents[1] / "skills"
    on_disk = {p.parent.name for p in skills_dir.glob("*/SKILL.md")}
    unmapped = on_disk - set(tg._SKILL_GROUPS)
    assert not unmapped, f"skill 未配激活映射(将走全量放行): {sorted(unmapped)}"
