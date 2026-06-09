"""LoopGuardMiddleware 单元测试：复现 run-335f888221dc 的死循环场景，验证护栏触发。

检测基于"最近 window 个工具调用 / 结果"的滑动窗口频次（非末尾连续），能抓住
A/B/A/B 交替空转，且模型改变行为后自然复位。
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from main.ist_core.middleware.loop_guard import (
    LoopGuardMiddleware,
    _analyze,
    _is_empty_result,
    _tool_call_fingerprint,
)


def _ai_with_tool_call(tc_id: str, name: str, args: dict) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"id": tc_id, "name": name, "args": args, "type": "tool_call"}],
    )


def _tool_result(tc_id: str, content: str) -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=tc_id)


class _Req:
    def __init__(self, messages):
        self.messages = messages

    def override(self, messages):
        return _Req(messages)


def test_fingerprint_stable_and_args_sensitive():
    a = _tool_call_fingerprint("qa_deepagent_grep", {"pattern": "slb real tcp", "path": "x"})
    b = _tool_call_fingerprint("qa_deepagent_grep", {"path": "x", "pattern": "slb real tcp"})
    c = _tool_call_fingerprint("qa_deepagent_grep", {"pattern": "slb real udp", "path": "x"})
    assert a == b  # key 顺序无关
    assert a != c  # 参数不同 → 指纹不同


def test_is_empty_result():
    assert _is_empty_result("(no matches)")
    assert _is_empty_result("")
    assert _is_empty_result("path not found: foo")
    assert not _is_empty_result("knowledge/data/markdown/product/cli.md:42: slb virtual http")


def test_is_empty_result_long_content_not_flagged():
    """Bug 5：长结果即便正文含 '未找到' 字样也不算空（避免假阳性）。"""
    long_text = "评审材料：" + "x" * 250 + " 这里提到未找到对应字段 no matches 仅是引用"
    assert len(long_text) > 200
    assert not _is_empty_result(long_text)


def test_dup_count_detected():
    """3 次完全相同的 grep → dup_count=3。"""
    msgs = [HumanMessage(content="把这段 F5 配置翻译成 APV")]
    for i in range(3):
        tc_id = f"call_{i}"
        msgs.append(_ai_with_tool_call(tc_id, "qa_deepagent_grep", {"pattern": "slb real tcp ", "path": "p"}))
        msgs.append(_tool_result(tc_id, "(no matches)"))
    stats = _analyze(msgs, window=8)
    assert stats["dup_count"] == 3
    assert stats["empty_count"] == 3
    assert "slb real tcp" in stats["dup_label"]


def test_alternating_loop_detected():
    """Bug 3：A/B/A/B 交替空转 —— 末尾连续法漏报，窗口频次法应抓到 A 出现 3 次。"""
    msgs = [HumanMessage(content="翻译配置")]
    pats = ["A", "B", "A", "B", "A"]
    for i, pat in enumerate(pats):
        tc_id = f"call_{i}"
        msgs.append(_ai_with_tool_call(tc_id, "qa_deepagent_grep", {"pattern": pat, "path": "p"}))
        msgs.append(_tool_result(tc_id, "(no matches)"))
    stats = _analyze(msgs, window=8)
    # A 出现 3 次 → dup_count>=3 触发，即使末尾是 A、A 前面是 B（不连续）
    assert stats["dup_count"] == 3


def test_empty_count_with_varying_queries():
    """关键词每次不同（不触发 dup），但窗口内空结果累积 → empty_count。"""
    msgs = [HumanMessage(content="翻译配置")]
    for i, pat in enumerate(["slb real tcp", "bindgroup", "slb virtual.*group", "slb class"]):
        tc_id = f"call_{i}"
        msgs.append(_ai_with_tool_call(tc_id, "qa_deepagent_grep", {"pattern": pat, "path": "p"}))
        msgs.append(_tool_result(tc_id, "(no matches)"))
    stats = _analyze(msgs, window=8)
    assert stats["dup_count"] == 1  # 各指纹只出现一次
    assert stats["empty_count"] == 4


def test_window_resets_on_behavior_change():
    """窗口滑动：早期重复调用滑出窗口后，dup_count 随之下降（模型改了行为）。"""
    msgs = [HumanMessage(content="翻译配置")]
    # 前 3 次重复 A，之后 8 次各不相同
    seq = ["A", "A", "A"] + [f"uniq{i}" for i in range(8)]
    for i, pat in enumerate(seq):
        tc_id = f"c{i}"
        msgs.append(_ai_with_tool_call(tc_id, "qa_deepagent_grep", {"pattern": pat, "path": "p"}))
        msgs.append(_tool_result(tc_id, f"hit {pat}"))
    stats = _analyze(msgs, window=8)
    # 最近 8 个调用里 A 已滑出（或仅剩 0-1 次），不再触发
    assert stats["dup_count"] < 3


def test_reminder_injected_on_dup(monkeypatch):
    monkeypatch.setenv("IST_LOOP_DUP_THRESHOLD", "3")
    mw = LoopGuardMiddleware()
    msgs = [HumanMessage(content="翻译 F5 配置")]
    for i in range(3):
        tc_id = f"c{i}"
        msgs.append(_ai_with_tool_call(tc_id, "qa_deepagent_grep", {"pattern": "bindgroup", "path": "p"}))
        msgs.append(_tool_result(tc_id, "(no matches)"))

    out = mw._maybe_reminder_messages(_Req(msgs))
    assert len(out) == len(msgs) + 1
    last = out[-1].content
    assert "loop-guard" in last
    assert "循环护栏" in last


def test_no_reminder_when_healthy():
    """正常推进（不同搜索 + 有命中）→ 不注入。"""
    mw = LoopGuardMiddleware()
    msgs = [HumanMessage(content="翻译配置")]
    msgs.append(_ai_with_tool_call("c0", "qa_deepagent_grep", {"pattern": "slb virtual http", "path": "p"}))
    msgs.append(_tool_result("c0", "cli.md:7212: slb virtual http knownsvc"))
    msgs.append(_ai_with_tool_call("c1", "qa_deepagent_grep", {"pattern": "slb group", "path": "p"}))
    msgs.append(_tool_result("c1", "cli.md:27: slb group method rr"))

    out = mw._maybe_reminder_messages(_Req(msgs))
    assert len(out) == len(msgs)  # 无注入


def test_last_human_index_skips_injected_reminders():
    """Bug 2：窗口起点应跳过带属性的 system-reminder / memory-context 注入消息。"""
    from main.ist_core.middleware.loop_guard import _last_human_index

    msgs = [
        HumanMessage(content="真实用户问题"),
        HumanMessage(content='<system-reminder data-source="loop-guard">提醒</system-reminder>'),
        HumanMessage(content="<memory-context>\n旧记忆\n</memory-context>"),
        HumanMessage(content="<system-reminder>\nskills\n</system-reminder>"),
    ]
    # 应回到下标 0（真实用户输入），跳过后三条注入
    assert _last_human_index(msgs) == 0


def test_disabled_via_env(monkeypatch):
    monkeypatch.setenv("IST_LOOP_GUARD_ENABLED", "0")
    mw = LoopGuardMiddleware()
    msgs = [HumanMessage(content="x")]
    for i in range(5):
        tc_id = f"c{i}"
        msgs.append(_ai_with_tool_call(tc_id, "qa_deepagent_grep", {"pattern": "same", "path": "p"}))
        msgs.append(_tool_result(tc_id, "(no matches)"))

    out = mw._maybe_reminder_messages(_Req(msgs))
    assert len(out) == len(msgs)  # 关闭后不注入
