"""从脑图抽结构化用例(只功能用例)。

脑图→结构化用例的抽取入口(agent 编译路径用)。
零外部管线依赖。
"""
from __future__ import annotations

import json
from pathlib import Path


def extract_cases(mindmap_path: Path) -> list[dict]:
    """复用 qa_extract_test_cases 解析脑图为结构化用例(只功能用例)。"""
    from main.ist_core.tools.skills.test_case_extractor import qa_extract_test_cases
    out = qa_extract_test_cases.invoke({"file_path": str(mindmap_path)})
    data = json.loads(out) if isinstance(out, str) else out
    return data.get("test_cases", [])
