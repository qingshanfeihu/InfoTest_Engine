"""修法1: 草稿新鲜度校验(旧草稿被视作没产出,治旧草稿污染)。"""
from __future__ import annotations

import os
import time


def test_stale_draft_rejected(tmp_path, monkeypatch):
    import importlib
    cp = importlib.import_module("main.ist_core.tools.device.compile_pipeline")
    root = tmp_path
    d = root / "workspace" / "outputs" / "aid1"
    d.mkdir(parents=True)
    f = d / "case.xlsx"
    f.write_text("x")
    old = time.time() - 100
    os.utime(f, (old, old))            # 文件是 100s 前的(旧草稿)
    monkeypatch.setattr(cp, "_project_root", lambda: root)
    # since=现在 → 旧文件应被拒(返回 None)
    assert cp._extract_xlsx_path("out", "aid1", since=time.time()) is None
    # since=0 → 不校验新鲜度,返回路径
    assert cp._extract_xlsx_path("out", "aid1", since=0) == f
    # 文件刷新到现在 → 通过
    now = time.time()
    os.utime(f, (now, now))
    assert cp._extract_xlsx_path("out", "aid1", since=now - 0.5) == f
