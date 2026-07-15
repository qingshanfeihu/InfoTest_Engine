"""Ask 子系统 A 片验收(DESIGN §11.11 eval 断言①②③⑥ + token 映射 + 渲染泄漏)。

①空手问 schema 级不可能;②quote 非子串被拒且错误信息含最近似;
③panel 未答时 cap 必呈报之(二分);⑥挂起案跨批续跑恢复。
(④adopted 不写回、⑤同键第二批零 ask 属 B 片,随构件二/三/五落。)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from main.ist_core.compile_engine_v8 import _shared as sh
from main.ist_core.compile_engine_v8 import nodes as N
from main.ist_core.compile_engine_v8 import views as V
from main.ist_core.compile_engine_v8 import engine_tool as ET

A = "203600000000000001"
B = "203600000000000002"


# ── 工具层:submit_ask_panel 门(eval ①②) ────────────────────────────────────


@pytest.fixture()
def lr_fixture(tmp_path, monkeypatch):
    """outputs/<batch>/last_run.json + doc 文件(经 IST_SESSION_DIR 入多根沙箱)。"""
    batch = tmp_path / "outputs" / "b1"
    batch.mkdir(parents=True)
    lr = batch / "last_run.json"
    lr.write_text(json.dumps([{
        "autoid": A, "_round": 1,
        "device_context": ("AN(config)# slb real dns r1 10.1.1.1 53\n"
                           "Health check succeeded\nr1 10.1.1.1 UP"),
    }]), encoding="utf-8")
    doc = tmp_path / "manual.md"
    doc.write_text("`slb real dns <name> <ip> <port>` registers a real service.",
                   encoding="utf-8")
    monkeypatch.setenv("IST_SESSION_DIR", str(tmp_path))
    return lr, doc


def _call(lr, **over):
    from main.ist_core.tools.device.ask_panel import submit_ask_panel
    base = dict(last_run_path=str(lr), autoid=A,
                intent_signature="dns-real-registration",
                conflict_shape="manual_vs_device", version_family="10.5",
                hypothesis="以设备实测形态为准", ask="确认吗?")
    base.update(over)
    return submit_ask_panel.func(**base)


def _side_dev(quote="slb real dns r1 10.1.1.1 53"):
    return {"source_ref": "device_context", "quote": quote, "anchor": None}


def test_eval1_empty_handed_ask_impossible(lr_fixture):
    """①检索先于 ask:retrieval_receipt 空 → 工具层拒绝(schema 层 pydantic 同锁)。"""
    lr, _ = lr_fixture
    out = _call(lr, sides=[_side_dev(), _side_dev()], retrieval_receipt=[])
    assert out.startswith("error") and "retrieval_receipt" in out


def test_eval1_single_side_rejected(lr_fixture):
    lr, _ = lr_fixture
    out = _call(lr, sides=[_side_dev()],
                retrieval_receipt=[{"slug": "manual_declared", "outcome": "miss"}])
    assert out.startswith("error") and "sides" in out


def test_eval1_strict_schema_locks_nested_fields():
    """strict 转换后嵌套对象必须有 properties(空对象 schema 会让 LLM 无法传 side)。"""
    from main.ist_core.tools.device.ask_panel import submit_ask_panel
    from main.ist_core.agents._llm_strict import to_strict_tool, PER_TOOL_STRICT
    assert "submit_ask_panel" in PER_TOOL_STRICT
    d = to_strict_tool(submit_ask_panel)
    fn = d["function"]
    assert fn.get("strict") is True
    params = fn["parameters"]
    assert params.get("additionalProperties") is False
    items = params["properties"]["sides"]["items"]
    assert set(items["properties"]) == {"source_ref", "quote", "anchor"}
    assert set(items["required"]) == {"source_ref", "quote", "anchor"}
    outcome = params["properties"]["retrieval_receipt"]["items"]["properties"]["outcome"]
    assert set(outcome["enum"]) == {"miss", "hit_conflicting", "hit_adopted_blocked"}
    assert "$ref" not in json.dumps(params)


def test_hypothesis_field_no_preset_default(lr_fixture):
    """F1 面板不预设默认(定稿 §B / 判例血统 (45)):hypothesis 契约呈报三项平摆事实、
    不推荐某侧、不索取"哪侧该赢";机生同族 verified 注明非独立佐证。且中性面板仍可落盘。"""
    from main.ist_core.tools.device.ask_panel import AskPanelArgs
    desc = AskPanelArgs.model_fields["hypothesis"].description.lower()
    # 旧的"选边推荐"式索取措辞已去除
    assert "which side should win" not in desc and "should win" not in desc
    # 新契约:不预设默认 + 平摆 + 机生血统非独立佐证
    assert "do not preset a default" in desc
    assert "not independent corroboration" in desc
    ask_desc = AskPanelArgs.model_fields["ask"].description.lower()
    assert "neutral" in ask_desc and "favour one side" in ask_desc
    # 中性 hypothesis 的面板照常落盘(不因去默认而拒绝)
    lr, doc = lr_fixture
    out = _call(lr, sides=[
        _side_dev(),
        {"source_ref": str(doc), "quote": "slb real dns <name> <ip> <port>",
         "anchor": "v10.2"}],
        retrieval_receipt=[{"slug": "manual_declared", "outcome": "miss"}],
        hypothesis="手册记为注册；设备实测接受；前轮为机生卷、未独立验——三项并陈")
    assert out.startswith("ask panel filed")


def test_eval2_paraphrased_quote_rejected_with_closest_line(lr_fixture):
    """②转述被拒且反馈含最近似行(poka-yoke 自纠素材)。"""
    lr, doc = lr_fixture
    out = _call(lr, sides=[_side_dev("slb real dns r1 was accepted"),
                           {"source_ref": str(doc),
                            "quote": "registers a real service", "anchor": "v10.2"}],
                retrieval_receipt=[{"slug": "manual_declared", "outcome": "miss"}])
    assert out.startswith("error") and "verbatim" in out
    assert "slb real dns r1 10.1.1.1 53" in out   # 最近似行原文


def test_record_vs_device_shape_requires_record_side(lr_fixture):
    """形态-侧别一致门:manual_vs_device 类差异,记载侧必须以原文出场——
    全 device 引文会让文档侧意图只活在 hypothesis 转述里(红线评审 P2 加固)。"""
    lr, _ = lr_fixture
    out = _call(lr, sides=[_side_dev(), _side_dev("r1 10.1.1.1 UP")],
                retrieval_receipt=[{"slug": "manual_declared", "outcome": "miss"}])
    assert out.startswith("error") and "record" in out


def test_eval2_doc_side_gate_and_filing(lr_fixture, tmp_path):
    """doc 侧 verbatim 同样把关;双侧通过 → 落盘全字段。"""
    lr, doc = lr_fixture
    out = _call(lr, sides=[
        _side_dev(),
        {"source_ref": str(doc), "quote": "slb real dns <name> <ip> <port>",
         "anchor": "v10.2"}],
        retrieval_receipt=[{"slug": "manual_declared", "outcome": "miss"}])
    assert out.startswith("ask panel filed")
    panel = json.loads((tmp_path / "outputs" / A / "ask_panel.json").read_text())
    assert panel["conflict_shape"] == "manual_vs_device"
    assert len(panel["sides"]) == 2 and panel["_round"] == 1
    assert panel["retrieval_receipt"][0]["outcome"] == "miss"


# ── 引擎层:ask 目标与 cap 二分(eval ③) ─────────────────────────────────────


def _fs_failed_with_panel(tmp_path, aid=A, answered=False):
    """构造:authored r1 → fail 裁决 → attribution reflow → ask_panel 事实(盘上有面板)。"""
    pdir = tmp_path / "outputs" / aid
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "ask_panel.json").write_text(json.dumps({
        "autoid": aid, "conflict_shape": "expected_vs_observed",
        # intent_signature/version_family 是 submit_ask_panel 落盘的必填字段(生产形态);
        # 缺它们会让 _latest_panel→write_adjudication 的判例键不全、静默 warning 失败——
        # fixture 补齐,让 confirm/correct 的判例写回(成对机制)可被真实验证
        "intent_signature": "sdns-host-method-delete", "version_family": "10.5",
        "sides": [{"source_ref": "device_context", "quote": "q1", "anchor": None},
                  {"source_ref": "m.md", "quote": "q2", "anchor": None}],
        "retrieval_receipt": [{"slug": "manual_declared", "outcome": "miss"}],
        "hypothesis": "按设备行为改预期", "ask": "确认吗?", "_round": 1,
    }), encoding="utf-8")
    fs = [
        {"ev": "authored", "aid": aid, "round": 1, "artifact": "art1"},
        {"ev": "verdict", "aid": aid, "run_id": "r1", "ctx": "delivery",
         "result": "fail", "artifact": "art1", "volume": "vol1", "signatures": ["s1"]},
        {"ev": "attribution", "aid": aid, "round": 1, "run_id": "r1",
         "layer": "V", "disposition": "reflow", "fix_direction": "x", "evidence": "e"},
        {"ev": "ask_panel", "aid": aid, "round": 1, "shape": "expected_vs_observed",
         "ref": str((pdir / "ask_panel.json"))},
    ]
    if answered:
        fs.append({"ev": "decision", "aid": aid, "question_id": f"panel:{aid}:1",
                   "answer": "预期以实机为准", "token": "correct"})   # 中性面板:用户裁决=correct(ruling 权威)
    return fs


def _vw(fs, aids=(A,)):
    manifest = {"cases": [{"autoid": a} for a in aids]}
    return V.batch_view(fs, manifest)


def test_panel_waiting_and_answer_clears(tmp_path):
    fs = _fs_failed_with_panel(tmp_path)
    vw = _vw(fs)
    assert sh.panel_waiting(fs, vw) == [A]
    fs2 = _fs_failed_with_panel(tmp_path, answered=True)
    assert sh.panel_waiting(fs2, _vw(fs2)) == []


def test_eval3_cap_bisection_panel_presented(tmp_path):
    """③cap_reached 且有未答 panel → 该案以 panel 题面呈报(cap 语境附注)。"""
    fs = _fs_failed_with_panel(tmp_path)
    fs.append({"ev": "cap_reached", "aid": A, "round": 3})
    vw = _vw(fs)
    t = sh.ask_targets({}, fs, vw)
    assert A in t["panel"] and A in t["cap"]
    # 节点侧 dedup 优先 panel;题面组装看 cap_reached 附注 —— 由渲染函数承接
    q = ET._contradiction_question({
        "autoid": A, "kind": "panel", "title": "", "cap_reached": True,
        "panel": {"conflict_shape": "expected_vs_observed", "sides": [],
                  "retrieval_receipt": [], "hypothesis": "h", "ask": "?"}})
    assert "轮次已用尽" in q["question"]


def test_eval3_cap_without_panel_is_engineering_report(tmp_path):
    """③无 panel 的封顶 → 工程故障呈报(证据附题面,选项=继续/挂起/停止)。"""
    fs = _fs_failed_with_panel(tmp_path, answered=True)
    fs.append({"ev": "cap_reached", "aid": A, "round": 3})
    vw = _vw(fs)
    t = sh.ask_targets({}, fs, vw)
    assert A not in t["panel"] and A in t["cap"]
    q = ET._contradiction_question({"autoid": A, "kind": "cap", "title": "",
                                    "rounds": 3, "evidence": "修法方向x", "prior_choices": []})
    assert "未收敛" in q["question"] and len(q["options"]) == 3


# ── 挂起/恢复(eval ⑥)与终态语义 ────────────────────────────────────────────


def test_eval6_suspended_resume_across_batches(tmp_path):
    """⑥挂起案本批不再问;新批(run_start)呈报恢复问询;resumed 解除挂起。"""
    fs = _fs_failed_with_panel(tmp_path, answered=True)
    fs.append({"ev": "suspended", "aid": A, "reason": f"panel:{A}:1"})
    vw = _vw(fs)
    assert vw["cases"][A]["status"] == V.S_SUSPENDED
    assert sh.suspended_resume_waiting(fs, vw) == []          # 同批:不打扰
    fs.append({"ev": "run_start", "aid": "", "seq": 2})       # 新批开工
    vw2 = _vw(fs)
    assert sh.suspended_resume_waiting(fs, vw2) == [A]        # 呈报恢复
    fs.append({"ev": "decision", "aid": A, "question_id": f"resume:{A}:1",
               "answer": "恢复处理", "token": "resume"})
    fs.append({"ev": "resumed", "aid": A, "of": f"resume:{A}:1"})
    vw3 = _vw(fs)
    assert vw3["cases"][A]["status"] != V.S_SUSPENDED         # 回活跃流
    assert sh.suspended_resume_waiting(fs, vw3) == []


def test_keep_suspended_stays_and_asks_again_next_batch(tmp_path):
    fs = _fs_failed_with_panel(tmp_path, answered=True)
    fs += [{"ev": "suspended", "aid": A, "reason": "q1"},
           {"ev": "run_start", "aid": "", "seq": 2},
           {"ev": "decision", "aid": A, "question_id": f"resume:{A}:1",
            "answer": "保持挂起", "token": "keep"},
           {"ev": "suspended", "aid": A, "reason": f"keep:resume:{A}:1"}]
    vw = _vw(fs)
    assert vw["cases"][A]["status"] == V.S_SUSPENDED
    assert sh.suspended_resume_waiting(fs, vw) == []          # 本批已答
    fs.append({"ev": "run_start", "aid": "", "seq": 3})       # 再下一批
    assert sh.suspended_resume_waiting(fs, _vw(fs)) == [A]    # 再次询问


def test_user_confirmed_defect_is_terminal():
    """用户确认产品缺陷 = 合法终态(§11.7 telos 的唯一非 excel 结果)。"""
    fs = [{"ev": "authored", "aid": A, "round": 1, "artifact": "art1"},
          {"ev": "attribution", "aid": A, "round": 99, "layer": "product_defect",
           "disposition": "defect_candidate", "evidence": "user",
           "fix_direction": "user confirmed"}]
    assert _vw(fs)["cases"][A]["status"] == V.S_TERMINAL


def test_attributor_self_judged_defect_not_terminal():
    """归因器自判 defect_candidate 非终态(引擎安排换形态轮;user 来源才终态)。"""
    fs = [{"ev": "authored", "aid": A, "round": 1, "artifact": "art1"},
          {"ev": "verdict", "aid": A, "run_id": "r1", "ctx": "delivery",
           "result": "fail", "artifact": "art1", "volume": "v1", "signatures": []},
          {"ev": "attribution", "aid": A, "round": 1, "run_id": "r1",
           "layer": "product_defect", "disposition": "defect_candidate",
           "evidence": "dev quote", "fix_direction": "x"}]
    assert _vw(fs)["cases"][A]["status"] == V.S_FAILED


# ── 问询节点:token 落账与自动挂起(安全件) ───────────────────────────────────


def test_ask_node_auto_suspends_when_unanswered(tmp_path, monkeypatch):
    """非交互/面板取消 → 自动挂起带反馈,案离开活跃流(不空转不悬置)。"""
    fs = _fs_failed_with_panel(tmp_path)
    facts_file = tmp_path / "outputs" / "b1" / "facts.jsonl"
    facts_file.parent.mkdir(parents=True, exist_ok=True)
    from main.ist_core.compile_engine_v8 import facts as F
    F.append_facts(facts_file, fs)
    state = {"out_name": "b1",
             "facts_ref": str(facts_file.relative_to(sh.project_root()))
             if str(facts_file).startswith(str(sh.project_root())) else ""}
    monkeypatch.setattr(sh, "outputs_root", lambda: tmp_path / "outputs")
    monkeypatch.setattr(sh, "facts_path", lambda s: facts_file)
    monkeypatch.setattr(sh, "manifest", lambda s: {"cases": [{"autoid": A}]})
    monkeypatch.setattr(N, "interrupt", lambda payload: {})   # 未答
    out = N.ask_contradiction(state)
    fs2 = F.load_facts(facts_file)
    assert any(f.get("ev") == "suspended" and f.get("aid") == A
               and str(f.get("reason", "")).startswith("auto:") for f in fs2)
    dec = [f for f in fs2 if f.get("ev") == "decision" and f.get("aid") == A
           and f.get("token") == "suspend"]
    assert dec and "auto-suspended" in str(dec[0].get("note", ""))
    assert out["n_ask_contradiction"] == 0                    # 不再空转


def test_ask_node_panel_confirm_lands_token(tmp_path, monkeypatch):
    fs = _fs_failed_with_panel(tmp_path)
    facts_file = tmp_path / "outputs" / "b1" / "facts.jsonl"
    facts_file.parent.mkdir(parents=True, exist_ok=True)
    from main.ist_core.compile_engine_v8 import facts as F
    F.append_facts(facts_file, fs)
    monkeypatch.setattr(sh, "outputs_root", lambda: tmp_path / "outputs")
    monkeypatch.setattr(sh, "facts_path", lambda s: facts_file)
    monkeypatch.setattr(sh, "manifest", lambda s: {"cases": [{"autoid": A}]})
    # 判例写回重定向到 tmp（默认写 repo knowledge/adjudications/，测试不得污染）
    import main.ist_core.tools.knowledge.adjudication_store as adj_store
    adj_dir = tmp_path / "adjudications"
    monkeypatch.setattr(adj_store, "adjudications_root", lambda: adj_dir)
    captured = {}

    def _fake_interrupt(payload):
        captured.update(payload)
        return {A: "预期以实机为准"}

    monkeypatch.setattr(N, "interrupt", _fake_interrupt)
    N.ask_contradiction({"out_name": "b1"})
    kinds = {c["autoid"]: c["kind"] for c in captured.get("cases", [])}
    assert kinds.get(A) == "panel"
    item = next(c for c in captured["cases"] if c["autoid"] == A)
    assert item["panel"]["hypothesis"] == "按设备行为改预期"   # 面板全文进 payload
    fs2 = F.load_facts(facts_file)
    # 中性面板:选"预期以实机为准"→ correct(裁决=意图最高权威;confirm 因 Z 中性化已退役)
    dec = [f for f in fs2 if f.get("ev") == "decision" and f.get("token") == "correct"]
    assert dec and dec[0]["question_id"] == f"panel:{A}:1"
    # 成对机制护栏:correct 裁决必落判例(下批同键免问)。panel 缺 intent_signature/
    # version_family 时 write_adjudication 会静默 warning 失败——fixture 补齐后此断言守住它
    assert list(adj_dir.glob("*.md")), "correct 裁决未写回判例(write_adjudication 静默失败=成对机制半断)"


def test_answer_token_privilege_words_short_command_only():
    """特权词只对短指令生效:长句里的「挂起/停止」是叙述,按题面默认走(P3 加固)。"""
    assert N._answer_token("panel", "挂起") == "suspend"
    assert N._answer_token("panel", "挂起该案") == "suspend"
    assert N._answer_token("panel", "停止该案") == "stop"
    assert N._answer_token("panel", "不要挂起,预期结果按手册第三章的写法来") == "correct"
    assert N._answer_token("cap", "不要停止该案,换个思路继续修") == "continue"
    assert N._answer_token("env", "确认环境问题,停止该案") == "stop"


# ── 渲染层:内部术语零泄漏(G 门与 §11.11 中文题面要求) ────────────────────────


def test_question_rendering_no_internal_terms_leak(tmp_path):
    for kind in ("panel", "cap", "env", "contra", "suspended"):
        q = ET._contradiction_question({
            "autoid": A, "kind": kind, "title": "标题", "rounds": 3,
            "contradictions": 2, "evidence": "依据文本", "prior_choices": [],
            "cap_reached": False,
            "panel": {"conflict_shape": "expected_vs_observed",
                      "sides": [{"source_ref": "device_context", "quote": "q"}],
                      "retrieval_receipt": [{"slug": "s", "outcome": "miss"}],
                      "hypothesis": "h", "ask": "?"}})
        text = q["question"] + " ".join(o["label"] + o["description"] for o in q["options"])
        for term in ("env_blocked", "reflow", "disposition", "attribution", "panel",
                     "cap_reached", "S_", "frozen", "rerun_isolated", "token"):
            assert term not in text, (kind, term)
        assert len(q["header"]) <= 12


def test_panel_rendering_no_preset_default_option():
    """S2-HIGH(#21;定稿 §B/(45)(46)):ask_panel 中性化后渲染层同步去预设首选项——
    面板不渲"引擎的理解"、无"确认按此继续"默认项;两选项各指一侧(实机为准/缺陷)对称呈报;
    confirm/defect token 仍有效(下游 briefs/adjudication 不变)。成对机制跨所有权补齐。"""
    q = ET._contradiction_question({
        "autoid": A, "kind": "panel", "title": "",
        "panel": {"conflict_shape": "manual_vs_device",
                  "sides": [{"source_ref": "device_context", "quote": "no-op-still-there"},
                            {"source_ref": "manual.md", "quote": "该命令用于删除"}],
                  "retrieval_receipt": [{"slug": "s", "outcome": "hit_conflicting"}],
                  "hypothesis": "手册记为删除;实机为 no-op;前轮机生未独立验——三项并陈",
                  "ask": "该以哪一方为准?"}})
    labels = [o["label"] for o in q["options"]]
    # 去"引擎的理解"标 + 去"确认按此继续"默认首选项(失所指的成对机制)
    assert "引擎的理解" not in q["question"]
    assert "确认,按此继续" not in labels and not any("按此继续" in l for l in labels)
    assert not q["header"].startswith("确认")             # header 也不再隐含 confirm-default
    # 两侧对称呈报:实机侧 + 手册侧(缺陷)各一选项;双源 verbatim 都进题面(平摆)
    assert any("实机" in l for l in labels) and any("缺陷" in l for l in labels)
    assert "no-op-still-there" in q["question"] and "该命令用于删除" in q["question"]
    # token 下游有效:correct(裁决=意图最高权威,Z 中性后取代 confirm)/ defect
    toks = set((q.get("_tokens") or {}).values())
    assert "correct" in toks and "defect" in toks
    # 中性化后 confirm(按呈报理解 Z 编)退役——面板不再产 confirm token
    assert "confirm" not in toks
