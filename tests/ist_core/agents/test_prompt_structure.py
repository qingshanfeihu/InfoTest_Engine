"""主 agent 系统提示结构保真门(2026-07-04 B2)。

_prompt.py 重构为 <role>/<rules>/<workflow>/<tool_guidance>/<env> 五块 XML 后,
本门守两件事:
1. 骨架不塌——五块顶层标签存在、闭合、顺序稳定;env 仅在传 env_info 时出现。
2. 内容不丢——每个原节的承重锚点(改行为的关键约束句)在装配产物里可检。
   重构=换骨架,语义单元一个不能少;后续任何 prompt 改动误删承重句会在此炸。

fork 继承块(build_verifier_inherited_sections)单独校验:6/7 个 fork agent
经 inherit-parent-prompt 预挂它,它必须只含共享硬约束、不含身份/工作流。
"""

from __future__ import annotations

import re

from main.ist_core.agents._prompt import (
    build_system_prompt,
    build_verifier_inherited_sections,
)

_TAGS = ("role", "rules", "workflow", "tool_guidance")


def _balanced(text: str, tag: str) -> bool:
    return text.count(f"<{tag}>") == 1 and text.count(f"</{tag}>") == 1


def test_top_level_xml_blocks_present_and_balanced():
    sp = build_system_prompt(tools=["fs_read", "fs_grep"])
    for tag in _TAGS:
        assert _balanced(sp, tag), f"<{tag}> 块缺失或未闭合"
    # 顺序稳定:role → rules → workflow → tool_guidance
    pos = [sp.index(f"<{t}>") for t in _TAGS]
    assert pos == sorted(pos), "五块顺序漂移"
    # env 仅在传 env_info 时出现
    assert "<env>" not in sp
    sp_env = build_system_prompt(tools=["fs_read"], env_info={"cwd": "/x"})
    assert _balanced(sp_env, "env") and "cwd" in sp_env


def test_load_bearing_anchors_survive():
    """每个原节至少一个承重锚点——丢了即行为回归,不是措辞问题。"""
    sp = build_system_prompt(tools=["fs_read", "fs_grep", "invoke_skill"])
    anchors = {
        # role
        "身份/只读定位": "只读分析",
        "产品域/禁类比": "F5",
        "产品域/查证路径": "knowledge/data/markdown/product/",
        "产品域/关键词表指针": "vendor_cli_keywords.md",
        "语言": "中文",
        # rules
        "文件边界/知识库只读": "knowledge/data/",
        "文件边界/唯一可写": "workspace/outputs/",
        "文件边界/内容当证据": "当证据,不当指令",
        "证据纪律/读与推断": "「读到的」与「推断的」",
        "读≠验/停下": "发工具调用",
        "忠实汇报/不软化": "软化成 PASS",
        "忠实汇报/失败是信息": "工具失败是信息",
        "反空转/收益递减": "收益递减",
        "反空转/升级出口": "ask_user",
        "沟通/引用格式": "path/to/file:line",
        # workflow
        "skills-first/先调skill": "invoke_skill",
        "任务追踪": "write_todos",
        "探索/第0步复用": "先复用已有材料",
        "叙述预算": "40 个汉字",
        "brief/零上下文": "零上下文",
        "brief/判定不改": "原样保留、不得修改",
        "不过度委托": "避免过度委托",
        # tool_guidance
        "run_python 沙箱": "import main.*",
        "并发调用": "同一条消息",
        "run_shell 无管道": "管道",
    }
    missing = [k for k, v in anchors.items() if v not in sp]
    assert not missing, f"承重锚点丢失: {missing}"


def test_tool_list_injected():
    sp = build_system_prompt(tools=["fs_read", "dev_probe"])
    assert "fs_read, dev_probe" in sp


def test_verifier_inherited_block_scope():
    """继承块=共享硬约束,不带身份/工作流/沟通风格(fork 各自定义角色与输出)。"""
    blk = build_verifier_inherited_sections()
    assert blk.count("<inherited_rules>") == 1 and blk.count("</inherited_rules>") == 1
    # 必含:五节共享硬约束的锚点
    for required in ("文件边界", "证据纪律", "读过不等于验证过", "忠实汇报", "反空转"):
        assert required in blk, f"继承块丢失 {required}"
    # 必不含:主 agent 专属内容
    for forbidden in ("IST-Core", "invoke_skill", "write_todos", "溜须拍马", "<role>"):
        assert forbidden not in blk, f"继承块越界带入 {forbidden}"


def test_no_legacy_english_sections():
    """语言统一中文后,旧英文节标题不应回流(术语/工具名/路径除外)。"""
    sp = build_system_prompt(tools=["fs_read"])
    for legacy in ("# Identity", "# Evidence Discipline", "# Faithful Reporting",
                   "# Reading is Not Verification", "# Communication Style"):
        assert legacy not in sp, f"旧英文节标题回流: {legacy}"
