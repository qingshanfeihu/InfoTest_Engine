# 安全评审报告 — #58 Fix C `_compact_args` 全参日志(凭据泄漏面)

**评审子 agent**:InfoTest Engine 安全评审(只读)
**日期**:2026-07-19
**范围**:仅 `main/ist_core/skills/loader.py` 的 `_compact_args`(#58 Fix C)——判定其把 tool_call 全参写入 `.events.jsonl` 能否泄漏凭据/Token/密码。**不做全批评审。**

---

## 结论

- **总体:需修改(条件性 FAIL)** — 潜在凭据泄漏面。默认路径不触发,但日志器**零脱敏**,硬红线「禁止在日志中打印 Token/密码」不由代码结构保证,仅靠「没人把凭据当 arg 传」的约定。修复一行、无损,建议合入前补脱敏。

---

## 发现(按严重度)

### [中 / 条件性] `loader.py:825-837`(`_compact_args`)+ `:1017`(注入点) — 全参 verbatim 序列化、零脱敏

**代码事实**
- `_compact_args`(825-837):`json.dumps(args, ensure_ascii=False, default=str, sort_keys=True)`,仅 300 字符截断,**不对任何 key 脱敏**。
- 注入点 `:1017`,在 `_emit_fork_step_events`(999);唯一调用链 `_invoke_fork_streamed`(1055)→ `:1095`。**作用域仅 fork**,不含主 agent。
- `fork_id` 恒设(`_fork_id = uuid...`,1157;传入 1200);`IST_FORK_STEP_EMIT` 默认 "1"=开(600)。⇒ 默认每个 fork 工具调用都记全参。
- 沉降点:`.events.jsonl`,落 `runtime/logs/`。`runtime` 在 `_PLATFORM_DENIED_TOP_LEVEL`(file_tools.py:83)——agent 读不回(无自 exfil 环),但仍是盘上明文日志,写入即违红线。

**泄漏链(dyn-agent 可达)**
- `dev_ssh`(ssh.py:173)/`dev_rest`(restapi.py:46)接受 `password` / `enable_password` / `username` 作**入参**。
- 凭据解析 **arg 优先**:ssh.py:33-35 `resolved_pass = password or os.environ.get("APV_PASSWORD","admin")`(enable/username 同型)。
- 二者:
  - 在 dyn-agent 注册表 `_TOOL_REGISTRY`(loader.py:222-223);
  - **不在** `_ON_DEVICE_BLOCKED`(agent_define.py:32-34,仅拦 `dev_run_batch/dev_run_batch_digest/dev_run_case/dev_init_device`)。
- ⇒ `agent_define` 可给 dyn-* 子 agent 授予 `dev_ssh`/`dev_rest`;dyn fork 走 `_invoke_fork_streamed` 日志路径。若该 fork 显式传 `password=`/`enable_password=`,该**值被逐字写入 `.events.jsonl`**(sort_keys 下 `enable_password`/`password` 排在 `command`/`host` 之间,典型短命令下落在 300 字符窗口内,不被截断保护)。

**为何不是纯 PASS**
- Design 评估「device creds 走 env(APV_PASSWORD 等)不走 tool args」对**默认路径正确**:args 默认 `""` → 只记 `{host, command}`,无秘密。
- 但 `_compact_args` **不做任何脱敏**,红线是否守住完全依赖运行期「没人把凭据当 arg 传」。而 dev_ssh/dev_rest 明确接受 password 参、arg 优先、dyn 可达——该不变量**无结构性保证**。硬红线不应依赖行为约定。

**建议(无损脱敏——凭据名 key 零诊断价值,`version`/`command`/`pattern` 等诊断参不受影响)**

在 `_compact_args` 序列化前按 key 脱敏:

```python
import re
_REDACT_ARG_KEY = re.compile(r"(?i)(password|passwd|secret|token|credential|api[_-]?key|access[_-]?key)")

def _compact_args(args: Any, limit: int = 300) -> str:
    if not isinstance(args, dict) or not args:
        return ""
    import json as _json
    safe = {k: ("***" if _REDACT_ARG_KEY.search(str(k)) else v) for k, v in args.items()}
    try:
        s = _json.dumps(safe, ensure_ascii=False, default=str, sort_keys=True)
    except Exception:  # noqa: BLE001
        s = str(safe)
    return s if len(s) <= limit else s[:limit] + "…"
```

- 用 `password` 覆盖 `enable_password`(子串命中)。
- **避免裸 `key`/`pass`**:否则误伤 `keyword`(build_command)、路径类参。
- 保留了 Fix C 的诊断意图(如 kb_footprint 的 `version` kwarg 照记)。

---

## 已确认安全的改动

- **默认 fork 白名单全部无凭据参**(逐个核 frontmatter `tools:`):
  - `compile-worker`:`fs_read/fs_grep/fs_glob/run_python/kb_footprint/compile_*/dev_probe/dev_help`——`dev_probe`/`dev_help` 单 `command` 串(read-only show/get),`run_python(code)`,无凭据参。
  - `compile-attributor`:`fs_*/kb_*/compile_*/submit_*`——无凭据参。
  - `review-verifier` / `config-answer-verifier`:仅 `fs_*`。
  - `config-answer-draft`:`fs_*/kb_footprint/build_command(keyword, values_json)`——无凭据参。
  - 默认编译/评审链经 `_compact_args` 记录的仅 `{command,host,pattern,query,path,autoid,version,...}`,不含秘密。
- `run_python(code)`:理论上可内联秘密,但 fork 沙箱够不到 `environment`/`runtime/`/`memory/`(黑名单),取不到秘密,非现实面。
- 阻塞回退路径(loader.py:1082 `runnable.invoke`)不 emit 步骤事件;主 agent 的 dev_ssh 调用不经本函数。
- 本改动为纯可观测性字段,**未触及**沙箱多根/读写四闸/记忆写白名单/平台黑名单,无沙箱削弱。

---

## 我实际核对过的闸门/事实

1. `_compact_args` 实现(825-837)+ 唯一注入点(1017)+ 唯一调用链 `_invoke_fork_streamed`→`_emit_fork_step_events`(1094-1095)。
2. 六个 fork agent 的 `tools:` frontmatter 白名单。
3. `dev_ssh`/`dev_rest`/`dev_probe`/`dev_help` 签名 + dev_ssh 凭据解析(ssh.py:33-35 arg 优先)。
4. dyn-agent 注册表(loader.py:222-223 含 dev_ssh/dev_rest)+ `_ON_DEVICE_BLOCKED`(agent_define.py:32-34,未拦 dev_ssh/dev_rest)。
5. `fork_id` 恒设(1157)、`IST_FORK_STEP_EMIT` 默认开(600)、沉降点 `.events.jsonl` 落 `runtime/`(黑名单 file_tools.py:83)。

**证据边界声明**:基于上述行级代码确认「默认路径不泄漏;dev_ssh/dev_rest 的 password 参构成 dyn 可达的潜在泄漏面」。未实跑构造带 dev_ssh 的 dyn agent 触发实证(纯只读审查),故定性为**潜在/条件性**,非已观测活跃泄漏。修复一行、无损,建议合入前补脱敏,让硬红线由代码而非约定守住。
