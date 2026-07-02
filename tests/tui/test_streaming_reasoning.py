"""streaming/_llm：reasoning_content 抽取——footer 真实 think 状态 + 思考流式的数据源。

mimo 深度思考期以 content=null、delta.reasoning_content 逐步返回思考。这几处保证它
不被当空 delta 丢弃、而是抽到 llm_token payload 的 reasoning 字段（reducer 据此置
thinking 相位、footer 显示"深度思考中"）。
"""

from __future__ import annotations

from langchain_core.messages import AIMessageChunk

from main.ist_core.agents._llm import _reasoning_from_raw
from main.ist_core.streaming import _to_event_payload


def test_reasoning_from_raw():
    raw = {"choices": [{"delta": {"reasoning_content": "思考增量", "content": None}}]}
    assert _reasoning_from_raw(raw) == "思考增量"
    # 回答型 delta / 无 reasoning / 空 choices → None
    assert _reasoning_from_raw({"choices": [{"delta": {"content": "答案"}}]}) is None
    assert _reasoning_from_raw({"choices": []}) is None
    assert _reasoning_from_raw({}) is None


def test_to_event_payload_extracts_reasoning():
    """思考 chunk（content 空 + additional_kwargs.reasoning_content）→ payload['reasoning']。"""
    chunk = AIMessageChunk(content="", additional_kwargs={"reasoning_content": "推理中…"})
    p = _to_event_payload({"name": "m", "data": {"chunk": chunk}})
    assert p.get("reasoning") == "推理中…"
    assert not p.get("content")   # 思考期 content 为空


def test_to_event_payload_content_chunk_has_no_reasoning():
    """回答 chunk（content 非空、无 reasoning）→ 只有 content。"""
    chunk = AIMessageChunk(content="答案")
    p = _to_event_payload({"name": "m", "data": {"chunk": chunk}})
    assert p.get("content") == "答案"
    assert "reasoning" not in p
