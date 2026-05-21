"""Fork extractor agent：仿 cc-haha src/services/extractMemories/。

设计要点：
- 与主 agent 共享同一个 CompositeBackend（确保读写一致）
- 不挂 _ToolExclusionMiddleware，让 fork agent 能用 read_file / edit_file
- prompt 强约束：路径必须 /memories/ 开头，5 turn 收敛
- recursion_limit 强制卡 turn 上限，超了直接 raise
- 失败一律静默（warning），主 agent 不受影响

为什么不复用主 agent 的 build_main_agent：
- 主 agent 挂着 PerTurnSkillReminder / SkillsMiddleware / Semantic check sub-agent，
  对 fork extractor 都是噪音
- fork agent 应当尽可能精简，用更小的模型（haiku tier）省算力
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from langchain_core.messages import HumanMessage

from main.qa_agent.agents._llm import build_agent_chat_model, qa_agent_tier_model
from main.qa_agent.memory.extractor import format_extraction_input

logger = logging.getLogger(__name__)


_EXTRACTOR_SYSTEM_PROMPT = """你是 IST-Core 记忆抽取助手。任务：阅读最近的对话片段，
判断是否有内容值得**长期保留**到 /memories/，如果有，调 edit_file 写入。

# 强约束（不可违反）

1. 工具调用上限 5 次，超过必须收敛输出 `DONE: nothing to commit` 并停止
2. 路径必须以 `/memories/` 开头：
   - `/memories/preferences.md` —— 用户偏好（语气、解释风格、禁用类比）
   - `/memories/feedback/<topic>.md` —— 用户反复纠正的反馈
   - `/memories/review_conclusions/<bug-id>.md` —— 已固化的评审结论
3. 用户必须**显式**说"以后/下次/记住/不要"才升级到 preferences.md / feedback/
4. 单次问答事实**不写**长期记忆（属于 working 范畴）
5. 禁止编造、禁止把对话当真理、禁止把单轮事实写成"用户偏好"
6. 禁止操作 /memories/AGENTS.md（项目级，由 dream task 管理）
7. 禁止操作 /working/* 路径（thread 内 hot path 自动维护）

# 工作流

1. 第一步必须先 read_file 看现有内容（preferences.md / 相关 feedback 文件）
2. 判断是否有"显式长期价值" → 没有 → 直接输出 `DONE: nothing to commit`，停止
3. 有 → edit_file 追加（保持文件原结构，只 append 新条目，不重写全文）
4. 完成后输出 `DONE: <一句话总结改动>` 并停止

# 输出格式（严格）

每次工具调用前后必须输出极短的中文说明（≤30 字）。最后一条消息必须以 `DONE:` 开头。
"""


_extractor_lock = threading.Lock()


def build_extractor_agent(*, backend: Any) -> Any:
    """构造 fork extractor agent。

    参考 deepagents/graph.py:206-225 create_deep_agent 签名。

    Args:
        backend: 主 agent 共享的 CompositeBackend（已 routes /memories/ → StoreBackend）。

    Returns:
        编译好的 LangGraph Runnable。失败时返回 None（调用方需 None 检查）。
    """
    try:
        from deepagents import create_deep_agent
    except ImportError as exc:
        logger.warning("deepagents 不可用，extractor agent 关闭: %s", exc)
        return None

    # 用 haiku tier 省算力（抽取任务比主评审简单得多）
    try:
        model = build_agent_chat_model(model=qa_agent_tier_model("haiku"))
    except Exception as exc:
        logger.warning("extractor agent 模型构造失败: %s", exc)
        return None

    try:
        return create_deep_agent(
            model=model,
            tools=[],
            system_prompt=_EXTRACTOR_SYSTEM_PROMPT,
            backend=backend,
            # 不传 memory= / skills= / interrupt_on= / subagents=
            # 关键：不挂 _ToolExclusionMiddleware（用户 middleware 留空），
            # 让 deepagents 默认装配的 FilesystemMiddleware（read_file/edit_file 等）保留
        )
    except Exception as exc:
        logger.warning("extractor agent 构造失败: %s", exc)
        return None


def run_extractor(
    extractor_agent: Any,
    recent_messages: list,
    *,
    max_turns: int = 5,
) -> str:
    """同步调 extractor，max_turns 卡 recursion_limit。

    Args:
        extractor_agent: build_extractor_agent 返回值；None 时直接返回 ""。
        recent_messages: 主 agent 最近的 messages 列表。
        max_turns: 最多允许工具调用次数；超出会被 langgraph recursion error 拦截。

    Returns:
        最后一条 AIMessage 文本（理想情况下以 `DONE:` 开头）；失败返回 ""。
    """
    if extractor_agent is None:
        return ""

    if not _extractor_lock.acquire(blocking=False):
        logger.debug("extractor 互斥锁被占，跳过本轮 distill")
        return ""

    try:
        prompt_input = format_extraction_input(recent_messages, tail_n=10)
        result = extractor_agent.invoke(
            {"messages": [HumanMessage(content=prompt_input)]},
            # recursion_limit = max_turns * 2 (tool_call + tool_result) + 余量
            config={"recursion_limit": max_turns * 2 + 4},
        )
    except Exception as exc:
        logger.warning("extractor agent invoke 失败: %s", exc)
        return ""
    finally:
        _extractor_lock.release()

    try:
        msgs = result.get("messages") if isinstance(result, dict) else None
        if not msgs:
            return ""
        # 最后一条 AIMessage 文本
        from langchain_core.messages import AIMessage
        for m in reversed(msgs):
            if isinstance(m, AIMessage):
                c = m.content
                if isinstance(c, str):
                    return c
                if isinstance(c, list):
                    parts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
                    return "\n".join(p for p in parts if p)
        return ""
    except Exception as exc:
        logger.debug("extractor 结果解析失败: %s", exc)
        return ""


__all__ = ["build_extractor_agent", "run_extractor"]
