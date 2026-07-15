r"""用户意图路由器。

确定性规则分类用户消息意图，不依赖 LLM。
优先级匹配：长模式优先，避免歧义。

意图类别:
- CHAT:                  普通技术问答
- CREATE_DOCUMENT:       创建企微云文档
- UPDATE_DOCUMENT:       更新已有文档
- GENERATE_REPORT:       生成测试报告
- SEARCH_KNOWLEDGE:      搜索知识库/文档

用法::

    from main.ist_core.middleware.intent_router import IntentRouter, Intent
    router = IntentRouter()
    result = router.classify("写一个HTTP SLB配置文档")
    assert result.intent == Intent.CREATE_DOCUMENT
    assert result.confidence >= 0.8
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Intent(str, Enum):
    """用户意图类别。"""

    CHAT = "CHAT"
    CREATE_DOCUMENT = "CREATE_DOCUMENT"
    UPDATE_DOCUMENT = "UPDATE_DOCUMENT"
    GENERATE_REPORT = "GENERATE_REPORT"
    SEARCH_KNOWLEDGE = "SEARCH_KNOWLEDGE"


@dataclass(frozen=True)
class IntentResult:
    """意图分类结果。"""

    intent: Intent
    confidence: float           # 0.0 ~ 1.0
    source: str = "regex"       # 意图来源（未来可扩展为 llm/hybrid）
    matched_rule: str = ""      # 命中的规则名（调试用）

    def __str__(self) -> str:
        return (
            f"IntentResult(intent={self.intent.value}, "
            f"confidence={self.confidence:.2f}, "
            f"rule={self.matched_rule})"
        )


# 优先级从高到低：越具体的意图越先匹配
# 每个规则组带名称（matched_rule 输出用）
_INTENT_RULES: list[tuple[Intent, str, list[str]]] = [
    # 生成报告（最具体，优先匹配）
    (Intent.GENERATE_REPORT, "generate_report", [
        r"生成.*报告", r"创建.*报告", r"输出.*报告", r"测试报告",
        r"生成.*test.*report", r"/report", r"把.*结果.*文档",
        r"报告.*生成", r"报告.*创建",
    ]),
    # 搜索知识（有明确标记词，优先于创建文档）
    (Intent.SEARCH_KNOWLEDGE, "search_knowledge", [
        r"搜索.*知识", r"搜索.*文档", r"搜索.*资料",
        r"查找.*文档", r"查找.*资料",
        r"查询.*报告", r"历史.*报告", r"之前.*报告",
        r"之前.*文档", r"有哪些.*文档",
        r"search.*doc", r"find.*doc",
    ]),
    # 创建文档
    (Intent.CREATE_DOCUMENT, "create_document", [
        r"写.*文档", r"写.*手册", r"写.*指南", r"写.*方案",
        r"创建.*文档", r"创建.*手册", r"创建.*指南",
        r"生成.*文档", r"输出.*文档", r"保存.*文档",
        r"创建.*企微", r"写.*企微", r"生成.*企微",
        r"create.*doc", r"write.*doc",
    ]),
    # 更新文档
    (Intent.UPDATE_DOCUMENT, "update_document", [
        r"更新.*文档", r"修改.*文档", r"编辑.*文档", r"补充.*文档",
        r"改.*文档", r"update.*doc",
    ]),
]

# 置信度阈值
_CONFIDENCE_HIGH = 0.80      # ≥ 高置信度：正常 intent 过滤
_CONFIDENCE_MEDIUM = 0.50    # [medium, high)：保守模式
# < medium：回退 CHAT


def _compute_confidence(matched_count: int, total_patterns: int) -> float:
    """根据命中模式数计算置信度。

    命中越多模式，置信度越高。
    - 3+ 模式命中 → 0.95
    - 2 模式命中  → 0.85
    - 1 模式命中  → 0.70
    - 0 模式命中  → 0.0
    """
    if matched_count >= 3:
        return 0.95
    if matched_count == 2:
        return 0.85
    if matched_count == 1:
        return 0.70
    return 0.0


class IntentRouter:
    """确定性意图路由器。

    规则匹配，无 LLM 调用，延迟 <1ms。
    无法匹配时返回 CHAT（安全降级，confidence=0）。
    """

    def __init__(self) -> None:
        # 预编译正则：(intent, rule_name, [compiled_patterns])
        self._rules: list[tuple[Intent, str, list[re.Pattern[str]]]] = []
        for intent, rule_name, patterns in _INTENT_RULES:
            compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
            self._rules.append((intent, rule_name, compiled))

    def classify(self, text: str) -> IntentResult:
        """分类用户消息意图，返回 IntentResult（含置信度）。

        Args:
            text: 用户原始消息（已去除 @mention 等噪音）

        Returns:
            IntentResult，包含 intent / confidence / source / matched_rule
        """
        if not text or not text.strip():
            return IntentResult(
                intent=Intent.CHAT, confidence=0.0,
                source="regex", matched_rule="empty_input",
            )

        cleaned = text.strip()

        for intent, rule_name, patterns in self._rules:
            matched_count = sum(1 for p in patterns if p.search(cleaned))
            if matched_count > 0:
                confidence = _compute_confidence(matched_count, len(patterns))
                return IntentResult(
                    intent=intent,
                    confidence=confidence,
                    source="regex",
                    matched_rule=rule_name,
                )

        return IntentResult(
            intent=Intent.CHAT, confidence=0.0,
            source="regex", matched_rule="no_match",
        )

    # 向后兼容：旧代码调 classify() 期望返回 Intent
    def classify_intent(self, text: str) -> Intent:
        """仅返回 Intent（向后兼容接口）。"""
        return self.classify(text).intent

    @staticmethod
    def confidence_threshold_high() -> float:
        """高置信度阈值。"""
        return _CONFIDENCE_HIGH

    @staticmethod
    def confidence_threshold_medium() -> float:
        """中置信度阈值。"""
        return _CONFIDENCE_MEDIUM
