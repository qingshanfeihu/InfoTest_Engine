"""事件 Sink：CLI / JSONL / LangSmith / Dialog 四端订阅同一 ``IstCoreEvent`` 总线。

PgAuditSink / TraceCollector 已禁用（2026-07-23，langfuse 替代）。
"""

from main.ist_core.sinks.cli_sink import CLISink
from main.ist_core.sinks.jsonl_sink import JsonlFileSink
from main.ist_core.sinks.langsmith_sink import LangSmithSink
from main.ist_core.sinks.pg_sink import PgAuditSink  # no-op 占位
from main.ist_core.sinks.dialog_sink import DialogueCollector

__all__ = ["CLISink", "JsonlFileSink", "LangSmithSink", "PgAuditSink", "DialogueCollector"]
