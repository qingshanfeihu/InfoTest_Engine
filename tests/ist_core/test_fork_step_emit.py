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
           "--- device echo (via jumphost) ---\n"
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


def test_streamed_fork_emits_structured_events(monkeypatch):
    """卡片数据面:fork_id 非空时,步骤同步双写 .events.jsonl 结构化事件——
    tool 事件带累计 n_calls(自含幂等),tool_result 带 status+已剥信封 summary。"""
    events: list[dict] = []
    monkeypatch.setattr(loader, "_fork_emit", lambda t: None)
    monkeypatch.setattr(loader, "_fork_emit_event", lambda r: events.append(r))
    monkeypatch.setenv("IST_FORK_STEP_EMIT", "1")
    states = _states()

    class _R:
        def stream(self, inp, config=None, stream_mode=None):
            yield from states

    loader._invoke_fork_streamed(_R(), "body", "x", fork_id="fk1")
    kinds = [e["event"] for e in events]
    assert kinds == ["tool", "tool_result", "tool", "tool_result"]
    tools = [e for e in events if e["event"] == "tool"]
    assert [t["n_calls"] for t in tools] == [1, 2]
    assert tools[0]["tool"] == "compile_precedent" and tools[0]["arg"] == "persistence"
    results = [e for e in events if e["event"] == "tool_result"]
    assert all(e["fork_id"] == "fk1" and e["status"] == "ok" for e in results)
    assert "命中 3 条先例" in results[0]["summary"]


def test_streamed_fork_no_structured_events_without_fork_id(monkeypatch):
    events: list[dict] = []
    monkeypatch.setattr(loader, "_fork_emit", lambda t: None)
    monkeypatch.setattr(loader, "_fork_emit_event", lambda r: events.append(r))
    monkeypatch.setenv("IST_FORK_STEP_EMIT", "1")
    states = _states()

    class _R:
        def stream(self, inp, config=None, stream_mode=None):
            yield from states

    loader._invoke_fork_streamed(_R(), "body", "x")   # 默认 fork_id="" → 不发结构化事件
    assert events == []


def test_fork_usage_tally_instance_counters(monkeypatch):
    """per-fork tokens:实例计数与全局累计双写(fork_end 报本 fork 用量)。"""
    import main.ist_core.graph as g
    monkeypatch.setattr(g, "extract_llm_usage", lambda r: {
        "input_tokens": 100, "output_tokens": 7, "prompt_cache_hit_tokens": 40})
    before = loader.get_fork_tokens()
    t = loader._ForkUsageTally()
    t.on_llm_end(object())
    t.on_llm_end(object())
    assert t.tokens == [200, 14, 80]
    after = loader.get_fork_tokens()
    assert (after[0] - before[0], after[1] - before[1], after[2] - before[2]) == (200, 14, 80)


def test_fork_events_path_derivation(monkeypatch):
    monkeypatch.delenv("IST_EVIDENCE_LOG", raising=False)
    p = loader._fork_events_path()
    assert p.endswith(".events.jsonl") and f".{__import__('os').getpid()}." in p
    monkeypatch.setenv("IST_EVIDENCE_LOG", "/tmp/x/custom.live.log")
    assert loader._fork_events_path() == "/tmp/x/custom.events.jsonl"
    monkeypatch.setenv("IST_EVIDENCE_LOG", "/tmp/x/other.log")
    assert loader._fork_events_path() == "/tmp/x/other.log.events.jsonl"


def test_short_fork_result_strips_tool_envelope():
    """fork 挂 ToolEnvelopeMiddleware,ToolMessage 带 <tool_result> 信封——预览必须
    拆回 body,不把开标签原文泄漏进 TUI(实况:满屏 `<tool_result name=… status="ok">`)。"""
    from main.ist_core.middleware.tool_envelope import envelope_text
    ok = envelope_text("dev_probe", "Pool: p1  Members: 3")
    r = loader._short_fork_result(ok)
    assert "<tool_result" not in r
    assert "Pool: p1" in r
    # error 信封 → ✗ 前缀 + 原因可见
    err = envelope_text("compile_emit", "error: case X 步骤载荷为空——四通道都没传")
    re_ = loader._short_fork_result(err)
    assert "<tool_result" not in re_
    assert re_.startswith("✗ ") and "步骤载荷为空" in re_
    # JSON 结果包在信封里同样拆开后走 JSON 单行预览
    js = envelope_text("compile_score", '{\n  "overall": 0.0,\n  "decision": "CUT"\n}')
    rj = loader._short_fork_result(js)
    assert "<tool_result" not in rj and "overall=0.0" in rj and "decision=CUT" in rj


def test_short_fork_args_picks_representative_scalar():
    assert loader._short_fork_args({"query": "persistence"}) == "(persistence)"
    assert loader._short_fork_args({"path": "a/b.md", "extra": 1}) == "(a/b.md)"
    assert loader._short_fork_args({}) == ""
    # 无白名单键时回退第一个标量
    assert loader._short_fork_args({"weird": "val"}) == "(val)"
    # 超长截断
    assert loader._short_fork_args({"command": "x" * 100}) == "(" + "x" * 48 + ")"


def test_fork_end_evidence_collects_tail_and_freshness(tmp_path, monkeypatch):
    """P1-10 白跑判据采集(2026-07-17 实弹:035493/035570 ok:true 零产物零尾块,卡片
    假 ✓):tail_status=STATUS 尾块值(引擎 _TAIL_RE 同款语义);artifact_fresh=案卷
    mtime>=fork 开始-1s(引擎 fresh 判据同款)。纯机械采集,语义合取在渲染层。"""
    import time
    from main.ist_core.skills import loader

    # 把 outputs 根重定向到 tmp(loader 按 parents[3] 定位仓根,monkeypatch Path 不可行
    # ——直接在真实仓根的 workspace/outputs 下用超长测试 autoid,测完清理)
    aid = "209999999999990077"
    root = loader.Path(loader.__file__).resolve().parents[3]
    case_dir = root / "workspace" / "outputs" / aid
    case_dir.mkdir(parents=True, exist_ok=True)
    xlsx = case_dir / "case.xlsx"
    try:
        # ① 有尾块 + 新产物
        t0 = time.time() - 5
        xlsx.write_bytes(b"x")   # mtime=now > t0
        ev = loader._fork_end_evidence("...\nSTATUS: produced\n", aid, t0)
        assert ev["tail_status"] == "produced"
        assert ev["artifact_fresh"] is True
        # ② 零尾块 + 陈旧产物(mtime 早于 fork 开始)= 白跑形态
        ev2 = loader._fork_end_evidence("我觉得写完了(散文,无机读尾块)", aid,
                                        time.time() + 60)
        assert ev2["tail_status"] == ""
        assert ev2["artifact_fresh"] is False
        # ③ 无 autoid → 不带 artifact_fresh(渲染层不可判,不触发 ⚠)
        ev3 = loader._fork_end_evidence("STATUS: needs_user_decision", "", 0.0)
        assert ev3["tail_status"] == "needs_user_decision"
        assert "artifact_fresh" not in ev3
    finally:
        import shutil
        shutil.rmtree(case_dir, ignore_errors=True)
