# 调研:sst/opencode 架构对照与 IST-Core 补齐(2026-07-05)

> 源:github.com/sst/opencode 浅克隆(HEAD b7e4f1ef,2026-07-05)至 scratchpad,精读 `packages/opencode/src` 的 session / provider / permission / lsp / plugin / server / agent 七个子系统(TS)。本文是 `docs/RESEARCH_mimocode_backfill.md` 的续篇——MiMo-Code 是 opencode 谱系衍生,skill / 上下文压缩(compaction+prune) / 记忆 / fork 四个子系统上一轮已对照并补齐(kb_memory_search / ToolResultPrune / 缓存单调性注释),**本轮只覆盖上一轮没碰的面**。对照基准:IST-Core 现状按 `main/ist_core` 源码实读(agents/_llm.py、tui/bridge.py、middleware/、web_server.py、tools/device/ssh.py 等)。文内 opencode 路径省略前缀 `packages/opencode/src/`。

结论先行:opencode 是「provider 能力元数据表 + 消息库即状态机 + 声明式 allow/ask/deny 权限 + 结构化 client/server」;IST-Core 是「单一 OpenAI 兼容端点 + LangGraph checkpoint + 工具内硬闸 + PTY 字节流桥」。两边多数差异是**通用产品 vs 私有测试工程 agent** 的定位差,该补的集中在 provider 适配摩擦与长会话稳定性两处。

## 一、provider 适配层(provider/transform.ts + provider.ts + models-dev + session/llm/)

IST-Core 在 minimax/deepseek/mimo 上踩过的坑(非流式 reasoning_content 漏收、数组参数被 stringify、空 chunk 死挂),opencode 几乎每个都有对应机制——但组织方式不同:它把怪癖**集中成一个纯函数兼容库 + 一张能力元数据表**,而非子类方法 patch。

| opencode 设计 | IST-Core 现状 | 决策 |
|---|---|---|
| **能力元数据表**(packages/core/src/models-dev.ts):每模型声明 `reasoning` / `temperature`(是否支持温度) / `tool_call` / `interleaved`(reasoning 回传字段名,`reasoning\|reasoning_content\|reasoning_details` 三选一) / modalities / limit / cost。从 models.dev API 拉取,磁盘缓存 + flock 防多进程竞争 + 每小时后台刷新。transform 层按表驱动,零 if-else 猜测 | 无表。唯一近似物是 `main/common/llm_helpers.py::thinking_param_for_model`(按模型族前缀给 `extra_body.thinking` 形状);reasoning 字段名、温度抑制、strict 支持散在 `_llm.py` 的 `ChatOpenAIWithReasoning` 四个方法 patch 里,新供应商接入要通读子类 | **补(A 项,Top1)**:轻量进程内 `MODEL_CAPS` 字典(不引外部服务)——`llm_helpers.py` 泛化为一张表:`{族前缀: {thinking 形状, reasoning 字段, 温度抑制, strict 可用}}`,`_llm.py` 各 patch 读表。新供应商=填一行,不再读四个方法 |
| **消息历史修复**(transform.ts `normalizeMessages`):per-vendor 纯函数——deepseek 每条 assistant 必须带 reasoning part(缺则补空);`interleaved.field` 声明的字段**空值也回传**(注释点名 DeepSeek);mistral toolCallId 重写为 9 位字母数字 + tool→user 序列间补 "Done." assistant 消息;anthropic 过滤空消息;`sanitizeSurrogates` 全量清洗坏 UTF-16 代理对 | reasoning_content 双向 patch 已有且更深:`_get_request_payload` 出方向回填、`_convert_chunk_to_generation_chunk` 流式入方向、`_create_chat_result` 非流式入方向补收(2026-07 修),另有 opencode 没有的 minimax `<think>` 内联剥离状态机。surrogate 清洗无 | reasoning 回传**已对齐**(实现更深)。surrogate 清洗**微补(可选)**:`ToolEnvelopeMiddleware` 包装工具结果时顺手 `.encode('utf-8','replace').decode()`——设备回显/二进制截断进消息history 的一行保险 |
| **流式防挂双闸**(provider/provider.ts):`headerTimeout`(首包响应头 10s 超时,openai 默认开,L35/L87)+ `chunkTimeout`(wrapSSE 对 SSE **逐次 read** 计时,超时 abort+cancel reader,L37);多信号 `AbortSignal.any` 合并 | 三层已有:langchain `request_timeout`(默认 300s 总超时)、`LANGCHAIN_OPENAI_STREAM_CHUNK_TIMEOUT_S`(120s parsed-chunk 层)、自研 stall 守卫 `_chunk_has_substance`(180s 连续无实质内容断流+安全重发)——substance 判定比字节判定强,能识破 keep-alive 空 chunk 骗超时 | chunk 层**不补**(已有等价且更细)。**首包超时补(C 项,Top3)**:IST 现状首包挂会死等 300s 总超时;`_build_chat_model` 的 `request_timeout` 改传 `httpx.Timeout(connect=10, read=<IST_LLM_TIMEOUT>, ...)`,对应 opencode headerTimeout=10s,一行工程量 |
| **坏工具调用自愈**(session/llm.ts `experimental_repairToolCall` + tool/invalid.ts):工具名大小写错→lowercase 修复;参数 schema 校验失败→改路由到 `invalid` 工具,其输出把错误原文回给模型("The arguments provided to the tool are invalid: …"),循环自愈不崩 | langgraph ToolNode `handle_tool_errors` 已把工具异常转 ToolMessage 回模型;stringify 数组问题走的是结构治理(原生数组通道+`IST_TOOLS_STRICT`) | **不补**(错误回传已有;stringify 的根治在通道不在修复)。lowercase 修复技巧记录备用 |
| **工具 schema 按厂商降级**(transform.ts `schema()`):OpenAI 布尔 schema→string、const→enum、type 推断;moonshot/kimi 拒 `$ref` 兄弟键、tuple items;Gemini 整数 enum→字符串、type 数组→anyOf、required 过滤 | 单端点 + 自家 pydantic schema,无需矩阵。mimo strict 数组 stringify 已修(strict 开关) | **不补**。若将来接 kimi/gemini 系端点,先查此表(transform.ts:1419-1559)再调试 |
| **采样参数族表**(transform.ts `temperature/topP/topK`):qwen 0.55 / minimax-m2 1.0+0.95+topK / kimi 按变体分——模型族最佳缺省一张表 | thinking 开启时不发 temperature/top_p(minimax 收到 enabled 直接 400 的教训),否则 setdefault(0.0/0.5) | **已对齐**(形式不同);族级缺省并入 A 项能力表同一张 |
| **options 级联 + 会话亲和**(session/llm/request.ts):options 四层合并(provider transform→model.options→agent.options→variant);headers 带 `x-session-affinity`/`X-Session-Id`(网关缓存路由);**工具按字母序 toSorted**(schema 顺序确定→提示缓存稳定);OpenAI Responses 族硬编码 `strict:false`(Codex parity) | 单端点无级联需求。工具顺序:deepagents 组装,顺序未显式钉死 | **不补**级联。**微补(可选)**:工具列表注册处显式排序钉死 schema 顺序(缓存稳定,与 C2 单调性注释同主题);session 亲和头待验证 mimo 网关是否消费,先不动 |
| **prompt cache 注入**(transform.ts `applyCaching`):anthropic 系给首 2 条 system + 末 2 条消息挂 cache_control,per-provider 键名表 | OpenAI 兼容端点自动缓存(prompt_cache_hit/miss_tokens 已在 streaming.py 读取上报) | **不补**(端点自动) |
| **SDK 实例管理**(provider.ts):BUNDLED_PROVIDERS 动态 import 映射;非捆绑 provider 运行时 `Npm.add` 安装;实例按 (providerID,npm,options) 哈希缓存;baseURL 支持 `${ENV}` 插值 | 单 ChatOpenAI 子类,`_build_chat_model` 每次构造 | **不补**(单端点无此问题) |
| **跨模型换机卫生**(session/message-v2.ts:245):历史消息 `differentModel` 时剥 providerMetadata、reasoning part 降级为普通 text(异厂签名不外泄);pending/running tool_use 回放时补 "[Tool execution was interrupted]" 假 result 保证 tool_use/tool_result 配对;签名 reasoning 块间空 text 分隔符改单空格(Anthropic 怪癖) | 会话中途换 `IST_MODEL` 重启:`_get_request_payload` 会把旧厂 reasoning_content 无条件回填给新厂(兼容端点多忽略未知字段,风险低);半截 tool_call 由 LangGraph super-step 原子性兜底(见二) | **不补**,记录风险点:若换厂后首轮 400,先查 reasoning_content 回填是否被新厂拒收(_llm.py `_get_request_payload` 加族判断即可修) |
| **按模型族选底座 prompt**(session/system.ts `provider()`):gpt→beast/codex、gemini、claude、kimi 各一份系统提示 | 单一 `_prompt.py` 五块 XML 服务所有供应商 | **不补**(域 prompt 主导,模型族差异小;34-case 对照轮未见族级 prompt 缺陷) |

## 二、session 主循环与错误恢复(session/prompt.ts + processor.ts + retry.ts + run-state.ts)

| opencode 设计 | IST-Core 现状 | 决策 |
|---|---|---|
| **轮级重试包整条流**(processor.ts:660 `Effect.retry(SessionRetry.policy)`):LLM 流中断(5xx/限流/网络)→整轮重建流续跑;SDK 层 maxRetries=0,重试权全在会话层;**重试状态推 UI**(status=retry,含 attempt/message/下次时间,session/status.ts);退避尊重 `retry-after-ms`/`retry-after` 头(秒或 HTTP 日期),无头 cap 30s(retry.ts:35);5xx 一律重试即使 SDK 未标 retryable;context overflow 永不重试(retry.ts:70) | 分层但有缝:langchain `max_retries=2` 只覆盖请求建立,流中断不管;`resilience.py::run_with_resilience`(指数退避重跑 graph.invoke)**只挂 runner.py print 路径**;TUI 路径瞬态=一行提示「可直接重发」,本轮报废等用户手动重发 | **补(B 项,Top2)**:TUI 瞬态自动续跑——`tui/bridge.py::_run_in_thread` 对 `is_transient_error` 挂退避重试(复用 resilience.py 既有件),重试状态发事件进 footer(「重试 2/4·12s 后」,对齐 opencode status=retry 可见性);退避读 `retry-after` 头(HTTPStatusError.response.headers)。checkpoint 幂等性 langgraph 已给(重 invoke 从上个完整 super-step 续) |
| **消息库即状态机**(prompt.ts:1081 runLoop):每轮从持久化消息推导下一步(pending tool?→continue;compaction task?→process;overflow?→create task;否则调 LLM),崩溃/重启后从库恢复;「provider 返回 stop 但消息里有 tool_calls→照样继续跑」的怪癖容忍(prompt.ts:1103) | LangGraph checkpointer(Postgres→SQLite→InMemory 三级降级)本质同型:state 按 super-step 原子持久化,重启续跑 | **已对齐**(靠 langgraph)。差异记录:opencode 粒度到 part(半步可恢复),IST 粒度到 super-step(qa_node 一轮),中断丢整轮但不出现半截脏态——对 IST 场景够用 |
| **abort 一致性清理**(processor.ts:539 cleanup):中断后孤儿 running tool_call 统一标 `status=error, metadata.interrupted=true`(等 250ms 让在跑工具落定);回放时 pending/running→假 result 配对;正文/reasoning part 补 end 时间;下轮循环忽略 interrupted 孤儿不误触发续跑(prompt.ts:96) | Ctrl-C→`task.cancel`→super-step 未完成不落 checkpoint,回滚到上个完整状态,天然无半截 tool_call;代价是丢整轮进度 | **不补**(原子性路线已自洽) |
| **doom-loop 升级问人**(processor.ts:29,356):最近 3 个 part 全是同工具+同 JSON 入参→触发 `permission.ask(permission="doom_loop")`,阻塞等用户裁决(默认规则 ask,agent.ts:121) | `LoopGuardMiddleware`:同指纹≥3/空结果≥4/软预算→注入收敛 reminder(不问人);慢路径有 `escalate-when-stuck` skill + 冻结闸门 | **不补**:批量编译必须无人值守,阻塞式问人与之矛盾;reminder→escalate→冻结的梯子已覆盖。差异记录:opencode 把死循环当权限事件,IST 当提示工程事件 |
| **overflow 判定用真实 usage**(session/overflow.ts):上一轮上报的 input+output+cache tokens ≥ (limit.input − 预留 20k)→入队 compaction task;流中途 overflow 用 `Stream.takeUntil` 截流转 compaction(processor.ts:644) | deepagents 自动摘要中间件按 fraction 阈值(mimo 轮已对照);usage/cache tokens 已在 streaming.py 抽取 | **已对齐**(mimo 轮结论不变) |
| **content-filter 静默空转显性化**(prompt.ts:1301):finish=content-filter 时强制造错误上抛,防「本轮无输出静默 idle」 | mimo 零响应 TUI 渲染已修(1f0c27f1);transient 判定误伤裸数字已修 | **已对齐** |
| **单飞与级联取消**(run-state.ts):每会话单 Runner,`ensureRunning` 合流重复请求;cancel 沿 metadata.sessionId/parentSessionId 链**传递取消后台任务**(BFS 到不动点) | bridge 单 task 单飞;fork 子 agent 在 qa_node 同步栈内,cancel 随栈终止 | **已对齐**(结构不同效果同) |
| **每 agent 步数上限**(agent.steps→isLastStep 注入 MAX_STEPS_PROMPT 收尾) | loop_guard 软预算(budget-only 温和版,25 tool_call 提醒不硬停) | **已对齐**(IST 版本对批量编译更安全——曾有硬预算误伤 14-case 教训) |

## 三、权限系统(permission/index.ts + arity.ts + agent 默认规则)

| opencode 设计 | IST-Core 现状 | 决策 |
|---|---|---|
| **三动作规则代数**:(permission, pattern, action∈allow/ask/deny),findLast 后规则覆盖先规则,缺省 ask;deny 直接 DeniedError,ask 发事件阻塞等 UI 回复(Deferred) | 无运行时 ask 层。三套替代:①工具内确定性硬闸(ssh `_validate_command` 元字符拒绝+高危黑名单+mode 白名单前缀+拓扑 IP 校验,拒绝理由回 LLM=「deny with reason」);②fork 工具白名单(agents/*.md frontmatter,loader 消费);③文件多根沙箱(代码级)。deepagents `interrupt_on` 基础设施在(`_resolve_interrupt_on`+bridge.resume_with)但 TUI 渲染未接、默认关 | **不补通用 ask 层**:无人值守批量编译是主场景,阻塞批准与之矛盾;私有环境危险面(设备命令)已被 A 层硬闸覆盖,且「拒绝+理由回模型」等价于自动化的 deny。`interrupt_on` 保持现状(基础设施留着,需要时接渲染) |
| **reject 可带纠正反馈**(index.ts:121):用户拒绝时附言→`CorrectedError{feedback}`→作为工具错误回给 LLM,模型按人话改道 | `ask_user` 工具(threading.Event 阻塞,非 interrupt)已能让用户给自由文本改道;工具硬闸拒绝理由也回模型 | **已对齐**(通道不同能力同) |
| **always→会话内规则累积**(index.ts:145):批准 always 后同会话同 pattern 不再问,且自动放行 pending 队列中已覆盖的其他请求;拒绝则级联拒绝同会话全部 pending(防队积假批准) | ask_user 单发单收,无队列语义 | **不补**(无 ask 队列就无此问题) |
| **bash 命令按 arity 词典切权限 pattern**(arity.ts+tool/shell.ts):真 AST 解析命令→`BashArity.prefix` 切出「人类可懂前缀」(`git checkout *`/`npm run dev *`)作为 ask/always 的 pattern;引用外部目录另问 external_directory | run_shell 走文件沙箱+平台黑名单;设备命令走 ssh 白名单。无按前缀的规则记忆 | **不补**(私有环境,shell 面已被沙箱收窄)。arity 词典思路(LLM 生成+注释写明生成 prompt)可作将来细化 run_shell 闸门的参考 |
| **敏感读默认 ask**(agent.ts:130):`read: {"*.env": ask, "*.env.example": allow}`——.env 读要批准 | `environment` 文件在仓根,不在 `_agent_roots()` 多根白名单内,agent **读不到**(更硬);token 不落日志有红线 | **已对齐**(代码级更硬) |
| **deny 规则从 schema 移除工具**(request.ts resolveTools+Permission.disabled):pattern="*" 的 deny 直接不让模型看见该工具 | fork frontmatter 白名单=同效果;主 agent ToolGating 是披露控制非权限 | **已对齐** |
| **子 agent 权限派生**(agent/subagent-permissions.ts):继承父的 deny 与 external_directory 规则,todowrite/task 默认 deny(防子代理再派生) | fork 白名单静态声明,`compile_fanout` 派发受 orchestrator 控制;dyn-* agent 工具⊆注册表机械校验 | **已对齐**(静态版) |

## 四、LSP/诊断集成(lsp/ + tool/edit.ts write.ts)

| opencode 设计 | IST-Core 现状 | 决策 |
|---|---|---|
| **写后同步等诊断回流**:edit/write/apply_patch 完成后 `lsp.touchFile(file,"document")`(最长等 5s)→取该文件 error 级诊断→`<diagnostics file=…>` XML 块**追加进工具输出**给 LLM 立即修(edit.ts:197);write 额外报其他文件回归(上限 5 文件);read 只做后台预热不阻塞 | 无 LSP(不写产品代码)。**同构物已有且更领域化**:编译产出的确定性反馈闭环——emit 出口结构门(crash-gate/found_times 拒绝门)同步拒绝并回原因;`lint_xlsx_case` 反解成品卷挂凭证+合并双卡点;`dev_run_batch_digest` 把上机结果精简回流 | **不补 LSP 本体**(通用 coding 能力,与测试工程 agent 无交集)。设计同构确认:「编辑后确定性检查、error 块附加到同一工具输出、模型当轮即修」这条链 IST 在 xlsx 域已走通,无缺口 |
| 38 个 server 懒启动(root+id 复用、broken 集合防重试风暴、spawning Map 去重)、push/pull 双通道诊断去重合并、独立 `lsp` 工具给模型主动查定义/引用 | — | **不补**。broken/spawning 两个防抖集合的形状,可作将来任何「per-资源懒启动外部进程」(如 env_pool 扩展)的参考 |

## 五、plugin/hook 机制(plugin/index.ts + packages/plugin)

| opencode 设计 | IST-Core 现状 | 决策 |
|---|---|---|
| **Hooks 接口**(packages/plugin/src/index.ts:222):`chat.message`/`chat.params`(改采样参数)/`chat.headers`/`tool.execute.before|after`/`tool.definition`(改工具描述)/`shell.env`/`permission.ask`(声明未接线)/`experimental.chat.messages.transform` 等;插件=返回 Hooks 对象的异步函数,`Plugin.trigger` 按注册顺序**串行** mutate output;来源=内置+本地文件+npm 运行时安装;失败隔离不中断启动 | langchain middleware 栈(main_agent.py 按序挂 8 件)已是同型扩展点:`wrap_model_call`≈chat.params+messages.transform,`wrap_tool_call`≈tool.execute.before/after,ToolEnvelope≈tool.definition 的输出面。区别:IST 扩展点编译期固定,不做运行时装载 | **不补**:私有单仓,middleware 栈可控性>插件动态性;运行时第三方装载=新攻击面(与 mimo 轮「多源 skill 不补」同理)。hook 清单收进本表作 middleware 命名参照 |
| 内置插件全是 provider auth(xai PKCE OAuth、cloudflare 网关适配等),cloudflare 插件用 chat.params 删 reasoning 模型不兼容的 max_tokens——供应商怪癖修补以插件形态存在 | 供应商怪癖收在 `_llm.py` 子类+llm_helpers | **不补**形态;佐证 A 项方向:怪癖要么表驱动(transform.ts)要么插件化(cloudflare.ts),都不散在核心循环里 |

## 六、client/server 分离(server/ + cli/cmd/tui.ts + packages/tui)

| opencode 设计 | IST-Core 现状 | 决策 |
|---|---|---|
| **结构化 API + SSE 事件流**:Effect HTTP server,无状态多实例(每请求 `?directory=`/`x-opencode-directory` 路由到实例,懒加载复用);事件走 SSE `GET /event`(10s heartbeat+首帧 connected+断线指数退避重连),WebSocket 只留给 PTY;TUI 是纯 SDK 客户端——默认 server 跑在**同进程 Worker 线程**内存直连(不开 TCP 口),传 `--port` 才起真实 TCP;Basic auth+`?auth_token=` query 双通道(EventSource 设不了头);PTY 连接用短期 ticket | `web_server.py`:FastAPI+xterm.js,WebSocket **PTY 字节流桥**——spawn 整个 TUI 子进程,前端是哑终端,语义全在子进程;上传/下载走自定义 OSC(7001/7002)带外信号;PBKDF2+滑窗限流+RBAC。server↔TUI 无结构化事件 | **不补**(不重写):PTY 方案已满足单人内网+reviewer 只读场景;结构化改造=重写渲染层,收益(多客户端观察同会话/富 Web UI)与当前用户面不匹配。**记录路标**:若将来要多人协作或独立 Web UI,走 opencode 形态(同进程内存直连与 TCP 同源、目录路由多实例)而非扩 PTY |
| SSE 10s heartbeat 防中间设备断闲连接 | WS PTY 桥无应用层 keepalive(靠 TCP/WS ping 默认) | **微补(可选)**:`ws_terminal` 加个 20-30s 应用层 ping task,防反代/防火墙断闲——几行工程量 |

## 七、agent 定义(agent/agent.ts,只列与 MiMo 轮结论的差异)

MiMo 轮已覆盖:权限代数四层、plan 模式 deny+allow 例外(不动工具表保缓存)、Agent.generate、专用小 agent 矩阵——结论均不变。本轮 opencode 侧新看到的差异:

| opencode 设计 | IST-Core 现状 | 决策 |
|---|---|---|
| `doom_loop` 是一等权限词条(默认 ask),死循环裁决进 allow/ask/deny 同一框架 | loop_guard=reminder 路线(见二) | 不补(理由同二) |
| 默认规则含 `question: deny`(子代理禁问人)、build/plan 才 allow | fork agent 无 ask_user(frontmatter 白名单不含);orchestrator 汇总 NEEDS_USER_DECISION 一次性问 | **已对齐**(IST 的「欠定汇总一次 ask」纪律更进一步) |
| plan 模式产物固定落 `plans/*.md` 且 edit 白名单只开这条缝 | workspace/outputs 唯一可写+四闸 | **已对齐**(同思想:写面收到白名单缝) |
| agent.steps 每 agent 步数上限进定义 schema | agent 定义无步数字段,靠 loop_guard 全局软预算 | 不补(全局软预算已够;fork 单 case 场景步数天然有限) |

## 本轮落地清单(值得立即落地的 Top 3,按痛点排序)

1. **A|供应商能力表(多供应商适配摩擦,最高优先)**:`main/common/llm_helpers.py` 把 `thinking_param_for_model` 泛化为 `MODEL_CAPS` 声明字典——每族一行:thinking 参数形状(enabled/adaptive/None)、reasoning 回传字段名、思考时是否抑制 temperature/top_p、strict function-calling 可用性、`<think>` 内联剥离开关;`_llm.py` 的 `ChatOpenAIWithReasoning` 四个 patch 方法与 `_build_chat_model` 全部改读表。对标 models-dev.ts 的「能力=数据」但不引外部服务(私有环境 3-4 族够用)。验收:新接一个供应商只改表不改方法体;现有 mimo/deepseek/minimax 行为回归零变化(`tests/` 现有 LLM 适配用例全绿)。
2. **B|TUI 瞬态自动续跑(长会话稳定性)**:`tui/bridge.py::_run_in_thread` 对 `is_transient_error` 从「一行提示请重发」升级为自动退避重试(复用 `resilience.py` 既有退避件;checkpoint 幂等由 langgraph super-step 保证):重试前发 footer 事件展示「重试 n/N·下次 Xs」(对标 opencode status=retry 的用户可见性,retry.ts+status.ts),退避优先读响应 `retry-after` 头、无头走指数退避 cap 30s,context/配额类错误不重试(对标 retry.ts:70 的不可重试分类)。验收:kill 网关模拟 502/限流,TUI 当轮自动续跑不报废;`IST_TUI_AUTO_RETRY=0` 可回旧行为。
3. **C|首包超时细分(小工程量高保护)**:`_build_chat_model` 的 `request_timeout` 从单值 300s 改 `httpx.Timeout(connect=10, read=按 IST_LLM_TIMEOUT, write=…, pool=…)`——对标 provider.ts `OPENAI_HEADER_TIMEOUT_DEFAULT=10_000`:网关首包挂死时 10s 内报错进 B 项重试,而非死等 300s。验收:阻断到端点的连接,失败在 ~10s 内浮出。

可选微项(顺手不单列):ToolEnvelope 内 surrogate 清洗一行保险(对标 sanitizeSurrogates);工具注册显式字母序钉 schema 顺序(缓存稳定);`ws_terminal` 应用层 20-30s ping。
