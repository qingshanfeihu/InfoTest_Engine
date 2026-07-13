"""s₀ 归因 echo-grounding(污点一修复,2026-07-13 run19 实弹驱动)。

run19@79:668030 被 s₀ 判「床污染,建议降级」,真相是自身命令写法(write all 撞交互 YES
→ 命令流错位)。根因:归因判据(_s0_pair)只看 IP 签名+卷面画像,不读完整回显;失败机理
「Failed to execute the command」在主设备会话 apv_70.txt,而 anomaly_lines 只扫断言摘要 d
→ 扫不到 → G6 免派深归因 → 误判 s₀。

修复三处协同:
① digest 侧 anomaly_lines 扫描范围含主设备完整会话(batch_tools,不只断言摘要);
② fetch_device_context_under 防中段截断(失败机理行优先保留);
③ diagnosis 事实落 echo_support(占用回显佐证=echo_confirmed / 无=necessity_only),
   题面据此校准语气——不做「验污染源 pass/fail」(理论反驳)。
"""
from __future__ import annotations

from main.ist_core.compile_engine_v8 import nodes as N


# ── echo_support 判定(正证:占用形态回显佐证)──────────────────────────────────

def test_echo_support_confirmed_on_occupancy_echo():
    """真实占用陈述(already exists/has been used)→ echo_confirmed(必要条件+回显佐证)。
    2026-07-14 出处更正:例行 advisory「may already be occupied…please check」不算正证
    (用户干净床实测:警告出现且配置成功)——文法负向已排除,见下一测试。"""
    rec = {"device_context": 'A configuration file named "sdns_file_save_030" already exists.\n'
                             "The list: adc has been used, please use another name"}
    assert N._echo_support(rec) == "echo_confirmed"


def test_echo_support_routine_advisory_is_not_occupancy():
    """例行 advisory(may already be occupied…Please check)≠占用陈述 → necessity_only。
    run18-20 实证:该警告在干净床上也出现且 listener 配置成功;它作 echo_confirmed 正证
    曾撑起 668015 的错误床污染强档题面。"""
    rec = {"device_context": "Warning: This IP/port pair may already be occupied by an "
                             "SLB virtual service. Please check and confirm."}
    assert N._echo_support(rec) == "necessity_only"


def test_echo_support_necessity_only_without_occupancy():
    """run19 型:回显无占用形态(668030 的失败是命令流错位,不是占用)→ necessity_only。"""
    rec = {"device_context": "write all file ...\nType \"YES\" to overwrite: no sdns listener\n"
                             "Write aborted by user. Failed to execute the command"}
    assert N._echo_support(rec) == "necessity_only"


def test_echo_support_no_echo_is_necessity_only():
    """无回显 → necessity_only(不猜)。"""
    assert N._echo_support({}) == "necessity_only"


# ── 负门:自身执行失败标记 → anomaly_lines 拦下,不误判 s₀(端到端形态)──────────

def test_exec_failure_in_device_context_scanned_as_anomaly():
    """echo-grounding 核心:主设备会话的执行失败标记必须被 exec_failure_markers 命中——
    这是 anomaly_lines 保留深归因(不免派 s₀)的输入。668030 的 'Failed to execute the
    command' 在完整回显里,修复前只扫断言摘要漏掉。"""
    from main.ist_core.tools.device.batch_tools import _exec_failure_markers
    markers = _exec_failure_markers()
    assert markers, "exec_failure_markers 文法数据缺失"
    # 668030 主设备会话的失败机理行
    dev_ctx = ("APV(config)#write all file sdns_file_save_030 test123\n"
               "A configuration file named \"sdns_file_save_030\" already exists.\n"
               "Type \"YES\" to overwrite: no sdns listener 172.16.34.70 53\n"
               "Write aborted by user.\nFailed to execute the command")
    hits = [ln for ln in dev_ctx.splitlines() if any(m in ln for m in markers)]
    assert hits, "主设备会话的执行失败标记未被 exec_failure_markers 命中(负门失效)"
    assert "Failed to execute the command" in hits[0]


# ── 题面语气据 echo_support 分档 ──────────────────────────────────────────────

def test_bed_question_hedges_when_necessity_only():
    """necessity_only → 题面提醒「也可能是本案自身命令写法,看完整回显」,不断言唯一根治。"""
    from main.ist_core.compile_engine_v8.engine_tool import _contradiction_question
    q = _contradiction_question({"autoid": "203601753067668030", "kind": "bed",
                                 "evidence": "upstream writer(s) touch shared state",
                                 "echo_support": "necessity_only"})
    assert "必要条件推断" in q["question"]
    assert "自身的命令写法" in q["question"] and "完整设备回显" in q["question"]


def test_bed_question_stronger_when_echo_confirmed():
    """echo_confirmed → 题面说「回显含占用形态直接佐证」,语气较强。"""
    from main.ist_core.compile_engine_v8.engine_tool import _contradiction_question
    q = _contradiction_question({"autoid": "203601753067668015", "kind": "bed",
                                 "evidence": "upstream writer(s) touch shared state",
                                 "echo_support": "echo_confirmed"})
    assert "回显含占用" in q["question"] and "直接佐证" in q["question"]


def test_bed_question_defaults_necessity_only():
    """缺 echo_support(旧事实)→ 默认 necessity_only(保守呈报)。"""
    from main.ist_core.compile_engine_v8.engine_tool import _contradiction_question
    q = _contradiction_question({"autoid": "203601753067668030", "kind": "bed",
                                 "evidence": "x"})
    assert "必要条件推断" in q["question"]


# ── 污点三:问询前提校验——diagnose 主体也有 anomaly 保护(与 G6 一致)──────────
def test_diagnose_main_body_anomaly_blocks_s0(monkeypatch):
    """diagnose 主体(G6 未覆盖案)判 s₀ 前:回显含自身执行失败(anomaly_lines)→ 不判 s₀。
    此前只有 G6 前筛有此门,主体缺 → 是 s₀ 误判缺口(污点三问询前提校验)。"""
    from main.ist_core.compile_engine_v8 import _shared as sh

    A = "203600000000000030"; PRED = "203600000000000000"
    # A(受害者,有自身执行失败) + PRED(前驱,有持久面写→_s0_pair 会命中)
    fs = [{"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
          {"ev": "merged", "aid": "", "volume": "v1", "composition": [PRED, A]},
          {"ev": "verdict", "aid": A, "result": "fail", "run_id": "r1", "ctx": "delivery",
           "artifact": "a1", "volume": "v1", "signatures": ["172.16.34.70"]}]
    monkeypatch.setattr(sh, "load_facts", lambda st: fs)
    monkeypatch.setattr(sh, "view", lambda st, f=None: {"cases": {
        A: {"status": "failed", "rounds": 1, "contradictions": 0}}})
    monkeypatch.setattr(sh, "manifest", lambda st: {"cases": [{"autoid": PRED}, {"autoid": A}]})
    monkeypatch.setattr(sh, "counts_update", lambda st, f=None: {})
    monkeypatch.setattr(sh, "emit", lambda t: None)
    appended = []
    monkeypatch.setattr(sh, "append", lambda st, facts: appended.extend(facts))
    # last_run:A 有自身执行失败 anomaly_lines
    monkeypatch.setattr(sh, "read_json", lambda p, d=None: (
        [{"autoid": A, "device_context": "…write all…",
          "anomaly_lines": ["Failed to execute the command"]}]
        if "last_run" in str(p) else (d if d is not None else [])))
    # PRED 卷面有持久面写(_s0_pair 命中);A 卷面普通
    monkeypatch.setattr(N, "_load_case_rows", lambda aid: (
        [{"E": "APV_0", "F": "cmd_config", "G": "write memory"}] if aid == PRED
        else [{"E": "APV_0", "F": "cmd_config", "G": "sdns listener 172.16.34.70 53"}]))
    monkeypatch.setattr(N, "_diag_grammar",
                        lambda: ([__import__("re").compile(r"write\s+memory", 2)], [], ([], [])))
    N.diagnose({"out_name": "b1", "last_run_ref": "outputs/b1/last_run.json"})
    diags = [f for f in appended if f.get("ev") == "diagnosis" and str(f.get("aid")) == A]
    # A 有自身执行失败 → 不判 h_s0(要么不落 diagnosis,要么非 h_s0)
    assert not any(d.get("h_position") == "h_s0" for d in diags), \
        "diagnose 主体应因 anomaly_lines 不判 s₀(自身执行失败非床污染)"


# ── 行级否定(run20 实证,2026-07-14):步骤描述横幅的「不存在」不得否决别行的真占用 ──

def test_echo_support_desc_banner_negation_does_not_veto():
    """668030 run20 形态:回显同时含 ①用例步骤描述横幅「恢复后应不存在」(意图文案,
    非设备输出) ②真实占用 Warning 行。否定是行内局部现象——横幅行的 '不存在' 不得
    全窗否决 Warning 行 → echo_confirmed。修前被错降 necessity_only(保守向,无害但错)。"""
    rec = {"device_context":
           "#######   step10: 验证sdns listener配置未被write all保存，恢复后应不存在\n"
           'A configuration file named "sdns_file_save_030" already exists.\n'
           "#### Fail Num 1: fail to find 172.16.34.70"}
    assert N._echo_support(rec) == "echo_confirmed"


def test_echo_support_same_line_negation_still_vetoes():
    """同一行内的否定仍然否决:'configuration file does not exist' 的 exist 是被否定的
    占用陈述本身,不得计为占用佐证。"""
    rec = {"device_context": "Error: configuration file sdns_save does not exist\n"
                             "#### Fail Num 1: fail to find"}
    assert N._echo_support(rec) == "necessity_only"


def test_occupancy_hit_line_scoped():
    """_occupancy_hit(共用核,_s0_pair 自扰分支同享)行级语义:负向行+正向行并存=命中。"""
    from main.ist_core.compile_engine_v8.nodes import _occupancy_hit
    assert _occupancy_hit("应不存在\nIP already occupied by SLB")
    assert not _occupancy_hit("file does not exist")


# ── G6 fix_direction 分档(2026-07-14 审计修:固定硬话是全清单唯一活措辞违例)──────

def test_g6_fix_direction_necessity_only_hedges():
    """necessity_only(假阳 20-26% 理论自认)→ 明说必要条件推断非确证,不说 sufficient。"""
    fx = N._g6_fix_direction("necessity_only", [{"via": "persistent-plane write"}])
    assert "necessary-condition inference" in fx and "NOT a confirmation" in fx
    assert "sufficient" not in fx


def test_g6_fix_direction_persist_polluter_drops_tail_placement():
    """持久面毒源:run11 实证排尾消不掉跨轮通路(_s0_pair 注释)→ 路线不含 tail placement。"""
    fx = N._g6_fix_direction("echo_confirmed", [{"via": "persistent-plane write"}])
    assert "direct corroboration" in fx
    assert "tail placement" not in fx


def test_g6_fix_direction_order_only_polluter_keeps_tail_placement():
    """纯卷序 L2/L3 毒源(无持久面):排尾仍是合法出路 → 路线保留。"""
    fx = N._g6_fix_direction("necessity_only", [{"via": "shared L2/L3 entity"}])
    assert "tail placement" in fx


# ── 意图盖章(P1c 证据源,author 派发时引擎侧落盘,worker 不可影响)────────────

def test_stamp_intent_writes_manifest_verbatim(tmp_path, monkeypatch):
    from main.ist_core.compile_engine_v8 import _shared as sh
    import json
    monkeypatch.setattr(sh, "manifest", lambda st: {"cases": [
        {"autoid": "203600000000000030",
         "title": "1.配置port 为53.执行write all后重启设备",
         "step_intents": [{"desc": "[check1]配置未被保存", "expected": ""}]}]})
    monkeypatch.setattr(sh, "outputs_root", lambda: tmp_path)
    N._stamp_intent("203600000000000030", {})
    d = json.loads((tmp_path / "203600000000000030" / "intent.json").read_text())
    assert d["title"].startswith("1.配置port 为53.执行write all")
    assert d["source"] == "manifest" and d["stamped_by"] == "engine.author"
