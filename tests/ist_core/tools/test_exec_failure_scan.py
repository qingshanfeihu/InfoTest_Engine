# -*- coding: utf-8 -*-
"""(43) ok(g) 谓词采集面扫描(§18.5;668030 空真实证驱动)。

markers 来自文法数据 exec_failure_markers(零硬编码);pass 案命中=空真嫌疑降
broken;fail 案命中=anomaly_lines 提取(独立共因对归因可见,坑#24 证据平权)。
"""
from __future__ import annotations

from main.ist_core.tools.device.batch_tools import _exec_failure_markers


def test_markers_loaded_from_grammar():
    m = _exec_failure_markers()
    assert m and any("Failed to execute" in x for x in m)


def _scan(detail: str, verdict: str):
    """复刻 digest 内联扫描逻辑的语义(单元锚;实现在 dev_run_batch_digest 循环内)。"""
    markers = _exec_failure_markers()
    anom = [ln.strip() for ln in detail.splitlines()
            if any(p in ln for p in markers)][:8]
    if anom and verdict == "pass":
        verdict = "broken"
    return verdict, anom


def test_pass_with_marker_demotes_to_broken():
    """668030 形态:恢复步失败+后续 not_found 空真'过'——pass 降 broken。"""
    log = ("step8: config all tftp ...\n"
           "Failed to get the file from tftp server\n"
           "Failed to execute the command\n"
           "#### Success Num 1: fail to find 172.16.34.70\n")
    verdict, anom = _scan(log, "pass")
    assert verdict == "broken"
    assert len(anom) == 2


def test_fail_with_marker_keeps_fail_extracts_anomaly():
    verdict, anom = _scan("RTNETLINK answers: File exists\n#### Fail Num 1", "fail")
    assert verdict == "fail" and anom


def test_clean_pass_untouched():
    verdict, anom = _scan("#### Success Num 1: successed to find x\n", "pass")
    assert verdict == "pass" and not anom
