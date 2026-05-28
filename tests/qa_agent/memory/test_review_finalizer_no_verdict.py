"""测试 review_finalizer 不再写评审结论 + archive 脚本.

来源：plan Step 1（memory write 端治理）。

参考实现不存评审结论到 memory；InfoTest_Engine 自创治理。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage


@pytest.fixture
def memory_adapter_module():
    """直接加载 ``test-case-review/memory_adapter.py``——它不在 main 包内（含连字符）."""
    project_root = Path(__file__).resolve().parents[3]
    adapter_path = (
        project_root / "main" / "qa_agent" / "skills" /
        "test-case-review" / "memory_adapter.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_review_adapter_test", adapter_path
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _StubStore:
    """memory_adapter.review_finalizer 签名要求 store 参数；本测试不依赖其方法."""


def test_finalizer_returns_none_for_p4_review_report(memory_adapter_module):
    """当主 agent 输出含 P0/P1 等评审关键字时，finalizer 仍不写入（治偷懒源头）."""
    messages = [
        HumanMessage(content="评审 BUG-121100 的测试用例"),
        AIMessage(content=(
            "## 二、基于证据的评级\n"
            "**P4** —— 用例覆盖完整但缺少 smode 测试...\n\n"
            "## 四、建议修改汇总\n"
            "P3-P5: Segment WebUI 重复...\n"
            "P0: 无重大缺口"
        )),
    ]
    result = memory_adapter_module.review_finalizer(messages, _StubStore())
    assert result is None, "评审结论必须不被写入 memory（不存评审结论）"


def test_finalizer_returns_none_for_empty_messages(memory_adapter_module):
    result = memory_adapter_module.review_finalizer([], _StubStore())
    assert result is None


def test_finalizer_returns_none_even_with_case_filename(memory_adapter_module):
    """即使能解析出 case_filename 与 ticket_id，也不写入."""
    messages = [
        HumanMessage(content=(
            "评审 knowledge/data/markdown/qa/Test List bug-to-case 121100 "
            "Cookie会话保持加密.md，对照 BUG-121100"
        )),
        AIMessage(content="## 评级 P4\n证据缺口：无"),
    ]
    result = memory_adapter_module.review_finalizer(messages, _StubStore())
    assert result is None


def test_archive_script_moves_cases_and_tickets(tmp_path):
    """archive 脚本把 cases/ + tickets/ 移到 archive/<timestamp>/."""
    from scripts.maintenance.archive_review_findings import (
        archive_review_findings,
    )

    memory_root = tmp_path / "memory"
    cases_dir = memory_root / "reviews" / "cases" / "case_121100"
    tickets_dir = memory_root / "reviews" / "tickets" / "BUG-121100"
    cases_dir.mkdir(parents=True)
    tickets_dir.mkdir(parents=True)
    (cases_dir / "findings.md").write_text("# legacy review report")
    (tickets_dir / "findings.md").write_text("# legacy review report")

    moved = archive_review_findings(memory_root=memory_root)

    assert "cases" in moved
    assert "tickets" in moved
    assert moved["cases"].is_dir()
    assert moved["tickets"].is_dir()
    # archive 后原路径不应存在
    assert not (memory_root / "reviews" / "cases").exists()
    assert not (memory_root / "reviews" / "tickets").exists()
    # archive 内容应在
    archived_findings = list(moved["cases"].rglob("findings.md"))
    assert any(f.read_text() == "# legacy review report" for f in archived_findings)


def test_archive_script_handles_missing_dirs(tmp_path):
    """没有 reviews/cases 或 reviews/tickets 时不应报错."""
    from scripts.maintenance.archive_review_findings import (
        archive_review_findings,
    )

    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    # reviews/ 整个不存在
    moved = archive_review_findings(memory_root=memory_root)
    assert moved == {}


def test_archive_script_handles_empty_reviews_root(tmp_path):
    """reviews/ 存在但 cases/ tickets/ 都缺失."""
    from scripts.maintenance.archive_review_findings import (
        archive_review_findings,
    )

    memory_root = tmp_path / "memory"
    (memory_root / "reviews").mkdir(parents=True)
    moved = archive_review_findings(memory_root=memory_root)
    assert moved == {}
