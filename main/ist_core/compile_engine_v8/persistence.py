"""持久化通道判定与卷序规则(DESIGN §6.5;数据=domain_grammar.persistence_channels)。

理论定位:ctx=(π, B) 中 π 的通道①优化 + 通道④共存检查——纯函数,吃文法数据与卷面行,
零硬编码领域命令(新通道=加 JSON 条目)。W/R 精确集不可文本判定,按家族保守近似
(误报代价=多挪几案到卷尾,不改案面内容)。
"""

from __future__ import annotations

import re
from functools import lru_cache

from main.case_compiler.domain_grammar import load_grammar


@lru_cache(maxsize=1)
def _channels() -> dict:
    ch = dict(load_grammar().get("persistence_channels") or {})
    ch.pop("_provenance", None)
    return ch


def _lines(case_steps: list[dict]) -> list[str]:
    out: list[str] = []
    for s in case_steps:
        if str(s.get("E") or "") == "check_point":
            continue  # 断言行的 G 是 pattern 不是命令
        out.extend(ln for ln in str(s.get("G") or "").splitlines() if ln.strip())
    return out


def case_channels(case_steps: list[dict]) -> set[str]:
    """该案命中的持久化通道集(保守近似:任一行命中任一 pattern 即入族)。"""
    hit: set[str] = set()
    lines = _lines(case_steps)
    for name, spec in _channels().items():
        pats = [re.compile(p, re.IGNORECASE) for p in (spec.get("patterns") or [])]
        if pats and any(p.search(ln) for ln in lines for p in pats):
            hit.add(name)
    return hit


def order_volume(cases: list[dict], steps_key: str = "steps") -> tuple[list[dict], list[str]]:
    """通道①/②排卷尾:干净案保持原序在前,持久化案保持族内原序移尾。

    返回 (新序 cases, 被移尾的 autoid 列表——交付报告须声明重排)。
    只对 mitigation 含 order_tail 的通道生效;排序是单调改善(干净案入边恒零,
    定理见 DESIGN §6.5),尾簇内部残余互扰由终验+矛盾 ask 兜底。
    """
    tail_channels = {n for n, s in _channels().items() if "order_tail" in str(s.get("mitigation", ""))}
    clean, tail, moved = [], [], []
    for c in cases:
        ch = case_channels(c.get(steps_key) or [])
        if ch & tail_channels:
            tail.append(c)
            moved.append(str(c.get("autoid")))
        else:
            clean.append(c)
    return clean + tail, moved


def coexist_violations(cases: list[dict], steps_key: str = "steps") -> list[dict]:
    """通道④共存检查:同卷中互斥对两侧都出现 → 违例清单(merge 期告警/隔离依据)。

    coexist_forbidden = [side_a_patterns, side_b_patterns]:卷内任一案命中 a 侧、
    任一案命中 b 侧即违例(官方约束是设备级状态互斥,不限同一案内)。
    """
    out: list[dict] = []
    for name, spec in _channels().items():
        pair = spec.get("coexist_forbidden")
        if not pair or len(pair) != 2:
            continue
        pa = [re.compile(p, re.IGNORECASE) for p in pair[0]]
        pb = [re.compile(p, re.IGNORECASE) for p in pair[1]]
        hits_a, hits_b = [], []
        for c in cases:
            lines = _lines(c.get(steps_key) or [])
            if any(p.search(ln) for ln in lines for p in pa):
                hits_a.append(str(c.get("autoid")))
            if any(p.search(ln) for ln in lines for p in pb):
                hits_b.append(str(c.get("autoid")))
        if hits_a and hits_b:
            out.append({"channel": name, "side_a": hits_a, "side_b": hits_b,
                        "provenance": spec.get("provenance", "")})
    return out
