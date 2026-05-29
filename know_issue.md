# Known Issues

记录开启 `extra_body={"enable_thinking": True}` 后已知 / 待观察的问题。新问题请追加到末尾，标注首次出现日期与触发场景。

## 2026-05-20 / Qwen3.6 + enable_thinking 模式

### 1. `tool_choice="required"` 与 thinking 模式不兼容

- **现象**：阿里云百炼官方文档明说"思考模式的模型不支持强制调用某个工具"。如果 deepagents / langchain 在某个 sub-agent 链路里通过 `tool_choice` 强制选工具，请求会被 DashScope 拒。
- **当前是否触发**：未在 main_agent 主路径观测到。Reviewer hierarchical pipeline 的 4 个 sub_agent 走 `create_deep_agent` 默认 `tool_choice="auto"`，理论上不受影响。
- **应对**：首次跑长流程时盯一下日志；若出现 `tool_choice not supported in thinking mode` 类错误，定位到具体调用方后改回 `auto`，或在该链路单独 `extra_body={"enable_thinking": False}` 关闭。
- **回滚**：`main/ist_core/agents/_llm.py` 把 `extra_body.setdefault("enable_thinking", True)` 改成 `False`。

### 2. Token 消耗显著上升

- **现象**：`reasoning_content` 不参与 prompt cache 但计入 output tokens。工具调用密集的多轮回合（reviewer 跑 4 sub_agent × 12+ 工具）单次 run 的累计 token 可能从 ~700k 涨到 ~1M+。
- **TUI 表现**：footer `tokens` 数字上升更快；之前 footer 把 `/ 128,000 tokens` 误展示成上下文窗口比例（已修复，commit 1054980），现在只显示累计值。
- **应对**：长流程结束后 `/compact` 重置 transcript + token 计数；或评审任务跑完一回合就开新 thread。
- **不应对的代价**：放任不管，单 thread 里 sub_agent 会被 deepagents 的 `summarization_middleware(max_tokens=28000)` 截断历史，模型记不住前面读过的文件。

### 3. 思考内容很长 → viewport 滚动压力

- **现象**：单条 `ThinkingMessage` 可能是几百字的中文段落。transcript 现在按真实视觉行（`\n` 拆 + 终端宽软换行）算 sticky scroll（commit 等待中），AI 流式独白也修复了被工具行覆盖的 bug。但若一次性思考超过 viewport 高度，仍只能看到末尾。
- **TUI 表现**：思考行被滚出屏幕外；按 ↑/↓（如果 transcript 实现了上下翻）或 ctrl+l 重渲染。
- **应对**：暂未实现可折叠的 `✶ Thinking (ctrl+o to expand)`，目前思考整段以 dim 灰 `✶` 前缀直接打。后续考虑把 ThinkingMessage 也接入 `_tool_output_blocks` 的折叠逻辑。

### 4. `reasoning_content` 字段名不稳定

- **现象**：抽 thinking 走 `additional_kwargs.get("reasoning_content") or additional_kwargs.get("reasoning")`。LangChain 不同小版本字段名有过摇摆（`reasoning` vs `reasoning_content` vs nested under `extra_data`）。
- **应对**：兜底已加两个 key；若升级 langchain-openai 后又看不到思考行，先打 `additional_kwargs.keys()` 排查。

## 2026-05-29 / 发布前全面体检（v1.0.4）

9 维度体检（文档 / 架构 / TUI / Web / IO / 沙箱 / 账号 / 密钥 / 代码质量）+ 高危项对抗复核。下面分「已修复」与「仍待办」两块。

### A. 已修复（本次随 v1.0.4 落地）

**Web Terminal 安全加固**（`main/ist_core/web_server.py` + `web/index.html`，仅 `infotest --server` 路径）：
- 密码改 PBKDF2-SHA256 哈希（`password_hash`），登录 `hmac.compare_digest` 恒定时间比较；明文 `password` 仅兼容并打 warning。生成哈希：`python -c "from main.ist_core.web_server import hash_password; print(hash_password('pw'))"`
- 会话 token 改 `secrets.token_urlsafe` + 8h 过期（`IST_WEB_SESSION_TTL_SEC`）+ `/api/logout` 撤销
- 登录失败按 IP 滑动窗口限流（`IST_WEB_LOGIN_MAX_FAILURES`/`_WINDOW_SEC`，默认 5/300s）
- 上传 RBAC（`IST_WEB_WRITE_ROLES`，默认仅 admin）+ 路径遍历修复（basename + 解析后二次校验）+ 体积上限（`IST_WEB_MAX_UPLOAD_MB`，默认 50）
- WS 断开显式 `terminate()/kill()` 子进程 + `await gather` 收尾，杜绝僵尸进程 / fd 泄漏
- 前端下载列表改 DOM `textContent` 构建（消除文件名 XSS）+ 加 `ws.onerror`
- `ssh_users.example.json` 去明文凭据，改 `password_hash` 占位符

**沙箱 / 资源 / 并发**：
- `file_tools.py` 平台黑名单（`_PLATFORM_DENIED_*`）改大小写不敏感比较，修复 macOS/Windows 大小写变体绕过（`MAIN/`、`Memory/`、`Runtime/` 等曾可绕过黑名单访问受保护目录）
- `cli.py:_start()` Web server 子进程 stdout 文件句柄改 try/finally 关闭（detach 后子进程已继承 fd），修复每次启动泄漏一个 fd
- `ist_app.py:run()` finally 块显式 `close()` `JsonlFileSink`，修复 TUI 退出 / 异常时 fd 泄漏
- `events.py` 默认 EventBus 单例 `get_default_bus`/`reset_default_bus` 加双检锁，修复 bridge 后台线程与 graph 执行线程并发下实例覆盖 / 订阅丢失

**文档**：
- `ARCHITECTURE.md` §8 全量管线命令标 legacy（`index_all`/`migrate_to_qdrant`/`mineru_*`/`function_trunk_create`/`fix_http2_deferred` 等模块已归档至 `backup/main_legacy/`，**不可** `python -m` 调用；当前仅 `mineru_batch_export`/`xlsx_to_markdown` 有效）
- 移除 §12.4.2 已删除的 `PreAnalysisInjectionMiddleware` 描述（该文件不存在于代码树），指向 §13 v2.0 Verification
- 版本号 1.0.4 对齐 `pyproject.toml` / CLI / TUI / CHANGELOG

### B. 仍待办（已确认但本次未改，按优先级）

> 体检对每条高危项做了对抗复核，下列为复核后**确认成立**但本次未动的项；误报已剔除，不在此列。

**安全 / 沙箱**：
- **符号链接 TOCTOU（sandbox-2，high）**：`file_tools._resolve_inside_root` 用 `Path.resolve()` 跟随符号链接，校验在 resolve 后；校验与实际 open 之间符号链接可被换指向。需 `O_NOFOLLOW` 或 open 后 `os.fstat` 校验 inode。改动面较大，单独排期。
- **`..` 字面检查在 resolve 前（sandbox-4，medium）**：与 sandbox-2 同源，建议合并修。
- **`store.read_long_term_by_path()` 读路径无 `..` 校验（sandbox-3，medium）**：写路径已防护，读路径漏；影响取决于 key_resolvers 回调可信度。

**IO / 资源**：
- **⚠️ KMS 缓存并发写竞态（io-1，high — 复核 agent 出错未完成，需人工确认）**：`kms_classifier.classify_file` 读-改-写 `.classifier_cache.json` 无锁，`/kms product update` 与 `/kms qa update` 并行会丢数据。建议原子写（tmpfile+rename）或文件锁。**发布前请人工核一遍这条。**
- **大 xlsx OOM（io-3，high）**：`file_tools._read_spreadsheet` 用 `openpyxl.load_workbook` 全量加载，GB 级表会 OOM；加文件大小预检 / `iter_rows` 行数上限。（kms_classifier 侧已有 `i>=2 break`，无此问题）
- **PDF 切分临时文件泄漏（io-2，medium）**：`mineru_batch_export._pdf_splits` 无清理 / 回滚，长期堆积。
- **子进程超时丢 stderr（io-4，medium）**：`exec_tools` `qa_exec`/`qa_bash` 的 `TimeoutExpired.stderr` 未回传，无法区分超时/hang/崩溃。

**TUI / 渲染**：
- **零宽字符宽度（tui-4，high）**：`ink/string_width.py` 把 ZWJ / 组合字符 / 控制字符按宽度 1 计，含 emoji 序列 / RTL 的 AI 输出会算错行高 → 滚动错位 / 截断。需对 Unicode 类别 Mn/Mc/Me + 控制字符返回 0。
- **tool_use FIFO fallback 错配（tui-1，medium）**：无 `lc_tool_run_id` 且多源异步时 `pop(0)` 可能错配；新 LangGraph 路径已有映射防护，旧路径单源有序，触发概率低。

**代码质量**：
- **异常吞掉无日志（exception-swallow-1/2，medium）**：`graph._emit_to_bus` 与 `events.EventBus.emit` 的 `except Exception: pass` 无日志，sink 失败静默；建议至少 `logger.debug`。
- **dream PID 锁 fd 泄漏（resource-leak-1，medium）**：`memory/dream.py:_acquire_pid_lock` 异常分支 fd 未关；单次调用影响有限。

**依赖 / 配置**：
- **`dashscope` 无版本上界（pkg-1，low）**：项目实际通过 langchain-openai 兼容端点用 DashScope，未直接 import SDK，风险低；下个维护周期补 `<2`。

### 误报记录（复核已证伪，勿重开）
`pricing.py`/`web_server.py` 非孤儿（footer 相对导入 / cli subprocess 调用）；`ssh_users.json` 未被 git 跟踪（`.gitignore` 生效）；streaming_text 竞态被 reducer `dispatch` 锁保护；WS `term.write` ANSI 非 XSS；CORS 同源架构非缺陷；AsyncSqliteSaver loop 检测正常；`devnull` 关闭顺序正确；571MB `ist_core.sqlite` 在包目录外，setuptools 不会打进 wheel（但建议 `infotest reset` 清理工作树）。
