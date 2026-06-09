# IST-Core 最小评审能力方案与待办

更新时间：2026-05-20

> **现状说明（2026-06-09）**：本文档是 2026-05-20 的最小评审能力规划，记录设计脉络。其中具体落地已演进，以当前代码与 `CLAUDE.md` 为准：
> - 评审模型不再是 `qwen3.6-plus`，统一走 OpenAI 兼容端点（`IST_MODEL`，示例 `mimo-v2.5-pro`）；无 `anthropic:` / provider 分支。
> - 证据来源里的 `backup/knowledge` 已随仓库清理移除；当前证据走 `knowledge/data/` + `workspace/`。
> - 评审已不止「最小 Review Prompt」：现有完整的 inline/fork 评审 skill（`test-list-review` + `review-verification` verifier）。
> 以下为历史规划原文，保留作设计参考。

## 1. 最终收口

当前不按旧版测试评审工具链迁移。Cookie 121100 实测后，结论收缩为：

- 现在只做两件事：**评审任务走 `openai:qwen3.6-plus`**，以及**追加最小 Review Prompt**。
- 不再维护 P1 / P2 排队清单。
- 其他能力只在实际失败样本、UI / 审计 / 自动化需求或明确产品需求触发时再讨论。

实测依据：

- 默认 `qwen-plus` 评审质量偏弱，曾误判本地缺少 BUG-121100 原始文档。
- `openai:qwen3.6-plus` 在不引入旧版工具、只用当前通用 `read_file` / `grep` / `ls` 的情况下，已经能提出有效评审问题。
- 旧版评审仍更完整，强在 baseline 和证据召回；但这不足以证明现在需要恢复旧版工具链。

## 2. 现在该做

### 2.1 评审模型路由

评审类任务默认使用：

```text
openai:qwen3.6-plus
```

触发条件：

- CLI / TUI 显式传入 `--task review` 或 `task_type=Review`。
- 用户输入包含“评审”“测试用例评审”“按之前评审要求”等明确评审意图。
- 用户提供 Excel / 测试列表 / 用例文件，并要求检查覆盖、缺口、测试质量。

非评审 QA 不强制使用 qwen3.6-plus。

当前不处理 `anthropic:qwen3.6-plus` 作为默认路径；该路径存在 usage metadata 兼容错误，先绕开。

### 2.2 最小 Review Prompt

评审任务在通用 system prompt 后追加以下约束，不先做独立 Skill：

```text
你正在执行测试用例评审。请使用当前可用的只读工具先检查本地证据，再下结论。

证据纪律：
1. 先从用户输入、文件名、表格内容中识别 bug id、CLI 名、feature id、关键产品词。
2. 对识别到的 bug id / CLI / feature id，优先搜索并读取本地证据，例如 defect_cleaned、defect_raw、feature json、review_inputs、conversation_history、backup/knowledge。
3. 不能把“未检索到”写成“项目不存在”。只能写“本轮未检索到 / 证据不足”，并说明实际搜过什么。
4. 链接、文件名、搜索命中不是证据；必须读取内容后才能引用。

评审基线：
除常规覆盖、步骤、预期、边界、正反向场景外，还要检查旧评审容易发现的缺口：
- 并发 / 多连接 / 长时间运行
- 超时 / 异常失败路径
- 日志 / 告警 / 可观测性
- 权限 / 非管理员 / 认证
- 多 group / 多实例隔离 / 全局与局部共存
- WebUI 语言 / 主题 / 兼容性
- IPv4 / IPv6 / 双栈
- 配置保存、reload、upgrade、回退

输出要求：
按“读取到的证据 / 基于证据的判断 / 证据缺口 / 建议修改”组织回答。
建议要具体到可补充的用例或检查点，避免泛泛建议。
```

## 3. 现在不做

以下不列入默认迁移队列：

- Excel 专用 parser / skill / tool。
- `qa_ingest_test_list`。
- `qa_summarize_test_list`。
- `qa_invoke_reviewer` 原样恢复。
- 旧版 product / asset / knowledge_ref 工具原样恢复。
- 旧版 defect_search_kb 原样恢复。
- hierarchical reviewer 整体迁移。
- async job / HIL / progress event / audit store。
- Qdrant runtime 检索作为评审前置。
- `ReviewEvidencePack`。
- `ReviewResult` / `ReviewFinding` schema。
- `DefectTicket` schema。
- `IndexedEvidenceHit` schema。
- `search_indexed_evidence` / `load_evidence_ref`。
- `fetch_defect_ticket` / Bugzilla / PLM live adapter。

## 4. 条件触发才做

| 能力 | 触发条件 |
|---|---|
| evidence locator | 多次实测发现 qwen3.6-plus 经常漏本地已有证据，例如 bug json、feature json、baseline 文档。 |
| baseline rule table | qwen3.6-plus 在多份用例中稳定漏旧评审 baseline 项，单靠 prompt 不够。 |
| Review Skill | 最小 Review Prompt 反复复用、变长、需要版本化或需要在多个入口挂载。 |
| `ReviewResult` / `ReviewFinding` | UI、审计、自动化评分或回归测试需要结构化结果。 |
| `DefectTicket` | 多来源缺陷数据需要统一展示、缓存、审计或复用。 |
| `IndexedEvidenceHit` | 真正接入 Qdrant 或多个知识库检索结果需要统一格式。 |
| `search_indexed_evidence` / `load_evidence_ref` | 本地 grep/read 成本过高，或知识库规模大到模型找不动。 |
| `fetch_defect_ticket` | 用户要求实时查 Bugzilla / PLM，且本地没有新数据。 |
| Review Workflow / `review.run` | 需要异步、HIL、审计、状态恢复、多 agent 分工。 |
| Evidence Pack | 需要跨会话复用、UI 展示、审计、多人协作或自动化回放。 |
| `/knowledge create/update/delete/list/status` | 真正开始维护产品 / 测试知识库生命周期。 |

## 5. 最小 E2E 验收

用 Cookie 121100 做最小验证：

- 输入：`backup/knowledge/orgin/Test List bug-to-case 121100 Cookie会话保持加密.xlsx`
- 模型：`openai:qwen3.6-plus`
- 工具：只允许当前通用 read / grep / ls / python

验收点：

- 能读取 Excel 并识别 Cookie / ircookie / AES / BUG-121100 主题。
- 至少尝试搜索本地 BUG-121100 / ircookie / product feature 证据。
- 不得把“未检索到”写成“项目不存在”。
- 能给出具体评审缺口，例如前置条件、预期断言、权限、日志、并发、upgrade、cookie 篡改、保存 / reload、WebUI 冗余等。
- 与旧版评审建议对比，能覆盖核心建议的一部分；未覆盖项记录为后续观察，不立即新增工具。

## 6. 待办

- [x] 评审任务默认路由到 `openai:qwen3.6-plus`。
- [x] 在评审任务中追加最小 Review Prompt。
- [x] 用 Cookie 121100 跑最小 E2E，对比旧版评审、qwen-plus、qwen3.6-plus 建议覆盖。
- [ ] 如果 E2E 发现稳定缺口，再把对应能力加入“条件触发才做”清单。

## 7. 知识管线简化（2026-05-20 落地）

E2E 验证既然通过，知识管线一并瘦身：

- 砍掉 Qdrant 向量库、RAG 检索、LLM 特征抽取（feature/scenario/architecture）、CLI 图、trunk 装箱。
- orgin/ 文档只做两件事：①KMS LLM 分桶（`product` / `test_case_list` / `test_strategy`）；②转 markdown 直出到 `knowledge/data/markdown/{product|qa}/`，agent 用 `read_file`/`grep` 直读。
- 入口：`/kms product update`（mineru → markdown/product/）+ `/kms qa update`（xlsx 走 openpyxl 直转，其他走 mineru → markdown/qa/）。
- `mineru_batch_export` 已加 zip 缓存跳过逻辑：已解析过的 stem 不调 MinerU API。
- 删除 21 个老管线模块 + `main/knowledge/` 子包；移除 `qdrant-client` / `langchain-qdrant` / `langchain-postgres` 依赖。

实测：cookie 121100 评审能从 markdown/qa + markdown/product 读到用例和规格，给出 4 段式专业评审（10 项缺口 + 12 项分级建议），覆盖 todolist 第 5 节全部验收点。

## 8. Footprint 知识树（2026-05-25 落地）

autodream 增强：在 dream consolidate 阶段，除了产出 AGENTS.md 行为规则，还额外提取**结构化产品/测试事实**到 `knowledge/footprints/` 知识树。

**为什么做**：
- 之前 dream 只产出 AGENTS.md（"用户说评审就调 skill"这类操作规则），缺少**产品事实**（"ircookie 5 种模式、enc_name 需要 passwd"）的沉淀。
- 每次评审 agent 都要重新 grep 同一份 CLI 文档，读到的还是有噪音、有冲突的原始内容。
- Footprint 是 LLM 已经验证过的精炼事实，权威度高于原始文档。

**核心设计**：
- 数据源：`memory/working/*.md`（完整读取，不受 dream gather 5000 字符截断限制）
- 提取：dream consolidate 用 haiku tier 模型（`IST_HAIKU_MODEL`，默认 deepseek-v4-flash）逐文件 LLM 提取
- 路由：剥离 `no/show/clear` 操作前缀 → 命令 token 化 → 按公共前缀分组到 leaf/trunk/branch；无 CLI 命令的 fact 直接丢弃
- 存储：`knowledge/footprints/{leaf,trunk,branch}/*.json`（5 个 section：cli/decision_rules/behaviors/known_issues/version_scope）
- 检索：`MemoryInjectionMiddleware` 自动注入（自然语言查询）+ `qa_footprint_lookup` tool（agent 主动按 CLI 命令名精确查）
- TUI：`/footprint` 总览 / show / search / stats / list

**预估满载规模**（CLI 文档 26K 行 / 891 命令）：~658 leaf 节点，~1.5 MB 内存，纯内存 dict 索引（无需 Qdrant）。

**关键 env**：`FOOTPRINT_ENABLED=1`、`IST_HAIKU_MODEL=deepseek-v4-flash`。

**后续优化点**（不阻塞上线）：
- decision_rules / behaviors 内容精炼（LLM distill 二次压缩）
- footprint trunk/branch 的丰富化策略
- agent 注入策略调优（top_k、token 上限）
- footprint 节点的合并去重策略（同一命令的多次提取结果合并）

## 9. 评审 verification 架构改造（2026-05-26 落地）

**背景**：测试评审 skill 跑出 "AI 偷懒"——主 agent 复用 memory 历史结论、verifier subagent 没注册、qa_sanity_check 工具被错误调用、最终输出只有 15 字"评审完成"。整个改造对照 cc-haha (`cc-haha/src/`) 的 verification 架构 + AgentTool / SkillTool / generalPurposeAgent 设计。

**核心改造（9 个 Step + plan-外发现的修订）**：

### 通用 agent 行为（不评审专项）

- 主 agent system prompt 加多个反偷懒 sections：
  - `Verification Contract`（仿 `prompts.ts:390-395` "you cannot self-assign"）
  - `Writing the prompt for task calls`（仿 `AgentTool/prompt.ts:103-112` "Brief like a smart colleague" + "Never delegate understanding"）+ "After the subagent returns" 子段（按 subagent 角色 relay）
  - `When NOT to use task`（仿 `AgentTool/prompt.ts:232-240`）
  - `Task Tracking`（仿 `TodoWriteTool/prompt.ts`）
  - `Reading is Not Verification`（仿 `verificationAgent.ts:55`）
  - `Faithful Reporting`（never claim done when tool failed / subagent FAIL/PARTIAL 不许软化）
  - `Communication Style`（仿 cc-haha "Tone and Style"）
  - Tool usage 加 `Parallel tool calls` + `qa_bash 多命令`
- explore subagent 仿 cc-haha `generalPurposeAgent.ts:20`：加 "the caller will relay this to the user, so it only needs the essentials" + SHARED_PREFIX
- skill listing 加 `when_to_use` 字段（含 SKIP 条件）—— LLM 看到判定 skill 是否真匹配，避免通用 QA 误调
- 删除 `qa_ask_user` 工具：评审场景被错误调用（options 必须 2-4 项的参数 derail）+ 通用 QA 不需要

### 评审专项

- 新增 `review-verification` subagent（仿 `verificationAgent.ts:10-129`）+ 注册到 main_agent.subagents_kwarg
  - prompt 含 "Your output IS the user-facing review report" + "DO NOT MODIFY THE PROJECT" + 强制 OUTPUT FORMAT（Verification command + Output observed）+ VERDICT/LEVEL 行
  - `build_verifier_inherited_sections()` 让 verifier 继承通用反偷懒约束（Read-Only / Reading-vs-Verification / Faithful Reporting / Evidence Discipline）
- 新增 `review_gate` 节点（仿 `hookHelpers.ts:70-83` Stop hook + `stopHooks.ts:257-267` blocking → userMessage 重路由）
  - 触发信号：检测主 agent 是否调过 `qa_invoke_skill('test-case-review')`
  - 检测目标：`task(review-verification)` 是否被调过 + ToolMessage 含 `VERDICT:` + `LEVEL:`
  - 重试上限 2 次，超限走 failed 分支（不抛异常，仿 `stopHooks.ts:456-472`）
- finalize 节点工程兜底：评审 gate=passed 时自动把 verifier ToolMessage 完整内容（9080 字含 VERDICT/LEVEL）当 final_answer——deepseek 不会主动复述 verifier 报告（实测 LLM 总结成 15 字 "评审完成"），runner CLI 模式必须工程层兜底
- SKILL.md 重写：
  - frontmatter 仿 cc-haha skillify 标准（name / description / when_to_use 含 Trigger + SKIP / allowed-tools / context: inline）
  - Step 0 写 todo（必做，仿 TodoWriteTool 反偷懒）
  - Steps 每步 Success criteria + 必要的 Execution / Rules / Artifacts（仿 cc-haha skillify 模板）
  - Phase 限定 ONLY path（桶隔离：product/ vs qa/，禁止从 qa/Test List_*.md 推产品定义）
  - 删除"全局约束"段（与主 agent prompt 重复，违反 cc-haha "通用约束写 system prompt / SKILL 写工作流" 哲学）
  - Step 8 简化为 cc-haha simplify Phase 3 风格 4 句话："verifier 输出是给用户的最终报告，relay"
  - Step 9 多 sheet xlsx：纯 prompt 路线（仿 simplify Phase 2 "Launch Three Review Agents in Parallel"）
- 废弃 `qa_sanity_check` 工具（cc-haha 无机械扫描工具；verifier 自发 grep 探索字面问题）
- memory write 端治理：`review_finalizer` 改为返回 None，评审结论不入 memory（仿 cc-haha 不存评审结论的源头治理）
- 一次性脚本 `scripts/maintenance/archive_review_findings.py`：archive 历史 reviews/cases + reviews/tickets 到 archive/ 子目录

### 工程基础设施

- `_sandbox.py` 模块：集中 CWD 解析 + 多根校验（仿 cc-haha `filesystem.ts:667-674` allWorkingDirectories + `cwd.ts:1-33` pwd）；exec_tools.py 路径展开为绝对路径避免 cwd 切换问题
- 主 agent `subagents_kwarg` 修复：之前 `**subagents_kwarg` 没传给 `create_deep_agent`（历史 bug 让所有 subagent 注册无效）
- task 工具 TUI 渲染：删 `subagent_start/end` 死代码事件类型（grep 确认无 emit 点）+ sink.py 用 LangChain 标准 tool_call/tool_result 驱动 SubAgentTaskMessage 状态机 running → done
- main agent recursion_limit 100（默认 25 不够评审 + verifier）；review-verification subagent recursion_limit 200

### 文档

- `docs/skill_authoring_standard.md`：项目级 SKILL 编写标准，完全对齐 cc-haha skillify.ts:96-145

### 验收

- 通用 QA "如何配置 HTTP SLB"：主 agent 不调 skill（`SKIP when` 条件生效），直接 grep `product/`，输出 2809 字完整配置说明 + CLI 命令 + 参数表
- 评审 BUG-121100：verifier 真被调用 + 返回 9080 字 VERDICT 报告 + finalize 兜底把报告复制到 final_answer（runner CLI 模式 final_answer 9080 字）
- 测试：389 passed + 1 预存 fail（`test_write_parent_not_exist` 跟本次改动无关）

### 已知限制 / 未对齐 cc-haha 但合理保留

- AsyncGenerator 状态机 vs LangGraph 节点图：架构层差异，整体改造代价过大
- 流式 TUI 渲染所有 ToolMessage vs runner 只输出 final_answer：用 finalize 工程兜底解决
- 6 种故障恢复策略（auto compact / max_token_recovery / model fallback...）：依赖 LangGraph 框架特性，deepagents 简化版
- prompt 缓存边界（global / ephemeral / section）：deepseek 没 cache 优势，意义有限
- Permission rules 4 层（rules / modes / hooks / classifier）：评审场景低风险，沙箱保护是底线

### 后续观察点（不阻塞）

- TUI 评审报告已默认全文展开 + 展示名「评审报告」；其它长 tool 仍 5 行截断
- 长上下文（46+ messages）下 deepseek-v4-pro 服从度下降——非工程能修，需观察

