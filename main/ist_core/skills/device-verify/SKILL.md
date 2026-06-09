---
name: device-verify
description: SSH 到实际 APV 设备执行 CLI 命令，支持只读验证和配置下发
context: inline
user-invocable: true
when_to_use: |
  Use when 用户要求"到设备上验证"、"上机跑一下"、"SSH执行"、"确认配置生效"、
  "下发配置"、"把命令跑一遍"，或生成了配置命令后要求实测验证。
  Trigger phrases: 上机, SSH执行, 设备验证, 下发配置, 跑命令, 确认生效, 实测
  SKIP when: 设备不可达且用户不愿手动执行。
allowed-tools:
  - qa_deepagent_read_file
  - qa_deepagent_grep(knowledge/data/markdown/product/*)
  - qa_deepagent_ls
  - qa_exec
  - qa_bash
  - qa_ssh
  - qa_restapi
effort: medium
---

# Device Verify

SSH 到实际 APV/网络设备执行 CLI 命令，支持**只读验证**（show/list/display）和**配置下发**（config 模式）两种场景。

## Inputs

- 待执行/验证的命令列表
- 目标设备 IP（可从 `knowledge/data/auto_env/network_topology_rag.md` 获取）
- SSH 凭据（默认 admin/admin，未提供时 qa_ask_user 询问）

## Principles

- **执行优先用 qa_restapi 而非 qa_ssh**：REST API 比 SSH 快得多（单次 HTTP 调用 vs shell 交互），且无需 enable/config 模式。SSH 仅作为 REST API 不可用时的降级方案
- **高危命令一律拒绝**，不准下发，不准静默跳过（详见下方黑名单）
- **CLI 手册优先于设备试错**：任何命令（含 show）必须先 grep `knowledge/data/markdown/product/cli__part*.md` 或 `cli_74__part*.md` 查语法。严禁在设备上用错误命令试探——设备不是命令发现工具，手册才是唯一权威
- **禁止假设命令名**：设备运行 InfosecOS，不是 Cisco IOS。不要用 `show ip interface brief`、`show vlan`、`show interface` 等 Cisco 风格命令名，必须从 CLI 手册中查找 InfosecOS 的正确命令
- 配置下发时，前一条失败不准继续执行后续命令
- SSH 凭据不准硬编码，用 qa_ask_user 或环境变量获取
- 连接超时/失败最多重试 3 次，超过标注「设备不可达」
- SSH 执行模板见 `main/ist_core/skills/device-verify/reference/ssh_template.md`，封装实现见 `main/ist_core/skills/device-verify/scripts/apv_ssh_client.py`

## 高危命令黑名单

以下命令**任何情况下禁止执行**：

**设备级破坏**：`system reboot`、`system shutdown`

**IP/接口修改（会导致失联）**：`ip address <接口> <IP>`、`no ip address`、`segment ip address`、`interface shutdown`、`no segment interface`、`no ip route`、`clear ip route`

**用户/权限修改**：`username <name> password`、`segment user <name> password`、`aaa`/`tacacs`/`radius` 认证配置

**全局清除**：`clear config`

**白名单（允许下发）**：SLB 全模块（slb *）、SDNS 全模块（sdns *）、分区（segment *）、SSL、HA 全模块（ha *）、系统安全子集（hostname/ntp/syslog/snmp/log/system *——危险命令如 system reboot/shutdown 由黑名单拦截）、删除/清除（no slb/clear slb/no sdns/clear sdns/no segment/clear segment/no ssl/clear ssl/no ha/clear ha 前缀均允许）、持久化（write memory/write segment）

## Steps

### 1. 确定场景与目标设备

**Execution**: Direct

判定场景（只读验证 vs 配置下发）。从 `knowledge/data/auto_env/network_topology_rag.md` 确定目标设备 IP（APV0: 172.16.34.70 / APV1: 172.16.34.71 等）。未提供凭据时 qa_ask_user。

**Success criteria**: 场景判定明确 + 目标设备 IP + 凭据就绪
**Artifacts**: scenario, target_device_ip

### 2. 高危命令预检 (when applicable: 配置下发)

**Execution**: Direct

对每条待下发命令，对照黑名单逐条检查。命中黑名单 → 拒绝并说明原因。命中白名单 → 通过。不确定 → qa_ask_user 确认。

**Rules**: 即使配置中包含高危命令也必须拒绝，不可静默跳过
**Success criteria**: 每条命令标记 safe/blocked/uncertain
**Artifacts**: command_safety_checklist

### 3. 生成执行命令清单

**Execution**: Direct

**⚠️ 强制步骤：所有命令（包括 show 和 config）必须先查 CLI 手册再执行。**

先 grep `knowledge/data/markdown/product/cli__part*.md` 或 `cli_74__part*.md` 确认命令的**完整名称和参数**。下表是已验证的正确命令——**必须使用表格中的精确命令，禁止简化**（如用 `show slb group` 代替 `show slb group method` 会遗漏关键信息）：

| 验证目标 | 正确命令（必须用完整形式） |
|---------|-------------------------|
| 虚拟服务 | `show slb virtual all` |
| 后台服务组 | `show slb group method` |
| 后台服务状态 | `show slb real all` |
| 健康检查 | `show slb health` |
| SDNS listener | `show sdns listener` |
| SDNS host | `show sdns host name` |
| 分区配置 | `show segment config` |
| HA 状态 | `show ha status` |
| 运行配置 | `show running` |

**禁止行为**：表格中 `show slb group method` 是完整的正确命令——不要写成 `show slb group`（缺 method）、`show slb virtual`（缺 all）、`show slb real`（缺 all）。如果你不确定某一行的完整命令，grep 手册确认后再执行。

**配置下发**：先查 CLI 手册确认每条命令的完整语法和参数约束（同 config-answer 的 CLI 验证流程），再将 Step 2 标记为 safe 的命令按依赖排序。

**Rules**: 禁止猜测命令，所有命令必须在 cli 手册中能找到
**Success criteria**: 每条命令可追溯到 CLI 手册中的定义
**Artifacts**: show_commands_with_expected（只读） / deploy_command_sequence（下发）

### 4. 执行命令

**Execution**: Direct（qa_restapi 优先 → qa_ssh 降级）或 [human]（qa_ask_user 手动）

**优先级**：`qa_restapi` > `qa_ssh` > 手动执行

1. **首选 `qa_restapi`**：REST API 最快（单次 HTTP round-trip），无 SSH 握手开销，支持 `\n` 交互式命令。show 和 config 命令统一 POST 即可，无需区分模式
2. **降级 `qa_ssh`**：REST API 不可用（连接失败/401/设备不支持）时使用 SSH
3. **兜底人工**：以上都不可用时 qa_ask_user 请用户手动执行，参考 `main/ist_core/skills/device-verify/reference/ssh_template.md`

**Human checkpoint**: 配置下发前，确认用户已知晓将修改设备配置（列出目标设备 + 待下发命令清单）

**Rules**: 配置下发时前一条失败不准继续；先 REST API 再 SSH 的顺序不可颠倒
**Success criteria**: 所有命令执行完成，输出已收集（或遇到首个错误中止）
**Artifacts**: execution_results

### 5. 对比分析 (when applicable: 只读验证)

**Execution**: Direct

逐条对比设备输出与预期：值匹配？状态正常？不一致时分析原因（未下发/语法错误/旧配置冲突）。

**Success criteria**: 每条对比有明确 match/mismatch 结论 + 差异分析
**Artifacts**: comparison_results

### 6. 持久化与验证 (when applicable: 配置下发)

**Execution**: Direct

**默认不保存**：配置下发后**不**执行 `write memory`。除非用户明确要求"保存配置"或"持久化"，否则跳过。避免覆盖设备上已有的未保存配置。

**验证下发结果**：执行对应 show 命令确认配置已生效。验证通过即完成任务，不需额外保存步骤。

**Success criteria**: 配置已生效确认 + 下发结果汇总完整（无需保存）
**Artifacts**: deploy_summary

### 7. 输出报告

**Execution**: Direct

按以下结构输出（输出时禁止再调任何工具）：

```
### 设备信息
- 目标设备：<设备名> (<IP>)
- 操作类型：只读验证 / 配置下发
- SSH 用户：<用户名>

### 命令执行结果

| # | 命令 | 执行状态 | 输出摘要 |
|---|------|---------|---------|
| 1 | `show slb virtual` | success | ✓ 包含 "v1" 172.16.34.100:80 |
| 2 | ... | error | ... |

### 详细分析
<对 error/mismatch 项的详细说明，附实际输出关键片段>

### 结论
- 成功：N 条 / 失败：N 条
- 建议：<修正建议或下一步>
```

**Rules**: 最终输出时禁止再调工具
**Success criteria**: 报告含完整四段结构（设备信息 + 执行结果表 + 详细分析 + 结论），所有异常项有根因分析
