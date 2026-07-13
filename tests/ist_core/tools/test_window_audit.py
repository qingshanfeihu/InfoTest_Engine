"""oracle 残差门(§18.10 窗口出处对账,2026-07-14 run18-20 实弹驱动)。

实弹背景:框架 read_until 读窗在异常回显(^ 拒绝/慢响应)下整体错位,断言在错误窗口上
求值——3 run 清点:假 FAIL 7 起(对齐响应块含期望值却判 fail)、假 PASS 12 起(not_found
判过但块含该值),668000 假 PASS 三连已写回先例+footprint(投毒)。全部集中写保存族。
本门=异构冗余:pty 原始流按提示符旁路重分段,与框架窗口做方向对账;矛盾=采集面失真,
verdict 降 broken(第三态,挡写回/归因/s₀ 配对)。fixture 全部取自 run20 真实形态。
"""
from __future__ import annotations

from main.ist_core.tools.device.batch_tools import _apv_blocks, _window_audit


# run20 668015 真实形态的最小化 apv 会话
APV_FALSE_FAIL = """clear slb all

APV(config)#no sdns listener
IP address

APV(config)#no sdns on
no sdns on
       ^

APV(config)#sdns on

APV(config)#sdns listener 172.16.34.70 53
Warning: This IP/port pair may already be occupied by an SLB virtual service. Please check and confirm.

APV(config)#show sdns listener
sdns listener 172.16.34.70

APV(config)#write file sdns_file_save_015
"""

# 对应的框架步骤日志:check 窗里装的是上一条命令的 Warning(真实失真形态)
INNER_FALSE_FAIL = """2026-07-14 04:33:41 172.16.35.70 - sends command in config: sdns listener 172.16.34.70 53
2026-07-14 04:33:45 172.16.35.70 - sends command in config: show sdns listener
2026-07-14 04:33:45 #### Fail Num 1: fail to find 172\\.16\\.34\\.70 in:
2026-07-14 04:33:45 Warning: This IP/port pair may already be occupied by an SLB virtual service.
2026-07-14 04:33:45 APV(config)#show s
2026-07-14 04:33:45 #######   step6: 执行write file
"""


def test_apv_blocks_resegments_by_prompt():
    b = _apv_blocks(APV_FALSE_FAIL)
    assert "show sdns listener" in b
    assert "sdns listener 172.16.34.70" in b["show sdns listener"][0]
    assert "no sdns on" in b


def test_false_fail_detected():
    """found 判 fail 但对齐响应块含期望值 → false_fail 失真(668015/030 run20 形态)。"""
    dist, _ = _window_audit(INNER_FALSE_FAIL, {"apv_172.16.35.70.txt": APV_FALSE_FAIL})
    assert any(d["kind"] == "false_fail" and d["cmd"] == "show sdns listener"
               for d in dist)


def test_caret_rejection_becomes_anomaly():
    """响应块含裸 ^ 行=设备解析拒绝(G 族,闭合于设备解析器标记)→ 自身执行异常。"""
    _, caret = _window_audit(INNER_FALSE_FAIL, {"apv.txt": APV_FALSE_FAIL})
    assert any("syntax rejected (^): no sdns on" == a for a in caret)


def test_false_pass_detected():
    """not_found 判过但对齐块含该值 → false_pass(668000 三连假 PASS 形态,写回投毒防线)。"""
    inner = ("2026-07-14 04:33:10 172.16.35.70 - sends command in config: show sdns listener\n"
             "2026-07-14 04:33:10 #### Success Num 1: fail to find 172\\.16\\.34\\.70 in : \n")
    apv = "APV(config)#show sdns listener\nsdns listener 172.16.34.70\n\nAPV(config)#exit\n"
    dist, _ = _window_audit(inner, {"apv.txt": apv})
    assert any(d["kind"] == "false_pass" for d in dist)


def test_aligned_true_pass_no_distortion():
    """found 判过且对齐块确含期望值 → 零失真(真 PASS 不误伤)。"""
    inner = ("2026-07-14 04:30:19 172.16.35.70 - sends command in config: show sdns listener\n"
             "2026-07-14 04:30:19 #### Success Num 1: successed to find 172.16.34.70 in : \n")
    apv = "APV(config)#show sdns listener\nsdns listener 172.16.34.70\n\nAPV(config)#exit\n"
    dist, caret = _window_audit(inner, {"apv.txt": apv})
    assert dist == [] and caret == []


def test_kth_check_aligns_kth_block():
    """同命令多次:第 k 个 check 对齐第 k 个响应块(668000 正确范式:配置后 found=块1 有、
    恢复后 not_found=块2 无 → 双零失真)。"""
    inner = ("2026-07-14 04:33:00 172.16.35.70 - sends command in config: show sdns listener\n"
             "2026-07-14 04:33:00 #### Success Num 1: successed to find 172.16.34.70 in : \n"
             "2026-07-14 04:33:10 172.16.35.70 - sends command in config: show sdns listener\n"
             "2026-07-14 04:33:10 #### Success Num 2: fail to find 172\\.16\\.34\\.70 in : \n")
    apv = ("APV(config)#show sdns listener\nsdns listener 172.16.34.70\n\n"
           "APV(config)#config memory\n\nAPV(config)#show sdns listener\n\nAPV(config)#exit\n")
    dist, _ = _window_audit(inner, {"apv.txt": apv})
    assert dist == []


def test_dig_sourced_check_skipped():
    """源命令不在 apv 会话(dig/RouterA)→ 审计范围外,如实跳过不误报。"""
    inner = ("2026-07-14 04:32:01 RouterA - sends command in config: dig @172.16.34.70 a.test1\n"
             "2026-07-14 04:32:01 #### Fail Num 1: fail to find ANSWER[\\s\\S]*?172\\.16\\.35\\.213 in: \n")
    apv = "APV(config)#show version\nversion x\n\nAPV(config)#exit\n"
    dist, _ = _window_audit(inner, {"apv.txt": apv})
    assert dist == []


def test_bad_regex_pattern_falls_back_literal():
    """check 模式非法正则 → 字面包含兜底,不崩。"""
    inner = ("2026-07-14 04:33:00 172.16.35.70 - sends command in config: show x\n"
             "2026-07-14 04:33:00 #### Fail Num 1: fail to find [broken( in: \n")
    apv = "APV(config)#show x\n[broken( yes\n\nAPV(config)#exit\n"
    dist, _ = _window_audit(inner, {"apv.txt": apv})
    assert any(d["kind"] == "false_fail" for d in dist)
