"""测试 qa_bash / qa_exec 多根沙箱（Step 5：解决 trace 实证 LLM 读 workspace/inputs/ 反复失败）.

来源：plan Step 5（沙箱接口统一）。

设计动机：trace 实证 LLM 想读 ``workspace/inputs/<.xlsx>`` 时
``qa_bash`` / ``qa_exec`` 的 cwd 锁在 knowledge/data/ 单根，导致路径反复
试错。改造后 ``qa_bash`` 解析命令路径参数选最匹配的沙箱根作为 cwd。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from main.qa_agent.tools.deepagent import exec_tools, file_tools
from main.qa_agent.tools.deepagent.exec_tools import qa_bash


@pytest.fixture
def multi_root_sandbox(tmp_path, monkeypatch):
    """模拟多根沙箱：knowledge/data/ + workspace/."""
    project = tmp_path
    agent_root = project / "knowledge" / "data"
    workspace_root = project / "workspace"
    agent_root.mkdir(parents=True)
    workspace_root.mkdir(parents=True)
    (agent_root / "markdown").mkdir()
    (agent_root / "markdown" / "qa.md").write_text("agent root file")
    (workspace_root / "inputs").mkdir()
    (workspace_root / "inputs" / "case.xlsx").write_text("workspace file")

    monkeypatch.setattr(file_tools, "_PROJECT_ROOT", project)
    monkeypatch.setattr(file_tools, "_AGENT_ROOT", agent_root)
    monkeypatch.setattr(file_tools, "_WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(exec_tools, "_PROJECT_ROOT", project)
    monkeypatch.setattr(exec_tools, "_AGENT_ROOT", agent_root)

    return {
        "project": project,
        "agent_root": agent_root,
        "workspace_root": workspace_root,
    }


def test_qa_bash_can_list_workspace_inputs(multi_root_sandbox):
    """``ls workspace/inputs/`` 在多根沙箱下应该能成功（之前 cwd 锁单根失败）."""
    result = qa_bash.invoke({"command": "ls workspace/inputs/", "timeout": 5})
    # 不能是 error，应该是 returncode=0 + 看到 case.xlsx
    assert "returncode=0" in result, f"unexpected: {result}"
    assert "case.xlsx" in result


def test_qa_bash_in_agent_root_still_works(multi_root_sandbox):
    """老路径 ``ls markdown/`` （相对 agent_root）继续工作."""
    result = qa_bash.invoke({"command": "ls markdown/", "timeout": 5})
    assert "returncode=0" in result
    assert "qa.md" in result


def test_qa_bash_cat_workspace_file(multi_root_sandbox):
    """``cat workspace/inputs/case.xlsx`` 应能直接读到 workspace 根下文件."""
    result = qa_bash.invoke({
        "command": "cat workspace/inputs/case.xlsx",
        "timeout": 5,
    })
    assert "returncode=0" in result
    assert "workspace file" in result


def test_qa_bash_rejects_outside_sandbox_path(multi_root_sandbox):
    """沙箱外路径仍然被拒（多根扩展不削弱安全）."""
    project = multi_root_sandbox["project"]
    # 创建一个沙箱外文件
    outside = project / "elsewhere" / "secret.txt"
    outside.parent.mkdir(parents=True)
    outside.write_text("secret")

    result = qa_bash.invoke({
        "command": f"cat {outside}",
        "timeout": 5,
    })
    assert result.startswith("error:")


def test_qa_bash_command_without_path_uses_default_cwd(multi_root_sandbox):
    """命令没有路径参数时（如 ``echo hi``），cwd 应回退到 ``_default_cwd()``."""
    result = qa_bash.invoke({"command": "echo hi", "timeout": 5})
    assert "returncode=0" in result
    assert "hi" in result
