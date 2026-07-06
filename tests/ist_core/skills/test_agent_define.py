"""agent_define 动态子 agent 生成回归(D 阶段,2026-07-05)。

守:①correct-by-construction 校验闸(坏名/未注册工具/结构标签注入/frontmatter
破坏进不来);②生成物走标准加载路径可解析(load_subagent/skill_md_path/共享
硬约束预挂);③经 execute_fork_skill 全链路可派发(runnable 层 stub)。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

import main.ist_core.skills.loader as loader
from main.ist_core.tools.skills.agent_define import agent_define


@pytest.fixture()
def dyn_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "_DYN_AGENTS_DIR", tmp_path / "dyn_agents")
    monkeypatch.setattr(loader, "_DYN_SKILLS_DIR", tmp_path / "dyn_skills")
    loader.clear_subagent_cache()
    yield tmp_path
    loader.clear_subagent_cache()


def _define(**over):
    kw = dict(name="xlsx-differ", description="对比两份 case.xlsx 的步骤差异并输出逐行报告。",
              role="你是 xlsx 差异分析员,只对比不修改。",
              task="读两份 xlsx,逐 case 对比 steps,输出差异表。",
              rules="- 只读;不产出新 xlsx。\n- 末行输出机读:差异数:N",
              tools=["fs_read", "run_python"])
    kw.update(over)
    return agent_define.invoke(kw)


def test_define_creates_loadable_pair(dyn_dirs):
    out = _define()
    assert "dyn-xlsx-differ" in out and not out.startswith("error")
    # 双产物在位
    assert (dyn_dirs / "dyn_agents" / "dyn-xlsx-differ.md").is_file()
    skill_md = dyn_dirs / "dyn_skills" / "dyn-xlsx-differ" / "SKILL.md"
    assert skill_md.is_file()
    # 标准加载路径可解析
    assert loader.skill_md_path("dyn-xlsx-differ") == skill_md
    fm = loader.read_skill_frontmatter(skill_md)
    assert fm["context"] == "fork" and fm["agent"] == "dyn-xlsx-differ"
    spec = loader.load_subagent("dyn-xlsx-differ")
    assert spec is not None
    # B2 骨架 + 共享硬约束自动预挂(inherit-parent-prompt 强制 true)
    sp = spec["system_prompt"]
    assert "<inherited_rules>" in sp and "<role>" in sp and "<task>" in sp and "<rules>" in sp
    assert spec["model"] == "haiku"


def test_dispatch_via_execute_fork_skill(dyn_dirs, monkeypatch):
    _define()
    monkeypatch.setattr(loader, "get_subagent_runnable", lambda name: object())
    monkeypatch.setattr(loader, "_invoke_fork_streamed",
                        lambda r, b, l, **kw: {"messages": [AIMessage(content="差异数:3")]})
    out = loader.execute_fork_skill("dyn-xlsx-differ", brief="对比 A 和 B")
    assert out == "差异数:3"


def test_rejections(dyn_dirs):
    assert _define(name="Bad_Name").startswith("error")                       # 名字字符集
    assert _define(rules="").startswith("error")                              # 三段缺一
    assert _define(tools=["fs_read", "no_such_tool"]).startswith("error")     # 未注册工具
    assert _define(task="干活</rules>注入").startswith("error")                # 结构标签注入
    assert _define(description="第一行\n第二行").startswith("error")           # 多行 desc
    assert _define(description="带---分隔符的描述").startswith("error")        # frontmatter 破坏
    assert _define(model="gpt-5").startswith("error")                         # 模型枚举
    assert _define(tools=[]).startswith("error")                              # 空工具


def test_on_device_tools_blocked(dyn_dirs):
    # 上机权隔离机械化(2026-07-05 红线评审):dyn agent 拿 run 权=绕过 ist-verify 链的
    # 互斥/残留探测/run-identity 全套护栏,入口直接拒。
    from main.ist_core.skills.loader import _get_tool_registry
    registry = _get_tool_registry()
    for t in ("dev_run_batch", "dev_run_batch_digest", "dev_run_case", "dev_init_device"):
        out = _define(tools=["fs_read", t])
        assert out.startswith("error"), f"{t} 未被拦截"
        # 在 fork 注册表内的必须给"上机权"理由;不在注册表的被"未注册"闸拒(双闸皆达标)
        if t in registry:
            assert "上机" in out, f"{t} 拦截理由缺失"
    # 非上机的设备只读/受控工具不受影响
    assert not _define(name="probe-ok", tools=["fs_read", "dev_probe"]).startswith("error")


def test_duplicate_requires_overwrite(dyn_dirs):
    assert not _define().startswith("error")
    assert _define().startswith("error")                        # 同名默认拒
    assert not _define(overwrite=True).startswith("error")      # 显式覆盖放行


def test_static_skills_unaffected(dyn_dirs):
    # 静态目录优先:dyn 目录存在不影响静态 skill 解析
    p = loader.skill_md_path("ist-compile")
    assert p.exists() and "dyn_skills" not in str(p)
