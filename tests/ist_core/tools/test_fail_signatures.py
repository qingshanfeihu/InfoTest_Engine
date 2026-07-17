"""A1 · fail_signatures 结构化解析回归（B1+B2 双 bug 一刀 + 迁移条款）。

病灶实证（dongkl 批 9 案 4 案签名脏，778072 为活标本）：
- B1：``(causality or "") + (detail or "")`` 无分隔拼接 + 裸 grep，收进
  ``p2=== 框架逐步执行+断言明细+异常 (….txt) ===`` 型跨段假签名；
- B2：``#### Success Num 6: fail to find: p2``（**通过的** not_found 断言）按
  "fail to find" 词面被收进签名 → 778072 冻结判定语义反转；
- 漏收：``#### Fail Num N: successed to find: X``（not_found 断言失败）词面不含
  "fail to find"，旧 grep 漏掉。

fixture 保真自 workspace/outputs/dongkl/unfinished/778072 的 attr_evidence.json
回显形态（时间戳/汇总与逐步两形态/节头），对象名脱敏。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from main.ist_core.tools.device.batch_tools import (
    _fail_signatures,
    _fail_signatures_legacy,
    normalize_fail_signature,
)

# ── 保真 fixture（778072 形态）────────────────────────────────────────────────

# 案末汇总形态（14:55:52 组）：`… find: <pat>`，无 ` in:` 尾——真 Fail 行只有 Hit 一条。
CAUSALITY_778072 = "\n".join([
    "2026-07-16 14:55:50 #### Success Num 4: successed to find p1 in : ",
    "2026-07-16 14:55:50 #### Success Num 5: successed to find p3 in : ",
    "2026-07-16 14:55:50 #### Success Num 6: fail to find p2 in: ",
    "2026-07-16 14:55:52 #### Fail Num 1: fail to find: Hit:\\s+[1-9]\\d*\\b",
    "2026-07-16 14:55:52 #### Success Num 1: successed to find: 172\\.16\\.35\\.224",
    "2026-07-16 14:55:52 #### Success Num 2: successed to find: Hit:\\s+[1-9]\\d*\\b",
    "2026-07-16 14:55:52 #### Success Num 3: successed to find: 172\\.16\\.35\\.(213|224)",
    "2026-07-16 14:55:52 #### Success Num 4: successed to find: p1",
    "2026-07-16 14:55:52 #### Success Num 5: successed to find: p3",
    "2026-07-16 14:55:52 #### Success Num 6: fail to find: p2",
])

# device_context 头（节头行——B1 病灶的拼接对象）。
CONTEXT_HEAD_778072 = "=== 框架逐步执行+断言明细+异常 (203031753342778072.txt) ==="

CONTEXT_778072 = "\n".join([
    CONTEXT_HEAD_778072,
    "2026-07-16 14:55:50 show sdns host pool autotest.com",
    "2026-07-16 14:55:50 sdns host pool \"autotest.com\" \"p3\" 0 ",
    "2026-07-16 14:55:50 APV(config)#",
    "RTNETLINK answers: Cannot assign requested address",
])


def test_summary_form_fail_captured_and_only_fail():
    """778072 全形态：唯一真 Fail（汇总形态、无 in 尾）被收，其余全出局。"""
    sigs = _fail_signatures(CAUSALITY_778072)
    assert sigs == {"Hit:\\s+[1-9]\\d*\\b"}


def test_success_notfound_excluded():
    """B2：通过的 not_found 断言（Success 行含 'fail to find' 词面）不入签名。"""
    text = "\n".join([
        "2026-07-16 11:47:00 #### Success Num 1: fail to find: some\\.pattern in: file.txt",
        "2026-07-16 11:47:00 #### Success Num 2: fail to find: another",
    ])
    assert _fail_signatures(text) == set()
    # 旧实现的病灶留证：legacy 会把两条都收进来
    assert len(_fail_signatures_legacy(text)) == 2


def test_fail_notfound_form_captured():
    """新增益：not_found 断言失败（Fail … successed to find）旧 grep 漏收，新解析收。"""
    text = "#### Fail Num 2: successed to find: 172\\.16\\.35\\.99 in: x.txt"
    assert _fail_signatures(text) == {"172\\.16\\.35\\.99"}
    assert _fail_signatures_legacy(text) == set()  # 旧实现按词面漏收


def test_section_headers_not_captured():
    """B1：日志节头/文件名/RTNETLINK 紧邻 'fail to find' 词面也零污染（锚定 ^####）。"""
    text = "\n".join([
        CONTEXT_HEAD_778072,
        "step12: 断言 fail to find: 这行是步骤描述不是裁决行",
        "2026-07-16 14:55:52 #### Fail Num 1: fail to find: Hit:\\s+[1-9]\\d*\\b",
        "RTNETLINK answers: Cannot assign requested address",
    ])
    assert _fail_signatures(text) == {"Hit:\\s+[1-9]\\d*\\b"}


def test_causality_context_boundary_no_merge():
    """causality 尾 + device_context 头以 \\n 拼接后，边界处无跨段假签名。

    旧病灶原样复现检查：'+' 无分隔拼接会让 causality 末行 `…fail to find: p2` 与
    context 首行节头粘成一行，legacy 收出 `p2=== 框架…===` 假签名。
    """
    joined = "\n".join((CAUSALITY_778072, CONTEXT_778072))
    sigs = _fail_signatures(joined)
    assert sigs == {"Hit:\\s+[1-9]\\d*\\b"}
    assert not any("===" in s for s in sigs)
    # 留证：无分隔 '+' 拼接在 legacy 下产出跨段假签名（修复针对的旧形态）
    dirty = _fail_signatures_legacy(CAUSALITY_778072 + CONTEXT_778072)
    assert any("===" in s for s in dirty)


def test_timestamp_prefix_stripped():
    """带 `2026-07-14 11:47:00 ` 时戳前缀的 Fail 行照常命中。"""
    text = "2026-07-14 11:47:00 #### Fail Num 1: fail to find: pat\\d+ in: y.txt"
    assert _fail_signatures(text) == {"pat\\d+"}


def test_legacy_fallback_when_zero_structured_lines():
    """零条结构化裁决行的旧文本 → 回退旧正则结果（老日志/异构框架版本留声腿）。"""
    text = "some old log line: fail to find: legacy\\.pattern here\nplain tail"
    assert _fail_signatures(text) == _fail_signatures_legacy(text)
    assert _fail_signatures(text)  # 非空：真回退到了 legacy


def test_structured_lines_present_no_fallback():
    """有结构化裁决行但零 Fail（全 Success）→ 返回空集，不回退 legacy。"""
    text = "\n".join([
        "#### Success Num 1: fail to find: p2",     # 通过的 not_found
        "noise: fail to find: should_not_leak",      # 非裁决行词面
    ])
    assert _fail_signatures(text) == set()


def test_switch_off_reverts_legacy(monkeypatch):
    """IST_FAIL_SIG_STRUCTURED=0 整体回退旧行为（跨版本对照/紧急逃生口）。"""
    monkeypatch.setenv("IST_FAIL_SIG_STRUCTURED", "0")
    assert _fail_signatures(CAUSALITY_778072) == _fail_signatures_legacy(CAUSALITY_778072)


def test_dedup_same_expect_multiple_instances():
    """同一 expect 多断言实例——集合语义去重（同/异判定契约）。"""
    text = "\n".join([
        "#### Fail Num 1: fail to find: same\\.pat in: a.txt",
        "#### Fail Num 2: fail to find: same\\.pat in: b.txt",
    ])
    assert _fail_signatures(text) == {"same\\.pat"}


# ── 迁移条款（normalizer：旧脏签名 ∩ 新签名非空）────────────────────────────────

def test_migration_normalizer_aligns_legacy_dirty_signatures():
    """跨界轮：存量旧格式签名（带 ` in: <file>` 尾）与新签名两侧过同一 normalizer
    后交集非空——冻结/跨床反驳比较不再因格式换代静默失效。"""
    step_line = "#### Fail Num 1: fail to find p2 in: 203031753342778072.txt"
    legacy = _fail_signatures_legacy(step_line)          # {"p2 in: 20303…txt"} 带尾脏签名
    new = _fail_signatures(step_line)                    # {"p2"} 干净
    assert legacy != new                                 # 逐字比较恒空 → 旧病灶
    assert not (legacy & new)
    legacy_n = {normalize_fail_signature(s) for s in legacy}
    new_n = {normalize_fail_signature(s) for s in new}   # 新格式幂等
    assert new_n == new
    assert legacy_n & new_n == {"p2"}                    # 归一后可交集


def test_normalizer_idempotent_and_whitespace():
    assert normalize_fail_signature("  a\\s+ b   c  ") == "a\\s+ b c"
    s = normalize_fail_signature("p2 in: file.txt")
    assert s == "p2"
    assert normalize_fail_signature(s) == s              # 幂等
    assert normalize_fail_signature("") == ""
    # 60 截断保持（签名只用于同/异判定的短截断契约）
    long = "x" * 100
    assert normalize_fail_signature(long) == "x" * 60


# ── dongkl 实数据等值校验（F-Py-9b-2 快照固化:读 tests/fixtures/、脱离生产数据存在性依赖）──────

# 快照自 workspace/outputs/dongkl/unfinished/<autoid>/attr_evidence.json(2026-07-18 固化)——
# 原读生产区(workspace 不入 git),这次 outputs 清理/隔离会清掉 dongkl 致本测试崩;固化进 git 后恒读。
_DONGKL_UNFINISHED = (Path(__file__).resolve().parents[2]
                      / "fixtures" / "dongkl_unfinished")


def _naive_fail_patterns(text: str) -> set[str]:
    """独立参照实现：逐行剥时戳后仅认 `#### Fail Num` 行，同规归一。"""
    import re
    out: set[str] = set()
    for raw in (text or "").splitlines():
        ln = re.sub(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ", "", raw.strip())
        m = re.match(r"^#### Fail Num \d+: (?:fail to find|successed to find):? (.*)$", ln)
        if not m:
            continue
        pat = re.sub(r"\s+", " ", m.group(1)).strip()
        pat = re.sub(r" in ?: ?\S*\s*$", "", pat).strip()[:60]
        if pat:
            out.add(pat)
    return out


def test_real_dongkl_cases_reextraction_equals_fail_lines():
    """3 案 attr_evidence 快照(F-Py-9b-2 固化,tests/fixtures/dongkl_unfinished/)：新提取签名
    == 原文 Fail 裁决行集合，逐案相等；且不再含节头假行/Success not_found 项。固化后恒跑不 skip。"""
    evidences = sorted(_DONGKL_UNFINISHED.glob("*/attr_evidence.json"))
    assert evidences, "快照 fixture 缺失——tests/fixtures/dongkl_unfinished/ 被挪动?"
    checked = 0
    for ev in evidences:
        rec = json.loads(ev.read_text(encoding="utf-8"))
        joined = "\n".join(((rec.get("causality") or ""),
                            (rec.get("device_context") or "")))
        got = _fail_signatures(joined)
        want = _naive_fail_patterns(joined)
        assert got == want, f"{ev.parent.name}: {got ^ want}"
        assert not any("===" in s for s in got), f"{ev.parent.name}: 节头假行残留"
        checked += 1
    assert checked >= 1
