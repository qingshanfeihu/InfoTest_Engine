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
    """run13 型:回显含占用语义(occupied/already)→ echo_confirmed(必要条件+回显佐证)。"""
    rec = {"device_context": "Warning: This IP/port pair may already be occupied by an "
                             "SLB virtual service. Please check and confirm."}
    assert N._echo_support(rec) == "echo_confirmed"


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
