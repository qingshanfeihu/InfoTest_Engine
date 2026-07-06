"""fork 运行过程可观测:execute_fork_skill 把 fork 内部每个工具调用实时发到主 bus。

修复前:fork 走阻塞 invoke,TUI 只看到编排层的"draft 第N轮",看不到 draft 在查什么命令、
怎么失败。改为 stream(stream_mode='values')逐 superstep 吐全量 state,新增 AIMessage 的
tool_calls 即时 emit 成 `↳ {tag}: {tool}({arg})`。IST_FORK_STEP_EMIT=0 退回 invoke。
"""

from __future__ import annotations

import main.ist_core.skills.loader as loader


def _states():
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    ai1 = AIMessage(content="", tool_calls=[
        {"name": "compile_precedent", "args": {"query": "persistence"}, "id": "1"}])
    ai2 = AIMessage(content="", tool_calls=[
        {"name": "fs_read", "args": {"path": "10.5_cli__part2.md"}, "id": "2"}])
    tm1 = ToolMessage(content="命中 3 条先例; top=CNAME会话保持 sim=0.82",
                      tool_call_id="1", name="compile_precedent")
    tm2 = ToolMessage(content="sdns host persistence <timeout> <netmask> ...",
                      tool_call_id="2", name="fs_read")
    final = AIMessage(content="xlsx: workspace/outputs/x/case.xlsx")
    h = HumanMessage(content="b")
    return [
        {"messages": [h]},
        {"messages": [h, ai1]},
        {"messages": [h, ai1, tm1, ai2]},
        {"messages": [h, ai1, tm1, ai2, tm2, final]},
    ]


def test_streamed_fork_emits_each_tool_call(monkeypatch):
    emitted: list[str] = []
    monkeypatch.setattr(loader, "_fork_emit", lambda t: emitted.append(t))
    monkeypatch.setenv("IST_FORK_STEP_EMIT", "1")
    states = _states()

    class _R:
        def stream(self, inp, config=None, stream_mode=None):
            yield from states

        def invoke(self, inp, config=None):
            return states[-1]

    result = loader._invoke_fork_streamed(_R(), "body", "532519 draft")

    assert result is states[-1], "最终 state 应等价 invoke 返回"
    joined = "\n".join(emitted)
    # 调用行
    assert "↳ 532519 draft: compile_precedent(persistence)" in joined
    assert "↳ 532519 draft: fs_read(10.5_cli__part2.md)" in joined
    # 结果预览行(让"查到什么"可见)
    assert "⤷ compile_precedent → 命中 3 条先例" in joined
    assert "⤷ fs_read → sdns host persistence" in joined
    # 2 调用 + 2 结果 = 4(最终纯文本 AIMessage 不发)
    assert len(emitted) == 4, f"应 2 调用 + 2 结果,实际 {emitted}"


def test_fallback_to_invoke_when_runnable_has_no_stream(monkeypatch):
    emitted: list[str] = []
    monkeypatch.setattr(loader, "_fork_emit", lambda t: emitted.append(t))

    class _OnlyInvoke:
        def invoke(self, inp, config=None):
            return {"messages": []}

    r = loader._invoke_fork_streamed(_OnlyInvoke(), "body", "x")
    assert r == {"messages": []}
    assert emitted == [], "无 .stream 时退回 invoke,不应有步骤 emit"


def test_disabled_emit_uses_invoke_not_stream(monkeypatch):
    monkeypatch.setenv("IST_FORK_STEP_EMIT", "0")
    calls = {"stream": 0, "invoke": 0}

    class _R:
        def stream(self, inp, config=None, stream_mode=None):
            calls["stream"] += 1
            yield {"messages": []}

        def invoke(self, inp, config=None):
            calls["invoke"] += 1
            return {"messages": []}

    loader._invoke_fork_streamed(_R(), "body", "x")
    assert calls["invoke"] == 1 and calls["stream"] == 0, "关步骤显示应走 invoke"


def test_short_fork_result_skips_banner_and_metadata_grabs_device_output():
    # dev_probe 真实格式:头部横幅 + command: 回显 + 分隔 + 设备回显。
    # 预览应跳过前三者,抓**设备回显**(用户要看的是查到什么,不是命令本身)。
    out = ("=== dev_probe ===\n"
           "command: show sdns pool name\n"
           "--- 设备回显(经跳转机)---\n"
           "Pool: cname_pool  Members: 2  Status: up")
    r = loader._short_fork_result(out)
    assert r == "Pool: cname_pool Members: 2 Status: up"
    assert "command:" not in r and "===" not in r
    # error 格式:跳过 command:/status: 抓错误行
    err = "=== dev_probe ===\ncommand: show x\nstatus: error\nconnection refused"
    assert loader._short_fork_result(err) == "connection refused"
    # 普通单行内容(footprint/precedent)不受影响
    assert loader._short_fork_result("命中 3 条先例") == "命中 3 条先例"
    # 整段皆横幅/元数据 → 回退第一非空行(不致空)
    assert loader._short_fork_result("=== x ===") != ""


def test_short_fork_args_picks_representative_scalar():
    assert loader._short_fork_args({"query": "persistence"}) == "(persistence)"
    assert loader._short_fork_args({"path": "a/b.md", "extra": 1}) == "(a/b.md)"
    assert loader._short_fork_args({}) == ""
    # 无白名单键时回退第一个标量
    assert loader._short_fork_args({"weird": "val"}) == "(val)"
    # 超长截断
    assert loader._short_fork_args({"command": "x" * 100}) == "(" + "x" * 48 + ")"
