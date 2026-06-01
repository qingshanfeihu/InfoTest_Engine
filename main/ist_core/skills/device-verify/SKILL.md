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
effort: medium
---

# Device Verify

SSH 到实际 APV/网络设备执行 CLI 命令，支持**只读验证**（show/list/display）和**配置下发**（config 模式）两种场景。

## Inputs

- 待执行/验证的命令列表
- 目标设备 IP（可从 `knowledge/data/auto_env/network_topology_rag.md` 获取）
- SSH 凭据（默认 admin/admin，未提供时 qa_ask_user 询问）

## Principles

- **高危命令一律拒绝**，不准下发，不准静默跳过（详见下方黑名单）
- 配置下发时，前一条失败不准继续执行后续命令
- SSH 凭据不准硬编码，用 qa_ask_user 或环境变量获取
- 连接超时/失败最多重试 3 次，超过标注「设备不可达」
- SSH 执行模板见 `reference/ssh_template.md`，封装实现见 `scripts/apv_ssh_client.py`

## 高危命令黑名单

以下命令**任何情况下禁止执行**：

**设备级破坏**：`system reboot`、`system shutdown`

**IP/接口修改（会导致失联）**：`ip address <接口> <IP>`、`no ip address`、`segment ip address`、`interface shutdown`、`no segment interface`、`no ip route`、`clear ip route`

**用户/权限修改**：`username <name> password`、`segment user <name> password`、`aaa`/`tacacs`/`radius` 认证配置

**全局清除**：`clear config`

**白名单（允许下发）**：SLB（slb virtual/real/group/health/translate/persist/policy）、SDNS（sdns host/listener/service/pool/on/off）、分区（segment name/user/interface/enable/disable/nat/vlan/ha）、SSL、HA（ha group/node/link）、系统（hostname/ntp/syslog/snmp/log on/off）、单个对象删除（`no slb virtual http <name>` 等）、持久化（`write memory`、`write segment file/memory`）

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

**只读验证**：根据验证目标查询 CLI 手册生成对应 show 命令。常见映射：

| 验证目标 | show 命令 |
|---------|----------|
| 虚拟服务 | `show slb virtual` |
| 后台服务组 | `show slb group` |
| 后台服务状态 | `show slb real` |
| 健康检查 | `show slb health` |
| SDNS listener | `show sdns listener` |
| SDNS host | `show sdns host` |
| 分区配置 | `show segment` |
| HA 状态 | `show ha status` |
| 运行配置 | `show running-config` |

每条命令标注预期结果。

**配置下发**：将 Step 2 标记为 safe 的命令按依赖排序，确认执行顺序。

**Success criteria**: 只读验证：每条 show 命令有对应预期结果；配置下发：safe 命令清单 + 执行顺序明确
**Artifacts**: show_commands_with_expected（只读） / deploy_command_sequence（下发）

### 4. SSH 执行

**Execution**: Direct（qa_exec + paramiko）或 [human]（qa_ask_user 手动）

用 `reference/ssh_template.md` 中的模板或 `scripts/apv_ssh_client.py` 封装类执行。

**只读验证**：在 enable 模式下依次执行 show 命令，收集所有输出。

**配置下发**：
- enable → config terminal → 逐条执行配置命令
- 每条检查输出中的错误标记（`% invalid`、`^`、`error` 等）
- 单条失败 → 立即停止，报告失败命令和错误输出，不执行后续命令
- 全部完成 → exit 退出 config 模式

**Human checkpoint**: 配置下发前，确认用户已知晓将修改设备配置（列出目标设备 + 待下发命令清单）

**Rules**: 配置下发时前一条失败不准继续
**Success criteria**: 所有命令执行完成，输出已收集（或遇到首个错误中止）
**Artifacts**: execution_results

### 5. 对比分析 (when applicable: 只读验证)

**Execution**: Direct

逐条对比设备输出与预期：值匹配？状态正常？不一致时分析原因（未下发/语法错误/旧配置冲突）。

**Success criteria**: 每条对比有明确 match/mismatch 结论 + 差异分析
**Artifacts**: comparison_results

### 6. 持久化与验证 (when applicable: 配置下发)

**Execution**: Direct

**写内存（按需）**：用户要求持久化时执行 `write memory` 或 `write segment memory`。未要求时跳过，避免覆盖设备上已有的未保存配置。

**验证下发结果**：执行对应 show 命令确认配置已生效。

**Success criteria**: 配置已生效确认 + 下发结果汇总完整
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
