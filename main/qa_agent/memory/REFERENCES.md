# 记忆子系统参考实现速查

读完 deepagents 0.5.9 与 langchain agents middleware 源码后整理。**实施前必看，遇到问题先回查这里再继续**。

## 1. deepagents.create_deep_agent 关键参数（graph.py:206-225）

```python
create_deep_agent(
    model,
    tools,
    *,
    system_prompt: str | SystemMessage | None,
    middleware: Sequence[AgentMiddleware],          # 用户中间件，插在 base 后 tail 前
    subagents: Sequence[SubAgent | CompiledSubAgent | AsyncSubAgent],
    skills: list[str] | None,                        # 触发 SkillsMiddleware
    memory: list[str] | None,                        # 触发 MemoryMiddleware（关键！）
    permissions,
    backend: BackendProtocol | BackendFactory | None,
    interrupt_on,
    response_format,
    context_schema,
    checkpointer,
    store: BaseStore | None,                         # 给 StoreBackend 用
    debug, name, cache,
)
```

**最大发现**：deepagents 已经内置 `MemoryMiddleware`，传 `memory=["/memories/AGENTS.md"]` 就会自动加载 + 注入 + 给出 edit_file 写记忆的 prompt。我们的 L3 不需要自己写注入逻辑，**复用即可**。

## 2. 中间件注册顺位（graph.py:656-714）

```
1. TodoListMiddleware
2. SkillsMiddleware            (if skills=...)
3. FilesystemMiddleware         (always, 暴露 read_file/write_file/edit_file/ls/glob/grep)
4. SubAgentMiddleware           (if subagents)
5. AsyncSubAgentMiddleware
6. SummarizationMiddleware
7. PatchToolCallsMiddleware
=== 用户 middleware 插入这里 ===
8. profile.extra_middleware
9. _ToolExclusionMiddleware     (if profile.excluded_tools)
10. AnthropicPromptCachingMiddleware
11. MemoryMiddleware            (if memory=...)
12. HumanInTheLoopMiddleware    (if interrupt_on)
```

**结论**：用户 middleware（包括 PerTurnSkillReminder、我们要加的 MemoryWriteMiddleware）插在第 7 与第 8 之间。MemoryMiddleware 在我们之后跑，意味着我们在 wrap_model_call 改 messages 时它的 system 注入还没发生（MemoryMiddleware 改的是 system_message，不是 messages，互不冲突）。

## 3. AgentMiddleware 钩子签名（langchain/agents/middleware/types.py）

```python
class AgentMiddleware(Generic[StateT, ContextT, ResponseT]):
    state_schema: type[AgentState]                  # 可选，扩展 state

    def before_agent(self, state, runtime) -> dict[str, Any] | None: ...
    async def abefore_agent(self, state, runtime) -> ...
    def before_model(self, state, runtime) -> dict[str, Any] | None: ...    # 返回 state update
    async def abefore_model(...): ...
    def after_model(self, state, runtime) -> dict[str, Any] | None: ...    # 关键：写 working
    async def aafter_model(...): ...
    def wrap_model_call(self, request, handler) -> ModelResponse: ...      # 关键：注入 reminder
    async def awrap_model_call(...): ...
    def after_agent(self, state, runtime) -> dict[str, Any] | None: ...
    async def aafter_agent(...): ...
    def wrap_tool_call(self, request, handler) -> ToolResponse: ...
    async def awrap_tool_call(...): ...
```

**ModelRequest** (types.py:88-269):
- `messages: list[BaseMessage]`
- `system_message: SystemMessage | None`
- `model: BaseChatModel`
- `tools: list[BaseTool]`
- `state, runtime`
- `.override(**overrides)` 返回新 ModelRequest（不可变模式）

**关键约束**（已验证）：在 `wrap_model_call` 里改 messages 不会持久化到 state；在 `before_model` 里返回 `{"messages": [...]}` 会通过 `add_messages` reducer 持久化。两个机制和我们 PerTurnSkillReminder 的设计完全一致。

## 4. CompositeBackend.__init__ 真实签名（backends/composite.py:140-165）

```python
CompositeBackend(
    default: BackendProtocol | StateBackend,
    routes: dict[str, BackendProtocol],
    *,
    artifacts_root: str = "/",
)
```

路径匹配：sorted_routes 按前缀长度倒排匹配；exact match `/memories` 也会路由到 `/memories/`（自动补斜杠）。
路径规范化：所有路径必须以 `/` 开头，路由后剥前缀，例如 `/memories/note.md` → `/note.md` 传给 StoreBackend。

## 5. StoreBackend.__init__（backends/store.py:181-230）

```python
StoreBackend(
    runtime=None,                     # deprecated，别传
    *,
    store: BaseStore | None = None,   # None 时运行期 get_store()
    namespace: NamespaceFactory | None = None,
    file_format: FileFormat = "v2",
)

NamespaceFactory = Callable[[Runtime[Any]], tuple[str, ...]]
```

namespace 校验（store.py:131-169）：每段必须 `[A-Za-z0-9\-_.@+:~]+`，不允许通配符；空 tuple 报错。我们的 `_user_namespace` 必须保证 fallback 也命中这个白名单。

```python
namespace=lambda rt: (rt.server_info.user.identity, "memories")  # 推荐
# 但 rt.server_info 在 langgraph dev 之外可能 raise，必须 try/except
```

## 6. StateBackend（backends/state.py）

```python
StateBackend(runtime=None, *, file_format="v2")
```

- 通过 `get_config()` 读 LangGraph 当前 thread 的 `files` channel
- 必须在 graph 执行上下文内调（外面调会 RuntimeError）
- 文件随 checkpointer 落盘，无需自己管

## 7. BackendProtocol 主要方法（backends/protocol.py:319-748）

```python
backend.ls(path) -> LsResult                              # entries
backend.read(file_path, offset=0, limit=2000) -> ReadResult  # file_data
backend.grep(pattern, path=None, glob=None) -> GrepResult
backend.glob(pattern, path="/") -> GlobResult              # matches: list[FileInfo]
backend.write(file_path, content) -> WriteResult           # 已存在则 error
backend.edit(file_path, old_string, new_string, replace_all=False) -> EditResult
# 全部都有 a* 异步版本
backend.upload_files(list[(path, bytes)]) -> list[FileUploadResponse]
backend.download_files(list[path]) -> list[FileDownloadResponse]   # MemoryMiddleware 用这个
```

## 8. deepagents.MemoryMiddleware 已有功能（middleware/memory.py）

```python
MemoryMiddleware(
    *,
    backend,                          # 必传
    sources: list[str],               # 文件路径列表
    add_cache_control: bool = False,  # ChatAnthropic 才生效
)
```

行为：
- `before_agent` 一次性 `download_files(sources)` 拼成 `state.memory_contents`
- `wrap_model_call` 把 `<agent_memory>...</agent_memory>` 拼到 system_message 末尾
- 内置 prompt（MEMORY_SYSTEM_PROMPT）告诉 LLM "用 edit_file 写记忆 / 何时该写"

**对我们的影响**：
- L3 AGENTS.md 注入 → 直接用 `memory=["/memories/AGENTS.md"]` 即可，不必自己造
- 但 MEMORY_SYSTEM_PROMPT 鼓励 LLM 自己 `edit_file` 写记忆——和我们"agent 不显式写"路线冲突
- 解决：保留 MemoryMiddleware 做注入，但让 fork agent 而不是主 agent 去 edit_file；主 agent 继续被 `_ToolExclusionMiddleware` 屏蔽 edit_file
- prompt 提示主 agent "可以 edit_file" 是 noise，但被 ToolExclusion 屏蔽后 LLM 调不了，只是浪费几百 token；可接受。如必要后续可子类化覆盖 MEMORY_SYSTEM_PROMPT。

## 9. _ToolExclusionMiddleware 工作方式

`main_agent.py:100-112` 已经在用：

```python
_ToolExclusionMiddleware(
    excluded={"write_file","edit_file","execute","read_file","ls","glob","grep"}
)
```

它在 wrap_model_call 时把 ModelRequest.tools 过滤掉这些名字。fork extractor agent 必须**不挂这个**，否则没法写记忆。

## 10. 现有 PerTurnSkillReminder 的可复用代码

`main/qa_agent/middleware/per_turn_skill_reminder.py`：
- `_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)` 简易 yaml-free frontmatter
- `_parse_skill_frontmatter(path)` 解析 name + description
- `_has_recent_reminder(messages)` 最近 4 条去重逻辑（要改 tag 名 `<memory-context>`）
- 注入位置：在最后一条 HumanMessage 之前插入新 HumanMessage —— 我们 L1/L2 工作记忆就用这套

## 11. 实施决策（基于以上事实）

| 议题 | 参考实现 | 我们怎么做 | 偏离原因 |
|---|---|---|---|
| L3 注入 | deepagents MemoryMiddleware（download_files → system 注入） | **复用**：传 `memory=["/memories/AGENTS.md"]` | —— |
| L3 写入 | MemoryMiddleware 鼓励 LLM edit_file | 改成 fork agent 写，主 agent 不暴露 edit_file | 用户决策"agent 不显式写" |
| L1/L2 注入 | 无内置 | 新增 MemoryInjectionMiddleware（仿 PerTurnSkillReminder） | 需要"每轮、user 角色、最后 human msg 之前" 而 MemoryMiddleware 是"system 末尾、首轮加载" |
| L1 写入 | 无内置 | MemoryWriteMiddleware.after_model 规则抽取，调 backend.edit | —— |
| 长期 distill | cc-haha 用 fork agent + AutoDream | 我们走 fork agent (B) + cron dream (C) 双轨 | 用户已选 |
| backend | CompositeBackend / StateBackend / StoreBackend | 全部用 deepagents 原生类 | —— |
| 路径 | `/memories/`（约定）`/working/`（自定） | 一致 | —— |
| namespace | `lambda rt: (rt.server_info.user.identity, "memories")` | 同款 + try/except 降级 default | rt.server_info 在 langgraph dev 之外可能不存在 |

## 12. 需要在 main_agent.py 改的两点

1. **删除原 FilesystemBackend** 替换为 `build_memory_backend()`：

```python
# 旧（约 main_agent.py:90-98）
backend = FilesystemBackend(root_dir=str(project_root), virtual_mode=True, ...)

# 新
from main.qa_agent.memory import build_memory_backend, get_memory_sources
backend = build_memory_backend()
backend_kwarg["backend"] = backend
```

2. **追加 memory 参数 + 我们的两个 middleware**：

```python
return create_deep_agent(
    ...,
    memory=get_memory_sources(),  # ["/memories/AGENTS.md"]
    middleware=[..., MemoryInjectionMiddleware(...), MemoryWriteMiddleware(...)],
    backend=backend,
    store=_get_default_store(),  # langgraph BaseStore，给 StoreBackend
)
```

`store=` 参数是关键：`StoreBackend(store=...)` 显式传不依赖 graph 上下文，但 fork agent 也要拿到同一个 store。所以在 backend.py 单例化 store。
