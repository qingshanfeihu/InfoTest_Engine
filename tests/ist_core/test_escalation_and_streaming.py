"""升级末轮(effort=max + 全回显 brief + 逐轮归档)+ fork 翻流式(停滞守卫/finish_reason)
+ footbar 最大深度思考中——2026-07-07 本轮改动的机读断言。

覆盖纯函数/可注入单元;并发流式稳定性与守卫真生效走实跑验证(不在单测)。
"""
from __future__ import annotations

import types


# ------------------------------------------------- F: ForkExecutor._limits_for
def test_limits_for_max_bumps_both_walls():
    from main.ist_core.resilience import AdaptiveLimiter, ForkExecutor
    fe = ForkExecutor(AdaptiveLimiter(1, 1, 4))
    base_wall, base_trans = fe._limits_for("")
    high_wall, high_trans = fe._limits_for("high")
    max_wall, max_trans = fe._limits_for("max")
    # 非 max:基础值(600/1200 默认)
    assert base_wall == high_wall == fe.wallclock_s
    assert base_trans == high_trans == fe.transient_wallclock_s
    # max:两层都放宽,且重试窗口 ≥ 单次墙钟(容得下一次完整 max 单跑)
    assert max_wall > base_wall
    assert max_trans >= max_wall


def test_limits_for_max_env_override(monkeypatch):
    from main.ist_core.resilience import AdaptiveLimiter, ForkExecutor
    monkeypatch.setenv("IST_FORK_WALLCLOCK_MAX_S", "999")
    monkeypatch.setenv("IST_FORK_TRANSIENT_WALLCLOCK_MAX_S", "1500")
    fe = ForkExecutor(AdaptiveLimiter(1, 1, 4))
    wall, trans = fe._limits_for("max")
    assert wall == 999.0 and trans == 1500.0


# ---------------------------------------------- C: _build_brief 末轮全回显 vs 轻量
def _brief(case_led, max_rounds=3):
    from main.ist_core.compile_engine.nodes.compile_phase import _build_brief
    state = {"manifest_ref": "m.json", "product_version": "v1", "max_rounds": max_rounds}
    return _build_brief("209030000000000001", state, case_led, "out")


def test_build_brief_non_last_is_lightweight():
    b = _brief({"rounds_used": 0, "evidence_excerpt": "ONLY-LATEST"})
    assert "最后一次编写" not in b
    assert "ONLY-LATEST" in b          # 非末轮仍喂最新一轮证据


def test_build_brief_last_attempt_full_history():
    hist = [
        {"round": 0, "device_context": "ROUND0-DEV", "fix_direction": "FIX0",
         "layer": "E", "disposition": "reflow"},
        {"round": 1, "device_context": "ROUND1-DEV", "fix_direction": "FIX1",
         "layer": "", "disposition": ""},
    ]
    b = _brief({"rounds_used": 2, "fail_evidence": hist})
    for must in ("最后一次编写", "思考深度已升至 max", "ROUND0-DEV", "ROUND1-DEV",
                 "FIX0", "第0次", "第1次", "归因:E/reflow"):
        assert must in b, must


def test_build_brief_last_attempt_needs_history():
    # rounds_used 达阈值但无 fail 历史 → 不触发全回显(回落轻量)
    b = _brief({"rounds_used": 2})
    assert "最后一次编写" not in b


# ------------------------------------------------ B: _archive_round_config 逐轮归档
def test_archive_round_config(tmp_path, monkeypatch):
    from main.ist_core.compile_engine.nodes import verify_phase as vp
    aid = "209030000000000009"
    root = tmp_path / "outputs"
    (root / aid).mkdir(parents=True)
    (root / aid / "case.xlsx").write_bytes(b"CFG-R1")
    monkeypatch.setattr(vp.sh, "outputs_root", lambda: root)

    vp._archive_round_config(aid, 1)
    arch = root / aid / "history" / "case.r1.xlsx"
    assert arch.is_file() and arch.read_bytes() == b"CFG-R1"

    # 覆盖新版后再归档 r2,r1 保留(前几次配置不丢)
    (root / aid / "case.xlsx").write_bytes(b"CFG-R2")
    vp._archive_round_config(aid, 2)
    assert (root / aid / "history" / "case.r2.xlsx").read_bytes() == b"CFG-R2"
    assert (root / aid / "history" / "case.r1.xlsx").read_bytes() == b"CFG-R1"


def test_archive_round_config_no_source_is_noop(tmp_path, monkeypatch):
    from main.ist_core.compile_engine.nodes import verify_phase as vp
    monkeypatch.setattr(vp.sh, "outputs_root", lambda: tmp_path)
    vp._archive_round_config("209030000000000009", 1)   # 无 case.xlsx,静默不抛
    assert not (tmp_path / "209030000000000009" / "history").exists()


# ------------------------------------------ D2: footbar 最大深度思考中
def test_payloads_have_max_thinking():
    from main.ist_core.ink.components.ist_app import _payloads_have_max_thinking
    running_hi = {"kind": "fork", "status": "running", "effort": "high"}
    running_max = {"kind": "fork", "status": "running", "effort": "max"}
    done_max = {"kind": "fork", "status": "ok", "effort": "max"}
    assert _payloads_have_max_thinking([running_hi]) is False
    assert _payloads_have_max_thinking([running_hi, running_max]) is True
    assert _payloads_have_max_thinking([done_max]) is False   # 已结束不算


def test_engine_bottom_line_max_thinking_tail():
    from main.ist_core.ink.components.ist_app import _render_engine_bottom_line
    p = {"kind": "engine", "run": "dongkl", "phase": "worker_fanout",
         "round": 2, "total": 4, "counts": {"produced": 1}}
    assert "最大深度思考中" not in _render_engine_bottom_line(p)
    assert "最大深度思考中" in _render_engine_bottom_line(p, max_thinking=True)


# ------------------------------------------ H: finish_reason 终止信号
def _chunk(*, gen_info=None, resp_meta=None):
    msg = types.SimpleNamespace(response_metadata=resp_meta or {})
    return types.SimpleNamespace(generation_info=gen_info, message=msg)


def test_chunk_finish_reason_reads_both_sources():
    from main.ist_core.agents._llm import _get_chat_openai_with_reasoning
    cls = _get_chat_openai_with_reasoning()
    assert cls._chunk_finish_reason(_chunk(gen_info={"finish_reason": "stop"})) == "stop"
    assert cls._chunk_finish_reason(_chunk(resp_meta={"finish_reason": "tool_calls"})) == "tool_calls"
    assert cls._chunk_finish_reason(_chunk()) == ""


def test_verify_finish_enabled_toggle(monkeypatch):
    from main.ist_core.agents._llm import _get_chat_openai_with_reasoning
    cls = _get_chat_openai_with_reasoning()
    monkeypatch.delenv("IST_LLM_VERIFY_FINISH", raising=False)
    assert cls._verify_finish_enabled() is True     # 默认开
    monkeypatch.setenv("IST_LLM_VERIFY_FINISH", "0")
    assert cls._verify_finish_enabled() is False


# ------------------------------------------ D2 数据面: reducer fork_start 带 effort
def test_reducer_fork_start_carries_effort():
    from main.ist_core.tui.reducer import MessageReducer
    r = MessageReducer()
    r._on_fork_cards({"payload": {"records": [
        {"event": "fork_start", "fork_id": "abc123", "skill": "compile-worker",
         "agent": "compile-worker", "effort": "max", "ts": 1.0}]}})
    snap = r.snapshot()
    idx = snap.fork_card_indices.get("fork:abc123")
    assert idx is not None, "fork_start 应建卡"
    payload = snap.messages[idx].content[0].payload
    assert payload.get("effort") == "max", "effort 应透传进卡片 payload(供 footbar 挂标)"


# ------------------------------------------ Fix4: 设备回显报告展示层清理
def test_clean_device_echo_strips_ts_and_collapses_blanks():
    from main.ist_core.compile_engine.nodes.closing import _clean_device_echo
    raw = ("=== 头 ===\n"
           "2026-07-07 23:30:08 172.16.35.70 - sends command in config: sdns pool p1\n"
           "\n\n"
           "2026-07-07 23:30:09 172.16.35.70 - show sdns pool\n")
    clean = _clean_device_echo(raw)
    assert "2026-07-07 23:30" not in clean          # 时间戳前缀剥掉
    assert "sends command in config: sdns pool p1" in clean
    assert "\n\n\n" not in clean                     # 连续空行折叠
    assert "=== 头 ===" in clean                     # 非时间戳行保留
    assert _clean_device_echo(raw, limit=10) == clean[:10]   # limit 截断
    # 原始不动(喂 LLM 归因的 device_context 保留时间戳=causality 照妖镜)
    assert "2026-07-07 23:30:08" in raw


# ------------------------- 布局门(2026-07-08 官方长上下文实践,PROMPT_ENGINEERING_STANDARD §一)
def test_build_brief_layout_data_top_instructions_last():
    """末轮 brief:首行机读信封;数据区(device_evidence)在前,intent 紧邻 round_task(指令)收尾。"""
    hist = [{"round": 1, "device_context": "DEV-CTX", "fix_direction": "FIX",
             "layer": "V", "disposition": "reflow"}]
    b = _brief({"rounds_used": 2, "fail_evidence": hist,
                "attribution": {"fix_direction": "HYP"}})
    assert b.splitlines()[0].lstrip().startswith("{")          # 机读信封首行
    order = ["<device_evidence>", "<prior_hypothesis", "<intent", "<round_task>"]
    pos = [b.find(t) for t in order]
    assert all(p >= 0 for p in pos[:1] + pos[-1:]), b[:200]
    present = [(t, p) for t, p in zip(order, pos) if p >= 0]
    assert [p for _, p in present] == sorted(p for _, p in present), present
    assert b.rstrip().endswith("</round_task>")                 # 指令收尾


def test_worker_skill_has_tail_examples_and_instructions_last():
    """worker SKILL:尾块 <examples> 存在;$ARGUMENTS(数据)在 <instructions>(指令)之前。"""
    from pathlib import Path
    body = (Path("main/ist_core/skills/compile-worker/SKILL.md")).read_text(encoding="utf-8")
    assert "<examples>" in body and "状态：produced" in body and "状态：needs_user_decision" in body
    assert body.find("$ARGUMENTS") < body.find("<instructions>")
    assert body.rstrip().endswith("</instructions>")
