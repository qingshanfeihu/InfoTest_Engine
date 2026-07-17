# IST-Core vs cc_haha：上下文引用与复用机制对比调研

> ⚠️ **历史存档（2026-07-17 归档,team4 docs 整编）**：早期 cc_haha 上下文机制对照,结论已被 RESEARCH_mimocode_backfill(prune/压缩落地)吸收。事实存档不删,现状勿引本文。

> 独立于 prompt 措辞对比，这一轮专看**上下文如何被引用、缓存、复用、卸载、压缩、回收**——即"同一份信息怎样在多轮/多 agent 之间少花 token 地重复利用"。
>
> 对比对象同上：本项目 `main/ist_core/**` vs `backup/docs_legacy/cc_haha_reference/src_*.ts`。

---

## 0. 机制总览对照表

| 复用机制 | cc_haha | IST-Core | 差距 |
|---|---|---|---|
| **system prompt 缓存分层** | 静态/动态边界 `SYSTEM_PROMPT_DYNAMIC_BOUNDARY` + `cacheScope:'global'` 跨组织复用 | 无（单段顺序拼接） | **IST 缺**，但 OpenAI 兼容端收益小 |
| **section 级缓存** | `systemPromptSection()` 注册表，computed once，`/clear`·`/compact` 才失效 | 无（每次 `build_system_prompt` 全量重算） | **IST 缺** |
| **cache-break 显式标注** | `DANGEROUS_uncachedSystemPromptSection(reason)` 强制写理由 | 无 | **IST 缺** |
| **prompt cache 命中可观测** | 内部埋点 | `streaming.py` 读 `prompt_cache_hit/miss_tokens` 透传 | 基本对齐（IST 只读不优化） |
| **每轮注入去重** | attachment delta（MCP/agent listing 增量） | `_has_recent_reminder`（近 4 条内不重复 skill/memory reminder） | 思路一致，IST 更朴素 |
| **会话内材料复用（prompt 级）** | 隐含 | **显式 "Step 0 — Reuse existing material first"** | **IST 更强** |
| **历史自动压缩（compact）** | 自动 summarization，"unlimited context" | `summarization_middleware(max_tokens=28000)` | 基本对齐 |
| **工具结果卸载（offload）** | 子 agent 隔离 + fork output_file「不要 peek」 | deepagents `FilesystemMiddleware` 把大结果落 `runtime/large_tool_results/` | 机制不同，**IST 缺"卸载后如何按需取回"的 prompt 指引** |
| **function result clearing / micro-compact** | `CACHED_MICROCOMPACT`：旧 tool result 自动清，保留最近 N | 无 | **IST 缺** |
| **"先记下后面要用的信息"** | `SUMMARIZE_TOOL_RESULTS_SECTION`（结果可能被清，先抄关键信息） | 无 | **IST 缺** |
| **子 agent 上下文隔离** | Explore/Plan/Verify 独立窗口，只回报结论 | explore/verifier 独立窗口，raw 不回主上下文 | 基本对齐 |
| **fork 共享父缓存** | fork 继承父 context + prompt cache（不设 model） | **无 fork**（只有独立 subagent，不共享缓存） | **IST 缺** |
| **跨会话状态复用（checkpoint）** | session resume | AsyncSqliteSaver / Postgres checkpoint，thread_id 续接 | 基本对齐 |
| **跨会话知识复用（记忆）** | memdir 轻量 | 三层记忆 + Footprint，按 query top-k 注入 | **IST 更强** |
| **LLM 调用结果缓存** | growthbook 配置缓存等 | `function_llm` + `LLMCache`（KMS/footprint/dream 用，按内容 hash） | **IST 有专用缓存** |
| **subagent runnable 复用** | agent 定义加载 | `_SUBAGENT_RUNNABLE_CACHE` 按 name 缓存编译产物 | 基本对齐 |
| **env/model 信息复用** | env section 缓存 + cutoff | 默认不注入 env（见上一轮调研） | **IST 弱** |

---

## 1. System Prompt 缓存与复用

### cc_haha
- `getSystemPrompt`（`src_constants_prompts.ts`）把数组切成两半：`SYSTEM_PROMPT_DYNAMIC_BOUNDARY` **之前**是静态可缓存内容（intro / system / doing-tasks / actions / tools / tone / output-efficiency），可用 `cacheScope:'global'` **跨组织复用同一前缀**；**之后**是 session 专属动态段。
- 动态段经 `systemPromptSection(name, compute)`（`src_constants_systemPromptSections.ts`）：每段 computed once → 存 `SystemPromptSectionCache`，直到 `/clear` 或 `/compact` 才 `clearSystemPromptSections()`。
- 易变内容（MCP instructions）用 `DANGEROUS_uncachedSystemPromptSection(name, compute, reason)` 标注——**必须写明为什么要破坏缓存**。
- 大量注释解释"把某段放到 boundary 之后是为了避免 `2^N` 个缓存前缀变体"（如 PR #24490/#24171）。即**缓存碎片化是一等公民关注点**。

### IST-Core
- `build_system_prompt`（`_prompt.py`）：每次调用把 13 段 `"\n\n".join()` 全量重算，无缓存、无静态/动态分层、无 cache-break 标注。
- `streaming.py:109` 读取 `prompt_cache_hit_tokens / prompt_cache_miss_tokens` 透传到 UI，说明**关心命中率但不主动优化前缀稳定性**。

> **差距**：IST 不做 prompt 前缀缓存工程。考量：
> - DashScope/DeepSeek 的 OpenAI 兼容缓存能力弱于 Anthropic，收益确实低；
> - 但 env / memory-context / skill-reminder 是"每轮变"的，IST 把它们当**消息**注入（不是 system 段），反而天然避免了 system 前缀碎片——这点设计上是对的。
> - 真正可改进的是：`build_system_prompt` 的 13 段身份/纪律内容是**完全静态**的，可以模块级缓存成常量字符串，省去每轮重新 join + 函数调用。当前每轮重算虽便宜，但无必要。

---

## 2. 会话内材料复用（最大正向差距）

### IST-Core 独有：Step 0 显式复用
`_prompt.py` 的 `_exploration_workflow_section`：

> **Step 0 — Reuse existing material first.** Before any new tool call, scan the current conversation for relevant prior tool results. If the user is asking a follow-up like "检查 cli" / "再核对一下"，且上一轮已经产出了 cli 命令、文件内容或行号，直接基于已有材料回答，不要再 ls / grep / read_file。

配合 `_reading_vs_verification_section` 里的 "I already saw this earlier — saw is not verified. Re-grep if you're going to make a claim now." 形成一组**张力约束**：默认复用已有材料，但要"下新结论"时必须重新验证。

### cc_haha
- 无逐轮"先扫描已有 tool result 再决定是否新调工具"的显式 prompt。其复用主要靠**架构**（子 agent 隔离 + 自动 compact），而非提示 LLM 主动复用会话内材料。

> **结论**：IST 在"prompt 引导 LLM 复用会话内已有证据"这点上**比 cc_haha 更显式、更强**，契合其评审业务（同一文件被反复追问）。

---

## 3. 工具结果的卸载与按需取回

### cc_haha 三件套
1. **`SUMMARIZE_TOOL_RESULTS_SECTION`**：`When working with tool results, write down any important information you might need later in your response, as the original tool result may be cleared later.`——提前告知 LLM"结果会被清，先抄关键信息"。
2. **`getFunctionResultClearingSection`**（`CACHED_MICROCOMPACT` gate）：`Old tool results will be automatically cleared from context to free up space. The N most recent results are always kept.`——把"自动清理 + 保留最近 N"这条**机制讲给 LLM**。
3. **fork output_file「不要 peek」**：fork 的 raw 输出落到 `output_file`，prompt 明确 `Don't peek` / `Don't race`——卸载后默认不取回。

### IST-Core
- deepagents `FilesystemMiddleware` 把大 tool 结果落 `runtime/large_tool_results/<call_id>`（`backend.py:126` 注释，目录实测有 `call_*` 产物），`file_tools._PLATFORM_DENIED_TOP_LEVEL` 把它列入黑名单（agent 视野隔离）。
- **但**：IST 的 system prompt **没有任何一段**告诉 LLM"你的大结果被卸载了 / 旧结果可能被清 / 需要时怎么取回 / 先抄关键信息"。卸载是后台静默发生的。

> **差距**：IST 有卸载机制（落盘），但**缺对应的 prompt 契约**。后果：
> - LLM 不知道结果会被压缩/清理，可能在 compact 后丢失它以为还在的证据；
> - 无"先记下后面要用的信息"指引，compact 风险更高（项目自己在 `_prompt.py:154` 注释里也承认"compact 后忘记自己在哪一步"，靠 todo list 兜底）。
> - 建议补一句 SUMMARIZE_TOOL_RESULTS 等价物 + 一句"大结果会落盘，需要细节时重新 read_file 而非凭记忆"。

---

## 4. 历史压缩（compact / summarization）

| | cc_haha | IST-Core |
|---|---|---|
| 机制 | 自动 summarization，宣称 "unlimited context" | `summarization_middleware(max_tokens=28000)`（deepagents 内置） |
| 触发 | 接近 context limit | 超 28k token |
| 向 LLM 说明 | **有**：`The conversation has unlimited context through automatic summarization.` + `The system will automatically compress prior messages...` | **无显式说明** |
| compact 后恢复 | section cache 清空重算 | todo list 兜底（`_prompt.py` 注释："compact 后从 todo list 恢复进度"） |

> **差距**：两边都有自动压缩，但 cc_haha **把"上下文会被自动压缩、所以无限"这件事告诉 LLM**，让模型放心长对话、并主动 summarize 关键信息。IST 静默压缩，LLM 不知情。

---

## 5. 子 Agent / Fork 的上下文复用

### cc_haha 双模
- **Subagent（带 subagent_type）**：零上下文，独立窗口，只回报结论（Explore/Plan/Verify/general-purpose）。
- **Fork（省略 subagent_type）**：**继承父 context + 共享父 prompt cache**，prompt 明确 "Forks are cheap because they share your prompt cache. Don't set model on a fork — a different model can't reuse the parent's cache."——这是**显式的缓存复用设计**。

### IST-Core
- 只有 subagent 路径（explore / review-verifier / extractor），各自独立窗口、独立 model（haiku/opus），raw 不回主上下文——上下文**隔离**正确。
- **没有 fork 概念**，也就没有"共享父缓存"的复用。每个 subagent 都是冷启动。

> **差距**：IST 缺 fork 式"继承上下文 + 共享缓存"的轻量委派。当前 subagent 全冷启动，对"基于主 agent 已收集证据再深挖"的场景，要么主 agent 把证据塞进 brief（重复 token），要么 subagent 重新检索（重复工作）。`_writing_fork_skill_brief_section` 已在教"怎么写 brief 把上下文带过去"，但本质还是**手工复制上下文**，不是缓存复用。

---

## 6. 跨会话复用：checkpoint + 记忆 + LLM 缓存

这是 **IST 明显强于 cc_haha** 的一组：

### 6.1 Checkpoint（对话状态）
- `graph.py`：AsyncSqliteSaver（TUI）/ SqliteSaver（print）/ PostgresSaver，按 `thread_id` 续接整段对话。`/working/` 路径随 checkpointer 落盘（`backend.py`）。
- cc_haha 也有 session resume，量级相当。

### 6.2 记忆（跨会话知识）
- 三层 + Footprint，`MemoryInjectionMiddleware._build_reminder` 每轮按 query **top-k** 拼装：working notes（40 行）+ key_resolvers 命中的 long-term（≤800 字截断）+ `read_long_term(query, top_k)` 语义召回 + `read_footprints(query, top_k=2)`。
- 每段都做 `≤800 字截断`，控制注入体积——**这是精细的"按需引用 + 限额复用"**。
- cc_haha 仅 `loadMemoryPrompt()` 轻量 memdir，无分层 top-k 召回。

### 6.3 LLM 结果缓存
- `function_llm.py` + `main/common/llm_cache.LLMCache`：KMS 分类 / footprint 提取 / dream consolidate 的 LLM 调用按**内容 hash 缓存**，`QA_LLM_CACHE_DISABLED=1` 可关。CLAUDE.md 也提到"结果走 `function_llm.chat_completion` 缓存"。
- cc_haha 无等价的内容级 LLM 结果缓存（它的 cache 是 growthbook 配置/prompt 前缀）。

### 6.4 Subagent 编译产物复用
- `skills/loader.py::_SUBAGENT_RUNNABLE_CACHE` 按 name 缓存编译好的 subagent runnable，热重载用 `clear_subagent_cache()`。

> **结论**：跨会话维度，IST 的复用资产（checkpoint + 三层记忆 top-k + 内容级 LLM 缓存 + runnable 缓存）**整体强于 cc_haha**。

---

## 7. 每轮注入的去重复用

| | cc_haha | IST-Core |
|---|---|---|
| skill 提醒 | DiscoverSkills attachment + delta（增量，避免重复全量） | `_has_recent_reminder`：近 4 条消息内已有同类 `<system-reminder>` 则跳过（`per_turn_skill_reminder.py:166`） |
| memory 提醒 | —— | `_has_recent_reminder`：近 4 条内已有 `<memory-context>` 则跳过（`middleware.py:43`） |
| agent listing | attachment delta（MCP/agent 变化才重发，省缓存） | 无动态 agent listing |
| 注入位置 | system / attachment | 插在最后一条 HumanMessage **之前**（`middleware.py:_inject`），不持久化到 state（避免被当用户输入） |

> **结论**：思路一致（都避免每轮重复堆同样的提醒），cc_haha 用 attachment delta 更省缓存，IST 用"近 N 条去重 + 不落 state"更朴素但够用。IST 的"注入不持久化"是为防 reminder 被 add_messages 当成用户新输入（项目踩过坑）。

---

## 8. 差距汇总（按优先级）

### P0 — 低成本、直接收益
1. **补"工具结果会被压缩/清理"的 prompt 契约**：移植 cc_haha 的 `SUMMARIZE_TOOL_RESULTS_SECTION`（"先抄下后面要用的关键信息，原始结果可能被清"）+ 一句"上下文超限会自动 summarize"。直接降低 compact 后丢证据的风险，与现有 todo-list 兜底互补。
2. **补"大结果已卸载、需细节请重新 read_file"指引**：IST 已落盘 `large_tool_results/`，但 LLM 不知情。一句话告诉它"不要凭记忆复述大文件内容，需要精确行号就重新 read"。和 Reading≠Verification 同源。

### P1 — 工程优化
3. **静态 system prompt 段缓存成常量**：`build_system_prompt` 的 13 段中 11 段完全静态，可在模块加载时拼一次存常量，每轮只拼 env/tools 动态尾巴。省每轮重复 join/函数调用（微小但无副作用）。
4. **评估 fork 式委派**：若要"基于主 agent 已收集证据继续深挖"，当前只能手工把证据塞 brief（重复 token）。可评估引入"继承上下文"的轻量子任务，减少证据重复传递。

### P2 — 按需
5. **micro-compact / function result clearing**：deepagents 的 summarization 已够用；若长评审会话频繁触顶，可参考 cc_haha"保留最近 N 个 tool result，旧的清理"做更细粒度回收。
6. **env section 默认注入并缓存**（与上一轮 P0 重叠）。

### IST 相对 cc_haha 的正向差距（保留强化）
- **Step 0 会话内材料复用** + Reading≠Verification 张力约束（prompt 级复用，cc_haha 无）。
- **三层记忆 top-k 按需注入 + ≤800 字限额**（精细的引用复用）。
- **内容级 LLM 结果缓存**（`LLMCache`，cc_haha 无等价物）。
- **注入不落 state**（防 reminder 被当用户输入）。
- subagent runnable 缓存、checkpoint 续接。

### 不建议引入
- 跨组织 `cacheScope:'global'` 前缀复用：OpenAI 兼容端收益低，工程复杂度高，不划算。

---

## 附：本轮涉及的关键代码位

**cc_haha**
- `src_constants_prompts.ts` — `SYSTEM_PROMPT_DYNAMIC_BOUNDARY`、`SUMMARIZE_TOOL_RESULTS_SECTION`、`getFunctionResultClearingSection`、fork 共享缓存说明
- `src_constants_systemPromptSections.ts` — section 缓存 + `DANGEROUS_uncachedSystemPromptSection`
- `src_tools_AgentTool_prompt.ts` — fork「不要 peek/race」、共享父缓存

**IST-Core**
- `main/ist_core/agents/_prompt.py` — Step 0 复用、Reading≠Verification、Task-Tracking（compact 兜底）
- `main/ist_core/agents/main_agent.py:89` — `summarization_middleware(max_tokens=28000)`
- `main/ist_core/memory/middleware.py` — `_build_reminder` top-k 注入 + `_has_recent_reminder` 去重 + `_inject` 不落 state
- `main/ist_core/memory/backend.py:126` — 大结果落 `runtime/large_tool_results/`
- `main/ist_core/graph.py` — Async/Sync SQLite / Postgres checkpoint
- `main/function_llm.py` + `main/common/llm_cache.py` — 内容级 LLM 结果缓存
- `main/ist_core/skills/loader.py:34` — `_SUBAGENT_RUNNABLE_CACHE`
- `main/ist_core/streaming.py:109` — prompt cache 命中率透传
