"""compile_prep: 脑图→manifest 解析契约 + 零命令红线。

验证 prep 只产需求(标题/分组/步骤/期望)、零命令;autoid 主键、标题重名不去重。
吃真实的三个脑图(workspace/inputs/automatic_case/*.txt)做基线。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from main.ist_core.tools.device import compile_prep

_ROOT = Path(__file__).resolve().parents[3]
_INPUTS = _ROOT / "workspace" / "inputs" / "automatic_case"

# 计划已核实的基线(本会话实测):dongkl 34 / yzg 26 / zhaiyq 53
_EXPECTED = {"dongkl": 34, "yzg": 26, "zhaiyq": 53}


@pytest.mark.skipif(not _INPUTS.exists(), reason="脑图输入不在")
@pytest.mark.parametrize("name,count", _EXPECTED.items())
def test_prep_case_counts(name, count, tmp_path):
    src = _INPUTS / f"{name}.txt"
    if not src.exists():
        pytest.skip(f"{name}.txt 不在")
    out = compile_prep.invoke(
        {"mindmap_path": str(src), "out_name": f"_pytest_prep_{name}"})
    assert f"case 总数: {count}" in out, out


@pytest.mark.skipif(not (_INPUTS / "dongkl.txt").exists(), reason="dongkl 不在")
def test_prep_manifest_has_no_commands():
    """红线:manifest 里 case 的 init_commands/steps/assertions_provenance 全 null。"""
    compile_prep.invoke(
        {"mindmap_path": str(_INPUTS / "dongkl.txt"), "out_name": "_pytest_prep_redline"})
    mpath = _ROOT / "workspace" / "outputs" / "_pytest_prep_redline" / "manifest.json"
    m = json.loads(mpath.read_text(encoding="utf-8"))
    assert m["case_count"] == 34
    for c in m["cases"]:
        assert c["init_commands"] is None, f"红线违反: {c['autoid']} 有命令"
        assert c["steps"] is None
        assert c["assertions_provenance"] is None
        # 需求字段必须有(标题/分组/步骤需求)
        assert c["autoid"] and c["title"]
        assert isinstance(c["step_intents"], list)
        assert isinstance(c["group_path"], list)


@pytest.mark.skipif(not (_INPUTS / "zhaiyq.txt").exists(), reason="zhaiyq 不在")
def test_prep_keeps_duplicate_titles_unique_autoid():
    """zhaiyq 有 10 组重名标题:标题不去重,autoid 全唯一。"""
    compile_prep.invoke(
        {"mindmap_path": str(_INPUTS / "zhaiyq.txt"), "out_name": "_pytest_prep_dup"})
    mpath = _ROOT / "workspace" / "outputs" / "_pytest_prep_dup" / "manifest.json"
    m = json.loads(mpath.read_text(encoding="utf-8"))
    autoids = [c["autoid"] for c in m["cases"]]
    titles = [c["title"] for c in m["cases"]]
    assert len(autoids) == len(set(autoids)) == 53  # autoid 全唯一
    assert len(titles) != len(set(titles))           # 标题有重名,未去重


def test_prep_rejects_missing_file():
    out = compile_prep.invoke({"mindmap_path": "no/such/mindmap.txt"})
    assert "error" in out and "不存在" in out
