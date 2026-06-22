"""qa_footprint_lookup 查找/回退算法的行为契约。

用**受控合成 footprint** 测，不碰生产知识库（生产数据随手册重解析漂移，
硬编码其值会假红假绿）。每个节点的 feature_id / 命令都由测试自己定义。

覆盖算法的每条分支：
  A. 精确命中叶子（有命令）         → 直接展开该节点
  B. 精确命中 branch（自己也有命令）→ 展开 + 附子命令清单
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
    return fl.qa_footprint_lookup.invoke({"command": q})


# A. 精确命中叶子 → 展开该节点，不触发回退
def test_A_exact_leaf_hit(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("demo.listener", ["demo listener <ip>", "show demo listener"]),
    ])
    r = _lookup("demo listener")
    assert "demo.listener" in r
    assert "demo listener <ip>" in r
    assert "父节点" not in r and "模糊" not in r


# B. 精确命中 branch，branch 自己也有命令 → 展开自身命令 + 附子命令清单
def test_B_branch_with_own_commands(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("demo.svc", ["demo svc <x>"], children=["demo.svc.method"]),
        _node("demo.svc.method", ["demo svc method <a>"]),
    ])
    r = _lookup("demo svc")
    assert "demo svc <x>" in r        # 自己的命令
    assert "demo.svc.method" in r      # 子命令清单（ID）
    assert "子命令" in r


# C. 命中空壳 branch，命令在直接子节点 → 递归展开子节点命令
def test_C_empty_branch_expands_children(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("demo.svc", [], children=["demo.svc.method", "demo.svc.name"]),
        _node("demo.svc.method", ["demo svc method <a>"]),
        _node("demo.svc.name", ["demo svc name <n>"]),
    ])
    r = _lookup("demo svc")
    assert "父节点" in r
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
    assert "父节点" in r                      # 走递归展开，不是模糊兜底
    assert "demo svc method <a>" in r          # 下潜到孙节点拿到命令
    assert "模糊" not in r


# E. branch 整棵子树都无命令 → 如实说明，不做全树模糊（治：返回无关 token-兄弟）
def test_E_empty_subtree_no_misleading_fuzzy(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("demo.empty", [], children=["demo.empty.child"]),
        _node("demo.empty.child", []),
        # 一个仅共享 "demo" token 的无关带命令节点——绝不能被返回
        _node("demo.other", ["demo other command"]),
    ])
    r = _lookup("demo empty")
    assert "未记录任何 CLI 命令" in r
    assert "demo other command" not in r       # 不得模糊到无关节点
    assert "模糊" not in r


# F. 查询不对应任何节点（自然措辞）→ 全树模糊，只收带命令叶子
def test_F_natural_phrase_fuzzy_fallback(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("demo.svc.method", ["demo svc method <a>"]),
    ])
    # "demo svc method rr" 不是节点（key demo.svc.method.rr 无），前缀也无 → None → 模糊
    r = _lookup("demo svc method rr")
    assert "模糊匹配" in r
    assert "demo svc method <a>" in r


# G. 彻底无 token 命中 → 未找到
def test_G_genuine_miss(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("demo.svc.method", ["demo svc method <a>"]),
    ])
    r = _lookup("zzz totally absent qqq")
    assert "未找到" in r


# 子节点计数只数带命令的（空子节点不计入展开列表）
def test_child_count_excludes_empty_children(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("demo.svc", [], children=["demo.svc.method", "demo.svc.empty"]),
        _node("demo.svc.method", ["demo svc method <a>"]),
        _node("demo.svc.empty", []),           # 空子节点
    ])
    r = _lookup("demo svc")
    assert "1 个带命令的节点" in r              # 只数 method，不数 empty


# 递归去重：子树有环/重复引用不死循环
def test_recursion_dedup_no_infinite_loop(tmp_path, monkeypatch):
    _make_index(tmp_path, monkeypatch, [
        _node("demo.a", [], children=["demo.b", "demo.a"]),  # 自引用
        _node("demo.b", ["demo b cmd"], children=["demo.a"]),  # 回指
    ])
    r = _lookup("demo a")                       # 不应挂死
    assert "demo b cmd" in r
