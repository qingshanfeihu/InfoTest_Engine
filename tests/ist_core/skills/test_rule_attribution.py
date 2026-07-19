# -*- coding: utf-8 -*-
"""⑥C 规则归属机器门(team4 #45 ⑥C,DESIGN §5.5 治理改写:废固定行数预算 → 归属行+熔断)。

§5.5:215/216 两约束——①**归属行存在性**:agent md 每条规则必须在 theory-map.md 有归属
(无归属=该删);②**150 熔断**:单文件超线先置换(删无据/过时规则入 removed-rules.md)
再增补、不得净增。

归属机制:agent md 每条规则末尾挂 `[Wn]`/`[An]` 可见 ID(**非 `<!--注释-->`——实测
loader.py:404 `body=parts[2].strip()` 不剥 HTML 注释,注释会全量进 LLM prompt 载荷=污染;
故用可见 ID,~4 字符/规则的有意识最小污染,详见 theory-map.md 头注),theory-map.md
`## Rule attribution` 表每 ID 一归属行(归属详情 externalized 到 review 面,prompt 只留 ID)。

机器检查三断言:
  ① **双射**(per agent):`set(md 的 [Wn]/[An]) == set(theory-map 表 Rule)`——md 有 ID
     无归属行=无归属规则(红)、表有 ID 而 md 无=孤儿归属(红),兑现"规则条数==归属行数"
     且抓错配;
  ② **theory 类 Ref ∈ 构件闭集**(闭集从 theory-map 上方构件表**解析**、不硬编码——增
     构件闭集自更新);grammar/failmode Ref 非空即可;
  ③ **line_count <= 熔断线** per file(=标注后实际行数;合法越线=先置换 removed-rules.md
     +有意识 bump 本常量,frozen-override 型——bump 动作本身=§5.5「越线先做减法」的强制触发)。

残余诚实标:纯散文里没挂 ID 的规范句机器抓不到(ID 定义规则边界)——靠 redline/Design
人审兜(读 md 确认无 tag-less 规范 claim)。
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_WORKER = _ROOT / "main/ist_core/agents/compile-worker.md"
_ATTRIBUTOR = _ROOT / "main/ist_core/agents/compile-attributor.md"
_THEORY_MAP = _ROOT / "main/ist_core/skills/ist-compile-engine/references/theory-map.md"

_ID_RE = re.compile(r"\[([WA]\d+)\]")
_ATTR_HEADER = "## Rule attribution"


def _md_ids(path: Path) -> list[str]:
    """agent md 里的 [Wn]/[An] marker,保留出现次序(供重复检测)。"""
    return _ID_RE.findall(path.read_text(encoding="utf-8"))


def _split_theory_map() -> tuple[str, str]:
    """theory-map.md 切成 (构件表区, 归属表区)——归属表区 = `## Rule attribution` 之后。
    构件闭集从构件表区抽(不含归属表,避免用被检查的 Ref 自证闭集)。"""
    text = _THEORY_MAP.read_text(encoding="utf-8")
    idx = text.find(_ATTR_HEADER)
    assert idx >= 0, f"theory-map.md 缺 `{_ATTR_HEADER}` 节(⑥C 归属表)"
    return text[:idx], text[idx:]


def _construct_closed_set(construct_region: str) -> set[str]:
    """构件闭集:构件表区里的 F\\d+ 与 §\\d+(.\\d+)*。theory-map 增构件→闭集自更新。"""
    return (set(re.findall(r"F\d+", construct_region))
            | set(re.findall(r"§\d+(?:\.\d+)*", construct_region)))


def _attribution_rows(attr_region: str) -> list[tuple[str, str, str]]:
    """归属表数据行 → [(rule_id, kind, ref)]。只取 Rule 列匹配 [WA]\\d+ 的行
    (跳过表头/`---`分隔/散文);Kind:Ref 按首个 `:` 分。"""
    rows: list[tuple[str, str, str]] = []
    for line in attr_region.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cols = [c.strip() for c in s.strip("|").split("|")]
        if len(cols) < 2 or not re.fullmatch(r"[WA]\d+", cols[0]):
            continue
        kind, _, ref = cols[1].partition(":")
        rows.append((cols[0], kind.strip(), ref.strip()))
    return rows


# ── ① 双射存在性(per agent):set(md ID) == set(theory-map 表 Rule) ──────────────────


def test_bijection_worker():
    ids = _md_ids(_WORKER)
    assert len(ids) == len(set(ids)), f"worker md 有重复 marker:{ids}"
    _, attr = _split_theory_map()
    table_w = {r for r, _, _ in _attribution_rows(attr) if r.startswith("W")}
    assert set(ids) == table_w, \
        f"worker 双射破:md 无归属={set(ids) - table_w} 表孤儿={table_w - set(ids)}"


def test_bijection_attributor():
    ids = _md_ids(_ATTRIBUTOR)
    assert len(ids) == len(set(ids)), f"attributor md 有重复 marker:{ids}"
    _, attr = _split_theory_map()
    table_a = {r for r, _, _ in _attribution_rows(attr) if r.startswith("A")}
    assert set(ids) == table_a, \
        f"attributor 双射破:md 无归属={set(ids) - table_a} 表孤儿={table_a - set(ids)}"


# ── ② theory 类 Ref ∈ 构件闭集;Kind 白名单;Ref 非空 ────────────────────────────


def test_attribution_refs_in_closed_set():
    construct, attr = _split_theory_map()
    closed = _construct_closed_set(construct)
    empty, bad_theory, bad_kind = [], [], []
    for rule, kind, ref in _attribution_rows(attr):
        if not ref:
            empty.append(rule)
        if kind not in ("theory", "grammar", "failmode"):
            bad_kind.append((rule, kind))
        elif kind == "theory" and ref not in closed:
            bad_theory.append((rule, ref))
    assert not empty, f"归属 Ref 为空:{empty}"
    assert not bad_kind, f"Kind 非白名单{{theory,grammar,failmode}}:{bad_kind}"
    assert not bad_theory, f"theory 类 Ref 不在构件闭集 {sorted(closed)}:{bad_theory}"


# ── ③ 150 熔断 tripwire(=标注后实际行数;越线先置换+bump,frozen-override 型)──────
# bump 规程:先删无据规则入 removed-rules.md / 检索顺序类置换入 contracts.md,再有意识
# 改本常量到新实际行数(bump 动作=§5.5「越线先做减法」的强制触发,防多轮增补不回填漂移)。
# attributor 193←187: +[A24](#52 SSL 静默失败面 pointer,#50 S1-S5 证据;无过时 A 规则可删,frozen-override 型 bump)
_LINE_CEILING = {"compile-worker.md": 203, "compile-attributor.md": 193}


def test_line_count_tripwire():
    for path in (_WORKER, _ATTRIBUTOR):
        n = len(path.read_text(encoding="utf-8").splitlines())
        ceil = _LINE_CEILING[path.name]
        assert n <= ceil, (
            f"{path.name} {n} 行 > 熔断线 {ceil}:先置换(删无据入 removed-rules.md / "
            f"检索序入 contracts.md)再有意识 bump 本常量(§5.5 越线先减法)")
