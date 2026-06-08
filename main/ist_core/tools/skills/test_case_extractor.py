"""qa_extract_test_cases: 脑图 JSON → 结构化测试用例列表 Tool.

通用适配不同人写的脑图用例格式。只提取功能性用例。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

_PROJECT_ROOT = Path(__file__).resolve().parents[4]

# Functional resource tag patterns (case-insensitive)
_FUNCTIONAL_RESOURCES = {"function", "functional", "funtional", "功能", "功能测试", "功能測試"}

# Module path keywords that indicate functional testing, even without resource tags.
_FUNCTIONAL_MODULE_KEYWORDS = ["功能", "functional", "function", "funtional"]

# Non-functional modules to skip (case-insensitive substring match)
_NON_FUNCTIONAL_MODULES = [
    "压力", "stress", "文档", "修改记录",
    "镜像链接", "功能概述", "补充case", "回归测试", "检查以下命令",
    "需求背景", "使用场景", "修订日期", "版本记录", "变更记录",
    "cli",  # CLI help/tab-completion tests, not functional feature tests
]

# Test methods not available in automation environment.
# Only CU (serial console) and SSH are available; skip WebUI, VGA, VNC.
_UNSUPPORTED_TEST_METHODS = [
    "webui", "vga", "vnc",
]

# Background context keywords — nodes whose text matches these are
# documentation/context, not test cases. (case-insensitive)
_BACKGROUND_KEYWORDS = [
    "修订日期", "版本记录", "变更记录", "修改记录",
    "功能概述", "需求背景", "使用场景", "测试环境",
    "前提条件", "备注", "说明：", "注：",
    "PLM需求", "需求链接", "镜像链接",
]


def _is_unsupported_method(module_path: str) -> bool:
    """Check if the module path indicates a test method unsupported in automation env."""
    path_lower = module_path.lower()
    for method in _UNSUPPORTED_TEST_METHODS:
        if method in path_lower:
            return True
    return False


def _is_background(text: str, module_path: str) -> bool:
    """Check if a node is background/context description rather than a test case."""
    combined = (text + " " + module_path).lower()
    for kw in _BACKGROUND_KEYWORDS:
        if kw.lower() in combined:
            return True
    return False


def _is_functional(module_path: str, resources: list[str]) -> bool:
    """Determine if a test case belongs to functional testing."""
    # Check resource tags first (most reliable)
    for r in resources:
        if r.lower() in _FUNCTIONAL_RESOURCES:
            return True

    # Check module path for functional indicators
    path_lower = module_path.lower()
    if any(kw in path_lower for kw in _FUNCTIONAL_MODULE_KEYWORDS):
        # Make sure it's not also in a non-functional sub-module
        for skip in _NON_FUNCTIONAL_MODULES:
            if skip.lower() in path_lower:
                # If the same path also has a functional keyword, it might be
                # nested — allow if functional keyword appears after the skip
                func_pos = max(
                    (path_lower.find(kw) for kw in _FUNCTIONAL_MODULE_KEYWORDS if kw in path_lower),
                    default=-1,
                )
                skip_pos = path_lower.find(skip.lower())
                if skip_pos >= 0 and (func_pos < 0 or skip_pos < func_pos):
                    return False
        return True

    return False


def _clean_brainmap_text(raw_text: str) -> str:
    """Strip BOM and leading garbage bytes, find JSON start."""
    # Handle multiple BOMs and non-characters
    while raw_text and ord(raw_text[0]) in (0xFEFF, 0xFFFF, 0xFFFE):
        raw_text = raw_text[1:]
    idx = raw_text.find("[")
    if idx > 0:
        raw_text = raw_text[idx:]
    return raw_text


def _infer_node_role(
    priority: int | None,
    degree: int | None,
    children_count: int,
    depth: int,
    max_depth: int,
) -> str:
    """Infer node role: 'module', 'case', or 'heading'."""
    if priority == 2:
        return "case"
    if priority == 1:
        return "module"
    if priority == 3:
        return "heading"

    # No priority — infer from structure
    if children_count == 0:
        return "case"  # leaf node
    if depth <= 2:
        return "module"
    return "heading"


def _split_steps_and_expected(text: str) -> tuple[list[str], list[str]]:
    """Split a test case text into action steps and expected results."""
    steps = []
    expected = []

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for line in lines:
        # Detect [check] style expected results
        if re.match(r'\[check\d*\]', line, re.IGNORECASE):
            expected.append(line)
        elif line.startswith("[") and "]" in line[:20]:
            expected.append(line)
        else:
            steps.append(line)

    # If no [check] markers found, treat all as steps
    if not expected and steps:
        # Check if there's a mix of numbered steps and results
        numbered = [l for l in steps if re.match(r'\d+[\.\、\)]', l)]
        if numbered and len(numbered) < len(steps):
            # Some lines look like results without check markers
            expected = [l for l in steps if not re.match(r'\d+[\.\、\)]', l)]
            steps = [l for l in steps if re.match(r'\d+[\.\、\)]', l)]

    return steps, expected


@tool
def qa_extract_test_cases(file_path: str) -> str:
    """Extract functional test cases from a brain-map JSON file.

    Reads a mind-map/brain-map JSON file (exported from test management tools),
    identifies functional test cases using adaptive heuristics, and returns a
    clean, structured JSON suitable for automation xlsx generation.

    Heuristics (adapt to different authors' writing styles):
    - priority=2 nodes → test cases; priority=1 → modules
    - Functional identification: "功能"/"function" in module path OR resource tags
    - Skips stress/webui/cli/documentation/release-notes modules
    - Extracts steps and expected results from case text and children
    - Handles [check] markers, numbered steps, and various text formats

    Args:
        file_path: Path to the brain-map .txt file (relative to project root
            or absolute). E.g. "yzg/input/yzg.txt".

    Returns:
        JSON string with: file_name, total_cases, modules (list of module
        paths), test_cases (list of {id, module, description, steps,
        expected, resource, priority, level, autoid}).
    """
    # Resolve path
    p = Path(file_path)
    candidates = [p, _PROJECT_ROOT / file_path]
    resolved = None
    for c in candidates:
        if c.exists():
            resolved = c
            break
    if resolved is None:
        return json.dumps({
            "status": "error",
            "error": f"File not found: {file_path}",
        }, indent=2, ensure_ascii=False)

    try:
        raw_text = resolved.read_text(encoding="utf-8")
        raw_text = _clean_brainmap_text(raw_text)
        data = json.loads(raw_text)
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "error": f"Failed to parse brain-map JSON: {exc}",
        }, indent=2, ensure_ascii=False)

    if not data or not isinstance(data, list):
        return json.dumps({
            "status": "error",
            "error": "Invalid brain-map format: expected a JSON array",
        }, indent=2, ensure_ascii=False)

    # Calculate max depth for inference
    def _max_depth(nodes, d=0):
        md = d
        for n in nodes:
            if n.get("children"):
                md = max(md, _max_depth(n["children"], d + 1))
        return md

    global_max_depth = _max_depth(data)

    root_text = data[0].get("data", {}).get("text", "").strip()

    # Collect test cases
    cases: list[dict[str, Any]] = []

    def _walk(nodes, path=None, depth=0):
        if path is None:
            path = []
        for node in nodes:
            d = node.get("data", {})
            text = d.get("text", "").strip()
            children = node.get("children", [])
            priority = d.get("priority")
            degree = d.get("degree")
            resource = d.get("resource", [])
            autoid = d.get("autoid", "")

            p = path + [text]
            role = _infer_node_role(
                priority, degree, len(children), depth, global_max_depth
            )

            if role == "case":
                # Build module path: skip root + non-module nodes
                module_parts = []
                for i, x in enumerate(p[:-1]):
                    # Skip root node
                    if i == 0 and x == root_text:
                        continue
                    # Skip nodes that look like cases (have step-like text)
                    node_d = None
                    # Find the node data for this path element
                    # simplified: just skip items that look like test steps
                    if not re.match(r'^\d+[\.\、\)]', x):
                        module_parts.append(x)

                module_path = " > ".join(module_parts)

                # Filter: skip background context nodes
                if _is_background(text, module_path):
                    _walk(children, p, depth + 1)
                    continue

                # Filter: skip unsupported test methods (webui/vga/vnc/api)
                if _is_unsupported_method(module_path):
                    _walk(children, p, depth + 1)
                    continue

                # Filter: functional only
                if not _is_functional(module_path, resource):
                    _walk(children, p, depth + 1)
                    continue

                # case 节点自身文本 = 用例名（描述），不作为步骤
                case_title = text.strip() if text else ""
                steps, expected = [], []
                case_prerequisites: list[str] = []
                # 步骤→预期关联：steps_with_expected[i] = 第i个步骤专属的预期列表
                step_expected_map: dict[int, list[str]] = {}

                # 前置条件标签关键词
                _PREREQ_LABELS = ["前提条件", "前置条件", "前置步骤", "前置："]

                # ── 结构规则：所有子节点都是步骤或检查点，由位置决定 ──
                # 有孙节点的 → 子节点=步骤，孙节点=检查点
                # 无孙节点的叶子 → 末位=检查点，非末位=步骤

                for idx, child in enumerate(children):
                    ct = child.get("data", {}).get("text", "").strip()
                    if not ct:
                        continue
                    grand_children = child.get("children", [])
                    is_last = (idx == len(children) - 1)

                    # ── 检测"前提条件"标签 → 用例前置 ──
                    is_prereq_child = any(
                        ct.startswith(kw) for kw in _PREREQ_LABELS
                    ) and not re.match(r'^\d+[\.\、\)]', ct)
                    if is_prereq_child:
                        prereq_text = ct
                        for prefix in ["前提条件:", "前提条件：", "前置条件:", "前置条件：",
                                       "前置步骤:", "前置步骤：", "前置："]:
                            if prereq_text.startswith(prefix):
                                prereq_text = prereq_text[len(prefix):].strip()
                                break
                        if prereq_text:
                            case_prerequisites.append(prereq_text)
                        for gc in grand_children:
                            gct = gc.get("data", {}).get("text", "").strip()
                            if gct:
                                case_prerequisites.append(gct)
                        continue

                    # ── 有孙节点：子节点是步骤，孙节点是预期结果 ──
                    if grand_children:
                        child_steps, child_expected = _split_steps_and_expected(ct)
                        if child_steps:
                            for cs in child_steps:
                                step_idx = len(steps)
                                steps.append(cs)
                                step_expected_map[step_idx] = []
                        elif not re.match(r'^\d+[\.\、\)]', ct):
                            step_idx = len(steps)
                            steps.append(ct)
                            step_expected_map[step_idx] = []
                        gc_exp = []
                        for gc in grand_children:
                            gct = gc.get("data", {}).get("text", "").strip()
                            if not gct:
                                continue
                            gc_steps, gc_expected = _split_steps_and_expected(gct)
                            gc_exp.extend(gc_expected)
                            if gc_steps and not gc_expected:
                                gc_exp.extend(gc_steps)
                        last_idx = len(steps) - 1
                        if last_idx in step_expected_map:
                            step_expected_map[last_idx].extend(gc_exp)
                        expected.extend(gc_exp)

                    # ── 叶子节点：末位是检查点，非末位是步骤 ──
                    elif is_last:
                        _, child_expected = _split_steps_and_expected(ct)
                        if child_expected:
                            expected.extend(child_expected)
                        else:
                            expected.append(ct)
                    else:
                        child_steps, child_expected = _split_steps_and_expected(ct)
                        if child_steps:
                            steps.extend(child_steps)
                        elif child_expected:
                            expected.extend(child_expected)
                        else:
                            steps.append(ct)

                # 如果没有步骤但有预期结果，用例名本身就是步骤
                if not steps and expected and case_title:
                    steps.append(case_title)

                # 只有有关联预期的步骤才保留对应的 expected
                # 扁平 expected 保留兼容，同时加 step_expected 字段
                linked_expected = []
                for idx, exps in step_expected_map.items():
                    linked_expected.extend(exps)
                # 合并：有关联的用关联的，没关联的保留原 expected 中未被关联的部分
                all_expected = list(linked_expected)
                for e in expected:
                    if e not in all_expected:
                        all_expected.append(e)

                # Deduplicate while preserving order.
                # Also remap step_expected_map indices to match deduped steps.
                seen = set()
                old_to_new: dict[int, int] = {}
                new_steps: list[str] = []
                for i, s in enumerate(steps):
                    if s in seen:
                        continue
                    old_to_new[i] = len(new_steps)
                    seen.add(s)
                    new_steps.append(s)
                steps = new_steps
                # Remap step_expected indices
                if step_expected_map:
                    remapped: dict[int, list[str]] = {}
                    for old_idx, exps in step_expected_map.items():
                        if old_idx in old_to_new:
                            remapped[old_to_new[old_idx]] = exps
                    step_expected_map = remapped
                seen.clear()
                expected = [e for e in expected if not (e in seen or seen.add(e))]  # type: ignore[func-returns-value]

                case: dict[str, Any] = {
                    "module": module_path,
                    "description": case_title if case_title else (text if not steps else ""),
                }
                if steps:
                    case["steps"] = steps
                if all_expected:
                    case["expected"] = all_expected
                if case_prerequisites:
                    case["case_prerequisites"] = case_prerequisites
                if step_expected_map:
                    # 转换为字符串键的格式给 decomposer 用
                    case["step_expected"] = {str(k): v for k, v in step_expected_map.items() if v}
                if resource:
                    case["resource"] = resource
                if priority is not None:
                    case["priority"] = priority
                if degree is not None:
                    level_map = {1: "基础", 2: "扩展", 3: "边界/负向"}
                    case["level"] = level_map.get(degree, str(degree))
                if autoid:
                    case["autoid"] = str(autoid)

                cases.append(case)

            elif children:
                _walk(children, p, depth + 1)

    _walk(data)

    # Build module list
    modules = sorted(set(c["module"] for c in cases if c["module"]))

    # Assign sequential IDs
    for i, c in enumerate(cases, 1):
        c["id"] = i
        # Reorder for readability
        ordered = {}
        for key in ["id", "module", "description", "steps", "expected",
                     "resource", "priority", "level", "autoid"]:
            if key in c:
                ordered[key] = c.pop(key)
        ordered.update(c)
        cases[i - 1] = ordered

    result = {
        "status": "success",
        "file_name": resolved.name,
        "total_cases": len(cases),
        "modules": modules,
        "test_cases": cases,
    }

    return json.dumps(result, indent=2, ensure_ascii=False)
