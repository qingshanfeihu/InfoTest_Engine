"""事件 Sink：CLI / JSONL / LangSmith / PgAudit / Dialog 五端订阅同一 ``IstCoreEvent`` 总线。"""

from main.ist_core.sinks.cli_sink import CLISink
from main.ist_core.sinks.jsonl_sink import JsonlFileSink
from main.ist_core.sinks.langsmith_sink import LangSmithSink
from main.ist_core.sinks.pg_sink import PgAuditSink
from main.ist_core.sinks.dialog_sink import DialogueCollector

__all__ = ["CLISink", "JsonlFileSink", "LangSmithSink", "PgAuditSink", "DialogueCollector"]
