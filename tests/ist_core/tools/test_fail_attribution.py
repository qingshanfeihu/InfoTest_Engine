"""V3 步骤5：fail 机械预判（fail_attribution）。

2026-07-02 收缩重写：预判只认**一个协议级事实**——设备语法拒绝标记 ``^``。
曾经的瞬态/E/G marker 关键字表已删（强字典猜语义，实证两类误归：裸 "dig" 把配置
被拒抢归 E；"timed out" 把配置错的下游超时归瞬态不回流）。其余 fail 一律
undetermined——device_context 原文交给 LLM 归因。
"""

from __future__ import annotations

from main.ist_core.tools.device.fail_attribution import (
    attribute_fail, AttributionResult, attribute_file_crash,
    has_device_syntax_caret, caret_rejected_commands,
)


# ── ^ 语法拒绝：唯一的机械 G 判定 ─────────────────────────────────────────

_CARET_CTX = (
    'APV(config)#sdns pool cname "pool_cname" "target.autotest.com"\n'
    'sdns pool cname "pool_cname" "target.autotest.com" \n'
    '               ^\n'
    'APV(config)#sdns host pool "autotest.com" "pool_cname"\n'
    'The pool "pool_cname" does not exist.\n'
    'Failed to execute the command\n'
    'dig @172.16.34.70 autotest.com cname +time=2 +tries=1\n'
    ';; connection timed out; no servers could be reached\n'
)


def test_caret_rejection_is_g_even_with_downstream_noise():
    """有 ^（设备语法拒绝）→ G，确定无疑——即使 context 同时含 dig 输出、
    timed out、does not exist 等下游后果文本（实证 994928：旧 marker 表把它抢归 E）。"""
    r = attribute_fail(_CARET_CTX)
    assert r.layer == "G"
    assert r.reflow is True and r.target_layer == "G"
    assert "^" in r.reason and "下游" in r.reason
    assert "sdns pool cname" in r.reason        # 被拒命令原文进 reason（给证据）


def test_caret_helpers():
    assert has_device_syntax_caret(_CARET_CTX)
    assert not has_device_syntax_caret("dig output\nANSWER: 1.2.3.4\n")
    cmds = caret_rejected_commands(_CARET_CTX)
    assert cmds and "sdns pool cname" in cmds[0]


# ── 无 ^：一律 undetermined，不做关键字猜测 ────────────────────────────────

def test_no_caret_returns_undetermined_not_keyword_guess():
    """dig 超时/无解析/SSH 字样都不再触发关键字预归因——原文交给 LLM。"""
    for ctx in (
        ";; connection timed out; no servers could be reached",   # 旧表会误判瞬态/E
        "#### Fail Num 1: fail to find \\b1.2.3.4\\b in: ANSWER 5.6.7.8",  # 旧表默认 V
        "ssh connection reset by peer",                            # 旧表判瞬态
        "The pool \"p1\" does not exist.\nFailed to execute the command",  # 旧表判 G(关键字)
    ):
        r = attribute_fail(ctx)
        assert r.layer == "undetermined", ctx
        assert "device_context" in r.reason      # 指路看原文
        assert "瞬态" in r.reason                # 给瞬态判定标准（复现≠瞬态），不替 LLM 下结论


def test_undetermined_carries_provenance_target_as_hint():
    r = attribute_fail("some fail detail", failing_assertion_layer="V")
    assert r.layer == "undetermined" and r.target_layer == "V"
    r2 = attribute_fail("some fail detail", failing_assertion_layer="X")
    assert r2.target_layer == ""                 # 非法层不透传


def test_render():
    g = AttributionResult("G", "设备语法拒绝(^)", reflow=True, target_layer="G")
    assert "[G]" in g.render() and "回流→G层" in g.render()
    u = AttributionResult("undetermined", "未预判", reflow=True, target_layer="")
    assert "待归因" in u.render() or "回流与否待归因后定" in u.render()


# ── 文件级崩溃签名（确定性事实，保留）────────────────────────────────────

def test_file_crash_found_times_recognized():
    """found_times() missing 崩溃签名 → 识别为编译缺陷，指引重编改 found/abs_found。"""
    tb = ("E   TypeError: found_times() missing 1 required positional argument: 'times'\n"
          "test_xlsx.py:304")
    hit = attribute_file_crash(tb)
    assert hit is not None
    name, guide = hit
    assert name == "found_times"
    assert "重编" in guide and ("found" in guide or "abs_found" in guide)
    assert "框架 bug" in guide  # 明确说明非框架 bug（这是 main 最易归因错处）


def test_file_crash_unknown_signature_returns_none():
    """未识别的崩溃签名 → None（交由泛型 unknown 处理，不硬套 found_times）。"""
    assert attribute_file_crash("SomeOther: RuntimeError boom") is None
    assert attribute_file_crash("") is None
