"""测试 review-verification subagent 注册（Step 3）.

验证：
1. ``build_review_verification_subagent()`` 返回正确 CompiledSubAgent dict
2. ``build_main_agent()`` 后 subagents 列表含 ``review-verification``
3. prompt 包含 cc-haha verificationAgent 关键约束（"try to break it" /
   verification avoidance / "cannot self-assign" / VERDICT 行）

cc-haha 对照（已读 ``verificationAgent.ts:10-129``）：
- ``Your job is not to confirm... it's to try to break it``
- 强制 OUTPUT FORMAT（Verification command + Output observed）
- 末尾必须 ``VERDICT: PASS|FAIL|PARTIAL``
"""

from __future__ import annotations

import pytest


def test_build_review_verification_subagent_returns_compiled_dict(monkeypatch):
    """直接调 build_review_verification_subagent()，验证返回 CompiledSubAgent dict.

    本测试 mock LLM 工厂避免真实 DASHSCOPE_API_KEY 依赖.
    """

    class _StubModel:
        def bind_tools(self, tools, **kw):
            return self

        def invoke(self, *args, **kwargs):
            return None

    monkeypatch.setattr(
        "main.qa_agent.agents._llm.build_agent_chat_model",
        lambda *args, **kwargs: _StubModel(),
    )

    from main.qa_agent.agents.semantic_check_agent import (
        build_review_verification_subagent,
    )

    spec = build_review_verification_subagent()
    assert isinstance(spec, dict)
    assert spec["name"] == "review-verification"
    # CompiledSubAgent 关键字段
    assert "runnable" in spec, "CompiledSubAgent 必须含 runnable 字段（subagents.py:559）"
    assert "description" in spec
    # description 必须明确"主 agent 不能 self-assign"
    desc_lower = spec["description"].lower()
    assert "cannot self-assign" in desc_lower or "main agent cannot" in desc_lower


def test_review_verification_prompt_contains_cc_haha_anti_laziness_phrases():
    """prompt 必须含 cc-haha verificationAgent 的反偷懒措辞."""
    from main.qa_agent.agents import semantic_check_agent

    prompt = semantic_check_agent._REVIEW_VERIFICATION_PROMPT

    # cc-haha verificationAgent.ts:10 原文
    assert "try to break it" in prompt

    # cc-haha verificationAgent.ts:12 verification avoidance
    assert "verification avoidance" in prompt.lower()

    # cc-haha 反偷懒：reading is not verification（可能含换行）
    normalized = " ".join(prompt.lower().split())
    assert "reading is not verification" in normalized

    # cc-haha verificationAgent.ts:81 强制输出格式
    assert "Verification command" in prompt
    assert "Output observed" in prompt

    # cc-haha verificationAgent.ts:117-127 末尾 verdict 行
    assert "VERDICT:" in prompt
    assert "LEVEL:" in prompt   # InfoTest_Engine 适配：评审场景额外加 P0-P7

    # InfoTest_Engine 特有：bucket discipline
    assert "Bucket discipline" in prompt
    assert "qa/Test List" in prompt


def test_review_verification_prompt_forbids_subagent_recursion():
    """verifier 自己不能调 task / 子 agent（避免递归）."""
    from main.qa_agent.agents import semantic_check_agent

    prompt = semantic_check_agent._REVIEW_VERIFICATION_PROMPT
    assert "不许用" in prompt
    # 列举禁用工具
    assert "task" in prompt.lower()


def test_main_agent_registers_review_verification_subagent(monkeypatch):
    """build_main_agent() 后 subagents 列表必须含 review-verification.

    策略：mock ``deepagents.create_deep_agent`` 在它真正被调用前——必须在
    main_agent 函数内 ``from deepagents import create_deep_agent`` 之前
    就 monkeypatch ``sys.modules['deepagents']``。
    """
    import sys

    # mock LLM build 工厂避免真实 API 调用
    class _StubModel:
        def bind_tools(self, tools, **kw):
            return self

        def invoke(self, *args, **kwargs):
            return None

    monkeypatch.setattr(
        "main.qa_agent.agents._llm.build_agent_chat_model",
        lambda *args, **kwargs: _StubModel(),
    )
    monkeypatch.setattr(
        "main.qa_agent.agents._llm.build_explore_model",
        lambda *args, **kwargs: _StubModel(),
    )

    # 捕获 create_deep_agent 收到的 subagents
    captured: dict = {}

    def _capture_create_deep_agent(**kwargs):
        captured.update(kwargs)
        return _StubModel()

    # 直接修改 sys.modules['deepagents'] 让 build_main_agent 函数内的
    # ``from deepagents import create_deep_agent`` 拿到我们的 mock
    deepagents_mod = sys.modules.get("deepagents")
    if deepagents_mod is None:
        import deepagents as deepagents_mod
    monkeypatch.setattr(
        deepagents_mod, "create_deep_agent", _capture_create_deep_agent,
    )

    from main.qa_agent.agents.main_agent import build_main_agent
    build_main_agent()

    # subagents kwarg 应有 review-verification + explore
    assert "subagents" in captured, "subagents kwarg 应被 build_main_agent 传入"
    subagent_names = [s["name"] for s in captured["subagents"]]
    assert "explore" in subagent_names
    assert "review-verification" in subagent_names, (
        f"review-verification subagent 未注册；实际有: {subagent_names}"
    )
