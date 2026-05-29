"""评审结果结构化 schema（Step 6）.
``createStructuredOutputTool`` 的 zod schema 模式——InfoTest_Engine 用
Pydantic 等价物。

用途：
- ``structured_extract`` 节点用独立 LLM 抽 verifier ToolMessage + 主 agent
  草稿，套 ``ReviewResult.model_validate()``
- 下游 TUI / 日志 / state.final_review 消费
- review_gate 检测 VERDICT/LEVEL 行（字符串匹配，不依赖本 schema）
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

class ReviewCheck(BaseModel):
    """verifier 单条 Check 结构"""

    title: str = Field(description="Check 标题（what you're verifying）")
    source: str = Field(default="", description="证据来源（test case rows / product doc）")
    verification_command: str = Field(default="", description="实际执行的 grep / read_file 命令")
    output_observed: str = Field(default="", description="命令实际输出（copy-paste）")
    result: Literal["PASS", "FAIL", "PARTIAL"] = Field(description="单条 Check 结果")
    severity: str = Field(default="", description="P0-P7 或空（仅 FAIL/PARTIAL 时有意义）")

class ReviewResult(BaseModel):
    """评审最终结构化输出（verifier verdict + 主 agent 草稿聚合）."""

    verdict: Literal["PASS", "PARTIAL", "FAIL"] = Field(
        description="verifier 给的最终 verdict（主 agent 不能 self-assign）"
    )
    level: str = Field(
        description="P0-P7 级别（verifier 给的）",
        pattern=r"^P[0-7]$",
    )
    checks: list[ReviewCheck] = Field(
        default_factory=list,
        description="verifier 的 Check 列表",
    )
    main_agent_draft_level: str | None = Field(
        default=None,
        description="主 agent 草稿给的初步 P 级别（可能与 verifier 不同）",
    )
    verifier_raw: str = Field(
        default="",
        description="verifier ToolMessage 原始 content（用于 debug / 回溯）",
    )
    final_markdown: str = Field(
        default="",
        description="最终渲染给用户的 markdown 报告",
    )
