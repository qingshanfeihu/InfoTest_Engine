"""意图索引容损与原子写回归(2026-07-05 v12 实证修复)。

事故:索引被杀进程截断成「合法对象+拖尾对象」拼接,json.loads 报 Extra data,
旧代码整体放弃 → 28 个 PASS 先例写回全挂。守:①抢救合并(后写覆盖先写、
坏段跳过);②损坏读取自动备份+原子重写干净版;③原子写落盘可整体解析。
"""

from __future__ import annotations

import json

import main.ist_core.tools.device.precedent_tools as pt


def test_salvage_merges_concatenated_objects():
    a = json.dumps({"x.xlsx": ["旧意图"], "y.xlsx": ["Y"]}, ensure_ascii=False)
    b = json.dumps({"x.xlsx": ["新意图"], "z.xlsx": ["Z"]}, ensure_ascii=False)
    merged = pt._salvage_json_objects(a + "\n" + b)
    assert merged["x.xlsx"] == ["新意图"]          # 后写覆盖先写
    assert set(merged) == {"x.xlsx", "y.xlsx", "z.xlsx"}


def test_salvage_skips_truncated_tail():
    good = json.dumps({"a.xlsx": ["A"]}, ensure_ascii=False)
    corrupt = good + '\n{"b.xlsx": ["残'          # 截断的第二对象
    merged = pt._salvage_json_objects(corrupt)
    assert merged == {"a.xlsx": ["A"]}


def test_read_repairs_corrupt_file_with_backup(tmp_path, monkeypatch):
    idxp = tmp_path / "mirror_intent_index.json"
    monkeypatch.setattr(pt, "_INTENT_INDEX_PATH", idxp)
    good = json.dumps({"a.xlsx": ["A"]}, ensure_ascii=False)
    idxp.write_text(good + good, encoding="utf-8")   # 拼接损坏
    out = pt._read_intent_index_file()
    assert out == {"a.xlsx": ["A"]}
    # 原件备份 + 重写后的文件整体可解析
    assert list(tmp_path.glob("*.corrupt-*.json")), "损坏原件未备份"
    assert json.loads(idxp.read_text(encoding="utf-8")) == {"a.xlsx": ["A"]}


def test_atomic_write_roundtrip(tmp_path, monkeypatch):
    idxp = tmp_path / "mirror_intent_index.json"
    monkeypatch.setattr(pt, "_INTENT_INDEX_PATH", idxp)
    pt._write_intent_index_atomic({"k.xlsx": ["意图 > 路径"]})
    assert json.loads(idxp.read_text(encoding="utf-8")) == {"k.xlsx": ["意图 > 路径"]}
    assert not idxp.with_suffix(".json.tmp").exists()   # tmp 不残留
