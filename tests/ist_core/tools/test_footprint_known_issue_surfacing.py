# -*- coding: utf-8 -*-
"""#61 surfacing infra:footprint known_issue 检索渲染可见性(自包含 synthetic fixture)。

003 二次根因(检索侧):worker 自然查路径上 known_issue 不可见——两 bug:
(a) 父查(如 `ssl activate`)深展开子命令 compact grammar 却漏子叶 known_issue(surfacing 缺失);
(b) 叶直查渲染只读老 schema {issue_id,title} → 新观察式 {fact_key,validity,content} 渲成空 `?: `。
surfacing infra 独立于任何具体领域 known_issue 内容——用**合成 fixture** 守渲染逻辑本身,不耦合
易变节点(#61 的真 YES known_issue 已被 device verdict 判合法而删除;infra 与被删内容无关、独立正确)。
"""
from __future__ import annotations

import json

from main.ist_core.memory.footprint.index import FootprintIndex
from main.ist_core.tools.knowledge.footprint_lookup import (
    _format_node, _issue_label, _kb_footprint_compute,
)


def _new_schema_node():
    """观察式 known_issue(LLM-Eng #52 起 footprint 节点用的 schema)。"""
    return {"feature_id": "demo.leaf", "level": "leaf",
            "cli": {"commands": [{"command": "demo leaf cmd"}]},
            "known_issues": [{"fact_key": "demo_trap", "validity": "uncertain",
                              "content": "陷阱详情:正确做法是走 X 两参机制,不写内联注解。"}]}


def _old_schema_node():
    return {"feature_id": "demo.old", "level": "leaf",
            "cli": {"commands": [{"command": "demo old cmd"}]},
            "known_issues": [{"issue_id": "203031753342778012", "title": "老式 known issue 标题"}]}


# ── bug (b):叶直查 non-brief 渲染新观察式 content 全文 ──────────────────────────


def test_leaf_render_new_schema_content_full():
    """修前只读 title/issue_id → 新 schema 渲成 `?: `(空),content 陷阱详情不可见。"""
    out = _format_node(_new_schema_node(), brief=False)
    assert "Known issues" in out
    assert "demo_trap" in out, "新 schema fact_key 未渲染"
    assert "正确做法是走 X" in out, "content 全文丢失(截断=指针落空)"
    assert "〔uncertain〕" in out, "validity 标签缺失(worker 据此判观察级/可设备实验仲裁)"
    assert "- ?: " not in out, "新 schema 不应渲成空 `?: `(schema-mismatch 回归)"


def test_old_schema_render_not_regressed():
    """双 schema 兼容:老 {issue_id,title}(sdns.* 在用)渲染不回归。"""
    out = _format_node(_old_schema_node(), brief=False)
    assert "203031753342778012" in out and "老式 known issue 标题" in out


# ── bug (a):brief(父展开)浮现子叶 known_issue 标签+指针 ────────────────────────


def test_brief_render_surfaces_label_and_pointer():
    out = _format_node(_new_schema_node(), brief=True)
    assert "demo_trap" in out, "brief 未浮现 known_issue 标签"
    assert "query" in out and "demo.leaf" in out, "brief 缺直查叶节点指针"
    assert "正确做法" not in out, "brief 应紧凑(只标签+指针),不内联 content 全文"


def test_issue_label_both_schemas():
    assert _issue_label({"fact_key": "fk", "content": "c"}) == "fk"
    assert _issue_label({"issue_id": "iid", "title": "t"}) == "t"
    assert _issue_label({"content": "只有内容"}) == "只有内容"


# ── 端到端:父查经 _kb_footprint_compute 深展开浮现子叶 known_issue ──────────────


def test_parent_query_surfaces_child_known_issue(tmp_path, monkeypatch):
    """worker 自然查询路径:父命令拿子命令文法时,子叶高频陷阱须在此可见(否则重犯)。"""
    nodes = tmp_path / "nodes"
    nodes.mkdir()
    (nodes / "demo.parent.json").write_text(json.dumps({
        "feature_id": "demo.parent", "level": "trunk",
        "cli": {"commands": []}, "children": ["demo.parent.child"]}), encoding="utf-8")
    (nodes / "demo.parent.child.json").write_text(json.dumps({
        "feature_id": "demo.parent.child", "level": "leaf",
        "cli": {"commands": [{"command": "demo parent child cmd"}]},
        "known_issues": [{"fact_key": "child_trap", "validity": "uncertain",
                          "content": "子叶陷阱详情"}]}), encoding="utf-8")
    idx = FootprintIndex(nodes)
    monkeypatch.setattr("main.ist_core.memory.footprint.get_footprint_index",
                        lambda *a, **k: idx)
    out = _kb_footprint_compute("demo parent")
    assert "child_trap" in out, "父查未浮现子叶 known_issue 标签(surfacing 回归)"
    assert "demo.parent.child" in out, "surfacing 缺直查叶节点指针"
