# 调研:MiMo-Code(opencode 谱系)设计对照与 IST-Core 补齐(2026-07-05)

> 源:github.com/XiaomiMiMo/MiMo-Code 浅克隆至 scratchpad,精读 `packages/opencode/src` 的 skill/agent/session-compaction/memory 四个子系统(~3k 行核心 + compose skill 套件)。本文档记录:它有什么、IST-Core 对应现状、补齐决策(带理由,含"不补"的)。

## 一、上下文压缩(session/compaction.ts + prompts)

| MiMo-Code 设计 | IST-Core 现状 | 决策 |
|---|---|---|
| **工具输出剪枝**(prune):从后往前保护最近 40k token 的工具输出,更旧的整体抹除(标记 compacted),skill 输出受保护、遇摘要边界停——**确定性、零 LLM 成本**,先于摘要触发 | 无。大结果有创建时 offload,但中等结果随轮堆积,直到摘要一把全总结(有损) | **补(A 项,本轮落地)**:`ToolResultPruneMiddleware`——保留头部 160 字符(文件指针/要点常在头部,比 MiMo 全抹更稳)+ 剪枝标记与恢复指引 |
| 尾轮保真:最近 2 轮原文保留(预算 25% usable,2k-8k 夹紧),只摘要头部 | deepagents 默认 keep 参数(消息数/分数);不可配(见下) | 不动(默认已有 keep 语义) |
| 锚定式增量摘要(previous-summary 合并更新,非重摘) | deepagents 摘要撤出历史落 `/conversation_history/<thread>.md` 可回读——不同路线,各有解 | 不补 |
| 结构化摘要模板(Goal/Instructions/Discoveries/Accomplished/Files) | deepagents 默认模板,`create_summarization_middleware(model, backend)` 只收两参,**无模板/阈值入口**;且 create_deep_agent **无条件自动挂**它,自己再传=双摘要 | **待办 B**:要定制须走 harness profile 排除+自建,侵入大,挂对照轮后评估 |
| 压缩跑专用 compaction agent(可配便宜模型) | 摘要用主模型 | 同上待办 B |
| **【bug 发现】** — | `main_agent.py` 的 `summarization_middleware(max_tokens=28000)` 在 deepagents 0.5.9 **导入必失败**(该版只有 `SummarizationMiddleware` 类/`create_summarization_middleware` 工厂),静默走 except → 28k 配置从未生效,实际一直是 create_deep_agent 默认阈值 | **修(Fix0,本轮落地)**:删死代码,注释钉死"默认自动挂载,勿再传自建实例" |

## 二、记忆(memory/service.ts + tool/memory.txt + path-guard)

| MiMo-Code 设计 | IST-Core 现状 | 决策 |
|---|---|---|
| **BM25/FTS5 检索式记忆**:盘上 md=事实源,SQLite FTS5 懒 reconcile(fingerprint=size+mtime),scope/type 过滤,**相对分数地板**(保 top1,砍 <0.15×top 的常见词噪声),3 倍过取 | 只有**推**(MemoryInjectionMiddleware top-k 注入),没有**拉**;且 `memory/` 在文件工具平台黑名单里——agent **无法主动检索自己的长期记忆** | **补(C 项,本轮落地)**:`kb_memory_search` 工具——FTS5+BM25+相对地板;CJK 用 bigram 预分词(unicode61 不切中文,trigram 又要求 ≥3 字);top1 直接带正文头(agent 读不到 memory/ 路径,工具必须把内容带回来) |
| 检索升级阶梯写进工具说明(1-3 个稀有词/命中即权威/0 命中→换更稀词→grep 目录→history 工具) | 无 | 随 C 项进 docstring(适配本项目) |
| checkpoint-writer fork:压缩/分页时把会话检查点/任务叙事写进 memory(sessions/<sid>/checkpoint.md、tasks/<tid>/),**前缀缓存对齐 fork**(冻结父请求前缀,工具 schema 镜像父,运行时限权不动 schema) | dream/distill 已有(离线蒸馏);任务叙事≈worker 机读尾块+fanout 落盘(已有) | 不补(重合度高);**前缀缓存对齐思想记入 C2 注释**(见四) |
| memory-path-guard:writer 角色级写路径白名单(精确到文件名模式) | memory store 写入白名单已有(记忆子系统安全不变量) | 不补 |
| 子 agent 进度模板强制(§1-§5 必填节,缺节机器打回) | worker 机读尾块(状态:/产物:)+ orchestrator 落盘为准 | 不补(同类机制已有) |

## 三、Skill 机制(skill/index.ts + tool/skill.ts + compose 套件)

| MiMo-Code 设计 | IST-Core 现状 | 决策 |
|---|---|---|
| 多源发现:builtin/compose 捆绑包 + 外部生态目录(.claude/.codex/.opencode)+ 配置路径 + **git URL 拉取** | 单目录 + dyn_skills | 不补(私有工程固定 skill 集,多源=多攻击面) |
| skill 加载输出附**捆绑文件抽样清单**(`<skill_files>`)+ base dir 指针 | invoke_skill 已列 reference/ 目录 ✓ | 已对齐 |
| `hidden` frontmatter + 权限过滤按 agent 出列表 | fork skill 不进 listing(user-invocable 控制)✓ | 已对齐(机制不同效果同) |
| compose 过程 skill 套件(plan/execute/verify/parallel/subagent/tdd/…,hidden,由 compose 模式编排) | 领域 skill 为主;过程纪律在 `<rules>`/CLAUDE.md | 不补(理念差异:IST 把过程纪律放常驻规则,MiMo 放按需 skill——各自成立) |
| 压缩时保护 skill 工具输出不被剪 | — | 随 A 项落地(protect invoke_skill/ask_user) |
| self-extend(运行时自造 skill) | agent_define(自造 agent,机械校验) | 已对齐(方向同,实现更硬) |

## 四、Agent 机制(agent/agent.ts)

| MiMo-Code 设计 | IST-Core 现状 | 决策 |
|---|---|---|
| 权限代数:defaults→agent→user→**hardPermission**(不可被配置放松的不变量,如 plan 模式禁写) | 工具白名单 + 文件沙箱(代码级硬闸) | 不补(我们的硬闸在代码层,更硬) |
| **计划模式禁写用 deny+allow 例外而非改工具表**——"tool-list mutation busts prompt cache"(其 PR #1207) | C2 tool_gating **改工具表**——但激活信号单调递增(组只增不减),整会话 schema 至多变 2 次,缓存各失效一次可摊销 | 不改;**把缓存考量写进 tool_gating 注释**(本轮落地),防将来有人加"组回收"逻辑破坏单调性 |
| Agent.generate:LLM 从描述生成 agent 定义 | agent_define:main(本身是 LLM)传参,工具机械校验拼装 | 已对齐(我们把"生成"与"校验"分层,更符合 correct-by-construction) |
| 专用小 agent 矩阵:title/summary/compaction/checkpoint-writer/dream/distill 各配模型档 | dream/distill 已有;compaction 见待办 B | 部分待办 B |

## 五、本轮落地清单

1. **Fix0**:main_agent.py 删除 `summarization_middleware` 死导入块(28k 配置从未生效),注释钉死 deepagents 默认装配事实。
2. **A**:`middleware/tool_result_prune.py` —— 确定性工具结果剪枝(保护最近 2 轮 + 最近 N 字符预算 + 保护 invoke_skill/ask_user + 小结果豁免 + 头部 160 字符保留);默认开(`IST_PRUNE_TOOL_OUTPUTS=0` 关,预算 `IST_PRUNE_PROTECT_CHARS`)——它先于摘要生效,剪枝(留头+可恢复)严格优于被整段摘要有损吞掉。
3. **C**:`tools/knowledge/memory_search.py` → `kb_memory_search` —— 记忆 FTS5/BM25 拉式检索(CJK bigram),index 落 runtime/,懒 reconcile,相对分数地板,top1 带正文;注册进 main agent(kb_ 前缀=基础组常驻)。
4. C2 注释补缓存单调性约束。

## 六、待办 B 收口(2026-07-08,提示工程改造批 0)

- **fraction 阈值真相**:deepagents 摘要 fraction 仅当 `model.profile.max_input_tokens` 存在才生效;自定义 ChatOpenAI 的 profile 恒 None → 实际一直走 **tokens=170000 绝对阈值 + keep 6 条消息** 兜底档(2026-07-05 注释所称"fraction 阈值"当时不实)。实测端点窗口 **1,048,565 tokens**(deepseek-v4-pro/flash 同值,超限报错原文)——即此前在窗口 16% 处就砍到 6 条。
- **已修**:`_llm.py::_build_chat_model` 按实测窗口挂 `profile`(env `IST_MODEL_CTX` 覆盖,0=退回兜底档),fraction(0.85 触发/0.10 保留)自此生效。单测 `tests/ist_core/agents/test_llm_model_profile.py`。
- **仍待办**:定制摘要模板/便宜 compaction 模型(deepagents 无入口);fork 摘要层(现仅剪枝+recursion_limit,末轮 max worker 实测单 fork 500k+ token)——待下一次对照轮的上下文压力数据定。
- **顺带实测**:`parallel_tool_calls` 端点默认即开(不传参数也返回多 tool_calls),无需配置;并行杠杆在 prompt(`_prompt.py::_tool_cadence_section` 经 inherited 注入 fork)。提示面构建标准全文:`docs/PROMPT_ENGINEERING_STANDARD.md`。
