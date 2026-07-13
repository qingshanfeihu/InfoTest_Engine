"""kb_footprint 查找/回退算法的行为契约。

用**受控合成 footprint** 测，不碰生产知识库（生产数据随手册重解析漂移，
硬编码其值会假红假绿）。每个节点的 feature_id / 命令都由测试自己定义。

覆盖算法的每条分支：
  A. 精确命中叶子（有命令）         → 直接展开该节点
  B. 精确命中 branch（自己也有命令）→ 展开自身 + **深展开**子树后代命令文法（不只列名）
  B2. 深展开超字符上限              → 部分展开 + 剩余后代回退列名提示
  C. 命中空壳 branch（命令在子节点）→ 递归展开子树带命令的后代
  D. 命中空壳 trunk（命令在孙节点） → 递归下潜到孙节点（单层展开会漏）
  E. branch 整棵子树都无命令        → 如实说明，不做全树模糊（不返回无关节点）
  F. 查询不对应任何节点（自然措辞） → 全树模糊兜底，只收带命令叶子
  G. 彻底无命中                     → 未找到
"""

from __future__ import annotations

import json

import pytest

from main.ist_core.memory.footprint.index import FootprintIndex
import main.ist_core.tools.knowledge.footprint_lookup as fl
import main.ist_core.memory.footprint as fp_mod


def _node(fid: str, commands: list[str], *, children: list[str] | None = None) -> dict:
    return {
        "schema_version": "1",
        "feature_id": fid,
        "level": "branch" if children else "leaf",
        "cli": {"commands": [{"command": c} for c in commands]},
        "footprint_meta": {"verified_count": 1},
        **({"children": children} if children else {}),
    }


def _make_index(tmp_path, monkeypatch, nodes: list[dict]) -> FootprintIndex:
    d = tmp_path / "nodes"
    d.mkdir()
    for n in nodes:
        (d / f"{n['feature_id']}.json").write_text(json.dumps(n), encoding="utf-8")
    idx = FootprintIndex(d)
    monkeypatch.setattr(fl, "get_footprint_index", lambda: idx, raising=False)
    monkeypatch.setattr(fp_mod, "get_footprint_index", lambda: idx, raising=False)
    return idx


def _lookup(q: str) -> str:
    return fl.kb_footprint.invoke({"command": q})


# A. 精确命中叶子 → 展开该节点，不触发回退
def test_A_exact_leaf_hit(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("demo.listener", ["demo listener <ip>", "show demo listener"]),
    ])
    r = _lookup("demo listener")
    assert "demo.listener" in r
    assert "demo listener <ip>" in r
    assert "parent node" not in r and "fuzzy" not in r


# B. 精确命中 branch，branch 自己也有命令 → 展开自身命令 + **深展开**子树后代命令文法。
# 治：旧行为只列子命令 ID 名，draft 拿到 `demo svc` 还得逐个再单查 method/name 拿文法
# （自顶向下走树、5.3 轮/fork 的制造机）。新行为一次把后代文法答全。
def test_B_branch_with_own_commands(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("demo.svc", ["demo svc <x>"],
              children=["demo.svc.method", "demo.svc.name"]),
        _node("demo.svc.method", ["demo svc method <a>"]),
        _node("demo.svc.name", ["demo svc name <n>"]),
    ])
    r = _lookup("demo svc")
    assert "demo svc <x>" in r            # 自己的命令
    assert "demo svc method <a>" in r     # 后代**文法**已内联（不只 ID）
    assert "demo svc name <n>" in r       # 多个后代都展开文法
    assert "Subcommand grammar" in r      # 走深展开分支


# B2. 深展开超 _KB_EXPAND_MAX_CHARS → 部分展开 + 剩余后代回退列名（护病态宽节点不爆上下文）
def test_B2_deep_expand_respects_char_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(fl, "_KB_EXPAND_MAX_CHARS", 1)  # 极小上限：仅首个后代展开
    _make_index(tmp_path, monkeypatch, [
        _node("demo.svc", ["demo svc <x>"],
              children=["demo.svc.method", "demo.svc.name"]),
        _node("demo.svc.method", ["demo svc method <a>"]),
        _node("demo.svc.name", ["demo svc name <n>"]),
    ])
    r = _lookup("demo svc")
    assert "demo svc method <a>" in r          # 首个后代仍展开（防全截没）
    assert "remaining subcommands not expanded" in r   # 剩余回退列名提示
    assert "demo.svc.name" in r                # 未展开者以 ID 列出供再查


# C. 命中空壳 branch，命令在直接子节点 → 递归展开子节点命令
def test_C_empty_branch_expands_children(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("demo.svc", [], children=["demo.svc.method", "demo.svc.name"]),
        _node("demo.svc.method", ["demo svc method <a>"]),
        _node("demo.svc.name", ["demo svc name <n>"]),
    ])
    r = _lookup("demo svc")
    assert "parent node" in r
    assert "demo svc method <a>" in r
    assert "demo svc name <n>" in r


# D. 命中空壳 trunk，直接子是空 branch、命令在孙节点 → 递归下潜（单层会漏）
def test_D_trunk_recurses_to_grandchild(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("demo", [], children=["demo.svc"]),
        _node("demo.svc", [], children=["demo.svc.method"]),
        _node("demo.svc.method", ["demo svc method <a>"]),
    ])
    r = _lookup("demo")
    assert "parent node" in r                  # 走递归展开，不是模糊兜底
    assert "demo svc method <a>" in r          # 下潜到孙节点拿到命令
    assert "fuzzy" not in r


# E. branch 整棵子树都无命令 → 如实说明，不做全树模糊（治：返回无关 token-兄弟）
def test_E_empty_subtree_no_misleading_fuzzy(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("demo.empty", [], children=["demo.empty.child"]),
        _node("demo.empty.child", []),
        # 一个仅共享 "demo" token 的无关带命令节点——绝不能被返回
        _node("demo.other", ["demo other command"]),
    ])
    r = _lookup("demo empty")
    assert "no CLI commands are recorded" in r
    assert "demo other command" not in r       # 不得模糊到无关节点
    assert "fuzzy" not in r


# F. 查询不对应任何节点（自然措辞）→ 全树模糊，只收带命令叶子
def test_F_natural_phrase_fuzzy_fallback(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("demo.svc.method", ["demo svc method <a>"]),
    ])
    # "demo svc method rr" 不是节点（key demo.svc.method.rr 无），前缀也无 → None → 模糊
    r = _lookup("demo svc method rr")
    assert "fuzzy-matched" in r
    assert "demo svc method <a>" in r


# G. 彻底无 token 命中 → 未找到
def test_G_genuine_miss(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("demo.svc.method", ["demo svc method <a>"]),
    ])
    r = _lookup("zzz totally absent qqq")
    assert "not found" in r


# H. 带 no/show/clear 动词前缀的查询 → 剥动词回退到裸 feature_id 叶子。
#    feature_id 由 extractor 剥动词后铸造(裸命令主体),但 agent 照手册原样
#    `no/show/clear <cmd>` 查 → 原样 key 对不上,须剥动词重试才精确命中,不该落模糊。
def test_H_verb_prefixed_query_strips_to_bare_feature(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("sdns.session.persistence",
              ["show sdns session persistence [host_name]",
               "no sdns session persistence <host_name> <network>",
               "clear sdns session persistence [host_name]"]),
    ])
    for q in ("no sdns session persistence",
              "show sdns session persistence",
              "clear sdns session persistence"):
        r = _lookup(q)
        assert "sdns.session.persistence" in r, q   # 精确命中裸 feature_id
        assert "fuzzy" not in r and "parent node" not in r, q


# I. feature_id 本就以 show/no/clear 起头的真节点(纯展示/清除命令,无配置对偶)→
#    原样精确命中,不被动词剥离误伤成裸形式而落空(治回退误伤这 20 个真·动词节点)。
def test_I_verb_led_feature_id_hit_as_is(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("show.statistics.sdns.query", ["show statistics sdns query"]),
        _node("clear.config.all", ["clear config all"]),
    ])
    r = _lookup("show statistics sdns query")
    assert "show.statistics.sdns.query" in r
    assert "show statistics sdns query" in r
    assert "fuzzy" not in r
    r2 = _lookup("clear config all")
    assert "clear.config.all" in r2
    assert "fuzzy" not in r2


# J. 原样既无动词节点、剥动词后裸主体也不存在 → 仍回 None(交给上层模糊),不误命中。
def test_J_verb_prefix_strip_still_miss_falls_to_fuzzy(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("demo.svc.method", ["demo svc method <a>"]),
    ])
    # "no demo svc method rr": 原样 no.demo.* 无; 剥 no → demo.svc.method.rr 仍无节点/前缀 → 模糊
    r = _lookup("no demo svc method rr")
    assert "fuzzy-matched" in r
    assert "demo svc method <a>" in r


# 子节点计数只数带命令的（空子节点不计入展开列表）
def test_child_count_excludes_empty_children(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("demo.svc", [], children=["demo.svc.method", "demo.svc.empty"]),
        _node("demo.svc.method", ["demo svc method <a>"]),
        _node("demo.svc.empty", []),           # 空子节点
    ])
    r = _lookup("demo svc")
    assert "1 command-bearing node" in r        # 只数 method，不数 empty


# 递归去重：子树有环/重复引用不死循环
def test_recursion_dedup_no_infinite_loop(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("demo.a", [], children=["demo.b", "demo.a"]),  # 自引用
        _node("demo.b", ["demo b cmd"], children=["demo.a"]),  # 回指
    ])
    r = _lookup("demo a")                       # 不应挂死
    assert "demo b cmd" in r


# K. token 级唯一前缀补全(设备 CLI 同款解析,run20 实证:`write mem` 曾被全树模糊
#    淹没)——`demo mem` 唯一补全到 memory,直接展开该叶,不走模糊。
def test_K_token_prefix_completion_unique(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("demo.memory", ["demo memory"]),
        _node("demo.method", ["demo method <m>"]),
        _node("demo.net", ["demo net <url>"]),
    ])
    r = _lookup("demo mem")                     # mem → memory 唯一(method 不以 mem 起头)
    assert "demo.memory" in r and "demo memory" in r
    assert "fuzzy-matched" not in r


# K2. 多义前缀不猜(设备同样拒绝解析)→ 回落模糊。
def test_K2_ambiguous_prefix_falls_to_fuzzy(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("demo.memory", ["demo memory"]),
        _node("demo.method", ["demo method <m>"]),
    ])
    r = _lookup("demo me")                      # me → memory/method 多义
    assert "No exact match" in r


# K3. 动词剥离后再补全:`show demo mem` → 剥 show → demo mem → memory。
def test_K3_verb_strip_then_completion(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("demo.memory", ["demo memory"]),
        _node("demo.net", ["demo net <url>"]),
    ])
    r = _lookup("show demo mem")
    assert "demo.memory" in r
    assert "fuzzy-matched" not in r


# K4. 多 token 逐级补全:`de mem` → demo.memory(每级唯一)。
def test_K4_multi_token_completion(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("demo.memory", ["demo memory"]),
        _node("demo.net", ["demo net <url>"]),
    ])
    r = _lookup("de mem")
    assert "demo.memory" in r
    assert "fuzzy-matched" not in r


# K5. 补全到 branch 前缀同样成立:`demo se fi` → demo.segment.file。
def test_K5_completion_through_branch(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("demo.segment.file", ["demo segment file <f>"]),
        _node("demo.net", ["demo net <url>"]),
    ])
    r = _lookup("demo se fi")
    assert "demo segment file <f>" in r
    assert "fuzzy-matched" not in r
