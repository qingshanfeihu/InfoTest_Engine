"""V3 步骤5：四层归因（fail_attribution）。"""

from __future__ import annotations

from main.ist_core.tools.device.fail_attribution import attribute_fail, AttributionResult


def test_transient_highest_priority():
    # 即使含 dig 字样，SSH 超时也优先判瞬态（不回流）
    r = attribute_fail("dig query failed: SSH connection timed out")
    assert r.layer == "transient"
    assert r.reflow is False
    assert r.target_layer == ""


def test_transient_variants():
    for d in ["SSH session dropped", "connection refused", "NXDOMAIN returned",
              "broken pipe", "EOF occurred in violation"]:
        assert attribute_fail(d).layer == "transient"


def test_e_layer_dig_no_answer():
    r = attribute_fail("dig returned no answer for the VIP")
    assert r.layer == "E"
    assert r.reflow is True
    assert r.target_layer == "E"


def test_g_layer_invalid_command():
    r = attribute_fail("% invalid command at sdns listener")
    assert r.layer == "G"
    assert r.target_layer == "G"


def test_g_layer_config_not_applied():
    r = attribute_fail("configuration failed: feature 未生效")
    assert r.layer == "G"


def test_v_layer_default_assertion_miss():
    # 有回显、无瞬态/E/G 信号 → V 错
    r = attribute_fail("check_point found 0 times, expected the backend ip but got different value")
    assert r.layer == "V"
    assert r.reflow is True
    assert r.target_layer == "V"


def test_v_layer_uses_provenance_target():
    # 断言不命中，但 provenance 标该断言其实依赖 G 段 → 回流目标用 provenance
    r = attribute_fail("assertion did not match output",
                       failing_assertion_layer="G")
    assert r.layer == "V"
    assert r.target_layer == "G"


def test_render():
    r = attribute_fail("SSH timeout")
    assert "transient" in r.render() and "不回流" in r.render()
    r2 = attribute_fail("dig no answer")
    assert "回流→E层" in r2.render()


def test_priority_e_over_g():
    # 同时含 E 和 G 信号，E 优先（先判可达性）
    r = attribute_fail("dig no answer; also % invalid command")
    assert r.layer == "E"
