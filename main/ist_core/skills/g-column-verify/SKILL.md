---
name: g-column-verify
description: [已废弃-优先使用烟雾测试] 设备直连执行 show 命令验证 check_point
context: fork
agent: g-column-verifier
user-invocable: false
when_to_use: |
  Use when automated-g-column-filling 需要直接在 APV 设备上逐条执行 show 命令验证 check_point（不经过烟雾测试框架）。
  SKIP when: 优先走 smoke_test_run 烟雾测试验证（automated-g-column-filling Step 6），此技能仅在设备直连验证场景使用。
allowed-tools:
  - qa_deepagent_read_file
  - qa_deepagent_grep
  - qa_deepagent_ls
  - qa_restapi
  - qa_ssh
  - qa_exec
  - qa_bash
effort: high
---
# G-Column Verify

接收已填充 G 列的测试用例，按行号顺序重放全部操作（APV 配置/show、Linux 命令），验证 check_point 与实际输出一致。不一致则用设备实际输出修正。

**核心原则：严格按行号顺序执行每一行，check_point 的唯一权威来源是设备上的实际输出。**

## Brief

$ARGUMENTS

## Principles

- **设备输出是 check_point 的唯一标准**：不从 CLI 手册或常识推测 check_point，必须在设备上跑出实际输出后从中提取
- **REST API 优先于 SSH**：APV 设备优先用 `qa_restapi`，不可用时降级 `qa_ssh`；Linux 设备用 `qa_ssh`
- **只改错的不改对的**：设备输出与原 check_point 匹配 → 保留；不匹配 → 修正；无法判断 → 标记
- **test_env 必须实际执行**：Linux 命令（dig/curl/ping）在 Linux 设备上实际跑，输出用于后续 check_point 验证

## Steps

### 1. 按行号顺序重放全部操作

**每一行都必须处理，不能跳过。** 顺序是构建设备状态的关键。

按行号升序遍历 rows_map，根据 E 列类型分别执行：

| E 列 | 操作 | 设备 | 说明 |
|------|------|------|------|
| `APV*`，G 为配置命令 | 下发配置 | APV | `qa_restapi` 下发，累积设备状态，多条可 `\n` 批量 |
| `APV*`，G 为 show 命令 | 执行并记录 | APV | `qa_restapi` 执行，记录输出 |
| `test_env` | 实际执行并记录 | Linux | `qa_ssh(host=<linux_device>)` 执行 G 列 Linux 命令，记录输出 |
| `check_point` | 验证 | — | 对照前一行输出验证（见 Step 2） |
| `time` | 跳过 | — | 不实际等待 |

**⚠️ APV 配置下发前必须列出命令清单并确认用户知晓。配置下发不可逆。**

### 2. 验证并修正 check_point

对每条 check_point 行：

1. 确定前一行是 APV show 还是 test_env，找到其设备输出
2. 用原 check_point 值在实际输出中匹配
3. 匹配成功 → 保留原值
4. 匹配失败 → 分析 D 列描述，从设备输出中提取正确的匹配内容
5. 无法确定 → 标记 issue，保留原值

修正时注意：
- 前一行是 APV show → check_point 格式必须是 CLI 完整输出行，不能是裸 IP 或正则片段
- 前一行是 test_env → check_point 格式按优先级表决定（`访问成功`→后端IP/响应内容，其他→工具输出格式如 `SERVER:`、`HTTP/1.1`）
- `found times` → 只修正数字

### 3. 输出修正结果

以 JSON block 输出（machine-readable）：

```json
{
  "corrections": {
    "<行号>": "<修正后 G 列>"
  },
  "unchanged": ["<行号>"],
  "show_outputs": {
    "<show行号>": "<APV 设备输出关键片段>"
  },
  "test_env_outputs": {
    "<test_env行号>": "<Linux 命令输出关键片段>"
  },
  "issues": [
    {"row": "<行号>", "reason": "<原因>"}
  ]
}
```

之后附中文摘要：执行命令数（APV 配置/show/test_env）、修正 check_point 数、未匹配项。
