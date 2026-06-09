# Known Issues

记录当前架构（统一 OpenAI 兼容端点，示例小米 MiMo）下的已知 / 待观察问题。新问题请追加到末尾，标注首次出现日期与触发场景。

> 历史归档：v1.0.4 及之前基于 DashScope `qwen` + `enable_thinking` 的已知问题（`tool_choice` 与思考模式不兼容、reasoning_content token 上升等）已随「统一 OpenAI 兼容端点」收口失效，不再适用，已移除。

## 2026-06-09 / 统一 OpenAI 兼容端点

### 1. `IST_HAIKU_MODEL` 必须是端点真实存在的模型

- **现象**：footprint 提取 / KMS 分类走 haiku tier（`IST_HAIKU_MODEL`）。若配成端点不存在的模型（曾误配 `mimo-v2-flash`），调用返回 `400 Not supported model`，footprint 提取静默失败、知识树不更新。
- **应对**：`IST_HAIKU_MODEL` 必须填 `GET {OPENAI_BASE_URL}/models` 真实返回的模型 id。MiMo CN 集群当前可用 chat 模型：`mimo-v2.5-pro` / `mimo-v2.5` / `mimo-v2-pro`。
- **代码兜底**：`_llm.py::DEFAULT_HAIKU_MODEL` 缺省为 `mimo-v2.5`。

### 2. `function_llm.chat_completion` 强制 `response_format: json_object`

- **现象**：该函数硬编码 `response_format={"type":"json_object"}`，端点**只能返回顶层 JSON 对象**（不可能返回顶层数组）。任何用它的 prompt 必须要求返回 `{...}` 而非 `[...]`，否则解析失败。
- **历史踩坑**：dream consolidate 曾要求返回 `[...]` 导致永远 `LLM returned non-list`，已改 prompt 输出 `{"decisions":[...]}` + `_coerce_decisions` 兼容。
- **应对**：新增走 `chat_completion` 的结构化调用，prompt 一律约定对象格式。

### 3. dream 进程内自调度依赖进程常驻

- **现象**：dream 默认走进程内守护线程（`maybe_trigger_dream_async`，TUI 启动时触发），受五道闸约束（24h 节流 + ≥5 sessions + PID 锁）。若 `infotest` 进程从不长时间运行、且未配系统 crontab，dream 可能始终不满足触发条件。
- **应对**：进程常驻场景无需额外配置；纯短命令场景可配 crontab 跑 `python -m scripts.maintenance.memory_dream`。`IST_DREAM_INPROC=0` 关闭进程内调度。

### 4. footprint evidence 质量受限于对话内容

- **现象**：footprint 的 `evidence_quote` 必须能在源文档 grep 到（否则整条 fact 被 merger 丢弃）。提取质量取决于 agent 当时读进对话的内容——若只 grep 到描述句没读到命令语法行，evidence 只能引描述句。
- **性质**：这是数据源限制，非 bug。不强行让 LLM 引用对话里不存在的内容。
