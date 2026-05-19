# What's New

## 2026-05-19

- Trimmed the IST-Core tool metadata registry to the current runtime tool surface:
  `qa_deepagent_ls`, `qa_deepagent_glob`, `qa_deepagent_grep`,
  `qa_deepagent_read_file`, `python_exec`, and `bash_exec`.
- Removed legacy QA/RAG/reviewer/platform tool names from runtime metadata while
  keeping TUI historical event rendering separate.
- Restored the IST-Core event sink modules required by streaming and replay imports:
  `JsonlFileSink` and `LangSmithSink`.
- Confirmed no additional dependency installation is needed for this fix; the project
  virtual environment already provides `langchain_core`, `deepagents`, and `langsmith`.
- Added focused event sink tests covering package exports, JSONL event persistence,
  CLI replay ordering, token flush behavior, and the default-disabled LangSmith sink.
