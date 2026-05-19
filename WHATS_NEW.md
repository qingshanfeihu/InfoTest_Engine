# What's New

## 2026-05-19

- Restored the IST-Core event sink modules required by streaming and replay imports:
  `JsonlFileSink` and `LangSmithSink`.
- Confirmed no additional dependency installation is needed for this fix; the project
  virtual environment already provides `langchain_core`, `deepagents`, and `langsmith`.
- Added focused event sink tests covering package exports, JSONL event persistence,
  CLI replay ordering, token flush behavior, and the default-disabled LangSmith sink.
