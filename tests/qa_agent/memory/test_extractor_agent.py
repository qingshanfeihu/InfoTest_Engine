"""extractor agent：5 turn 上限 + 互斥锁 + 静默失败。"""

from __future__ import annotations

from unittest import mock

from langchain_core.messages import AIMessage, HumanMessage

from main.qa_agent.memory import extractor_agent


def test_run_extractor_returns_empty_when_agent_none():
    out = extractor_agent.run_extractor(None, [HumanMessage(content="x")])
    assert out == ""


def test_run_extractor_swallows_invoke_exception():
    fake_agent = mock.MagicMock()
    fake_agent.invoke.side_effect = RuntimeError("model down")
    msgs = [HumanMessage(content="hi"), AIMessage(content="hello")]
    out = extractor_agent.run_extractor(fake_agent, msgs)
    assert out == ""


def test_run_extractor_passes_recursion_limit():
    """recursion_limit = max_turns * 2 + 4。"""
    fake_agent = mock.MagicMock()
    fake_agent.invoke.return_value = {
        "messages": [AIMessage(content="DONE: nothing")]
    }
    extractor_agent.run_extractor(
        fake_agent, [HumanMessage(content="x")], max_turns=5
    )
    config = fake_agent.invoke.call_args.kwargs.get("config") or fake_agent.invoke.call_args.args[1]
    assert config.get("recursion_limit") == 5 * 2 + 4


def test_run_extractor_extracts_last_ai_text():
    fake_agent = mock.MagicMock()
    fake_agent.invoke.return_value = {
        "messages": [
            HumanMessage(content="input"),
            AIMessage(content="thinking..."),
            AIMessage(content="DONE: appended preferences.md"),
        ]
    }
    out = extractor_agent.run_extractor(fake_agent, [HumanMessage(content="x")])
    assert out == "DONE: appended preferences.md"


def test_run_extractor_handles_list_content_blocks():
    fake_agent = mock.MagicMock()
    fake_agent.invoke.return_value = {
        "messages": [
            AIMessage(content=[
                {"type": "text", "text": "DONE: "},
                {"type": "text", "text": "noop"},
            ])
        ]
    }
    out = extractor_agent.run_extractor(fake_agent, [HumanMessage(content="x")])
    assert "DONE" in out
    assert "noop" in out


def test_run_extractor_mutex_lock_prevents_reentry():
    """同一时刻只允许一个 extractor 跑。"""
    holder = {"running": False, "second_called": False}

    def slow_invoke(payload, config=None):
        holder["running"] = True
        # 在持锁时再次调 run_extractor 应被拒
        out = extractor_agent.run_extractor(
            mock.MagicMock(invoke=lambda *a, **k: holder.__setitem__("second_called", True) or {"messages": []}),
            [HumanMessage(content="reentry")],
        )
        # 第二次应该早早返回空
        return {"messages": [AIMessage(content="DONE: ok")]}

    fake_agent = mock.MagicMock()
    fake_agent.invoke.side_effect = slow_invoke
    extractor_agent.run_extractor(fake_agent, [HumanMessage(content="x")])
    assert holder["running"] is True
    # 第二次嵌套调用没获取到锁，不会触发 invoke
    assert holder["second_called"] is False
