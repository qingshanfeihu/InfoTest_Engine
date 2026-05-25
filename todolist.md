# IST-Core 最小评审能力方案与待办

更新时间：2026-05-20

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
- 提取：dream consolidate 用 haiku tier 模型（`QA_AGENT_HAIKU_MODEL`，默认 deepseek-v4-flash）逐文件 LLM 提取
- 路由：剥离 `no/show/clear` 操作前缀 → 命令 token 化 → 按公共前缀分组到 leaf/trunk/branch；无 CLI 命令的 fact 直接丢弃
- 存储：`knowledge/footprints/{leaf,trunk,branch}/*.json`（5 个 section：cli/decision_rules/behaviors/known_issues/version_scope）
- 检索：`MemoryInjectionMiddleware` 自动注入（自然语言查询）+ `qa_footprint_lookup` tool（agent 主动按 CLI 命令名精确查）
- TUI：`/footprint` 总览 / show / search / stats / list

**预估满载规模**（CLI 文档 26K 行 / 891 命令）：~658 leaf 节点，~1.5 MB 内存，纯内存 dict 索引（无需 Qdrant）。

**关键 env**：`FOOTPRINT_ENABLED=1`、`QA_AGENT_HAIKU_MODEL=deepseek-v4-flash`。

**后续优化点**（不阻塞上线）：
- decision_rules / behaviors 内容精炼（LLM distill 二次压缩）
- footprint trunk/branch 的丰富化策略
- agent 注入策略调优（top_k、token 上限）
- footprint 节点的合并去重策略（同一命令的多次提取结果合并）
