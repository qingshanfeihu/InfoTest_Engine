---
name: device-verify
description: SSH into a real APV device to execute CLI commands; supports read-only verification and configuration deployment.
context: inline
user-invocable: true
when_to_use: |
  Use when the user asks to verify on the device, run it on the device, execute over SSH,
  confirm a configuration took effect, deploy configuration, or run the commands for real —
  or when generated configuration commands need live verification.
  Trigger keywords: 上机, SSH执行, 设备验证, 下发配置, 跑命令, 确认生效, 实测
  SKIP when: the device is unreachable and the user is unwilling to execute manually.
allowed-tools:
  - fs_read
  - fs_grep(knowledge/data/markdown/product/*)
  - fs_ls
  - run_python
  - run_shell
  - dev_ssh
  - dev_rest
  - kb_footprint
effort: medium
---

# Device Verify

SSH into a real APV / network device to execute CLI commands. Two scenarios: **read-only verification** (show/list/display) and **configuration deployment** (config mode).

## Inputs

- The list of commands to execute / verify
- Target device IP (available from `knowledge/data/auto_env/network_topology_rag.md`)
- SSH credentials (default admin/admin; ask_user when not provided)

## Principles

- **Prefer dev_rest over dev_ssh for execution**: the REST API is much faster than SSH (a single HTTP call vs. an interactive shell) and needs no enable/config mode. SSH is only the fallback when the REST API is unavailable
- **High-risk commands are always refused** — never deploy them, never silently skip them (see the blacklist below)
- **The CLI manual outranks trial-and-error on the device**: every command (including show) must first be grepped in `knowledge/data/markdown/product/cli_*_Chapter*.md` + `cli_*_Appendix*.md` for its syntax. Never probe the device with wrong commands — the device is not a command-discovery tool; the manual is the only authority
- **Never assume command names**: the device runs InfosecOS, not Cisco IOS. Do not use Cisco-style command names such as `show ip interface brief`, `show vlan`, `show interface`; look up the correct InfosecOS command in the CLI manual
- During configuration deployment, if a command fails, do not continue with the remaining commands
- Never hard-code SSH credentials; obtain them via ask_user or environment variables
- On connection timeout/failure retry at most 3 times; beyond that, annotate 「设备不可达」 (device unreachable)
- References (read directly, no indirection):
  - SSH execution template: `main/ist_core/skills/device-verify/reference/ssh_template.md`
  - Reference implementation: `main/ist_core/skills/device-verify/scripts/apv_ssh_client.py` — wraps `connect()` / `execute_show_commands()` / `execute_config_commands()`; env vars: `APV_DEVICE_IP`, `APV_USERNAME`, `APV_PASSWORD`, `APV_SSH_PORT` (defaults documented in the script)

## High-risk command blacklist

The following commands must never be executed, under any circumstances:

**设备级破坏**：`system reboot`、`system shutdown`

**IP/接口修改（会导致失联）**：`ip address <接口> <IP>`、`no ip address`、`segment ip address`、`interface shutdown`、`no segment interface`、`no ip route`、`clear ip route`

**用户/权限修改**：`username <name> password`、`segment user <name> password`、`aaa`/`tacacs`/`radius` 认证配置

**全局清除**：`clear config`

**白名单（允许下发）**：SLB 全模块（slb *）、SDNS 全模块（sdns *）、分区（segment *）、SSL、HA 全模块（ha *）、系统安全子集（hostname/ntp/syslog/snmp/log/system *——危险命令如 system reboot/shutdown 由黑名单拦截）、删除/清除（no slb/clear slb/no sdns/clear sdns/no segment/clear segment/no ssl/clear ssl/no ha/clear ha 前缀均允许）、持久化（write memory/write segment）

## Workflow checklist

Copy this checklist at the start and tick items off as the corresponding steps complete:

```
Device Verify progress:
- [ ] Step 1: Scenario determined + target device IP + credentials ready
- [ ] Step 2: Every deploy command marked safe/blocked/uncertain against the blacklist (deploy only)
- [ ] Step 3: Every command traced to its CLI-manual definition (full name + parameters)
- [ ] Step 4: Commands executed (dev_rest → dev_ssh → manual fallback), outputs collected
- [ ] Step 5: Device output vs. expectation compared item by item (read-only only)
- [ ] Step 6: Effect confirmed via show; no write memory unless the user asked (deploy only)
- [ ] Step 7: Four-section report delivered; no tool calls after output started
```

## Steps

### 1. Determine the scenario and target device

**Execution**: Direct

Decide the scenario (read-only verification vs. configuration deployment). Determine the target device IP from `knowledge/data/auto_env/network_topology_rag.md` (the single source of truth for device addresses — read it, do not recall addresses from memory). If credentials were not provided, ask_user.

**Success criteria**: scenario decided + target device IP + credentials ready
**Artifacts**: scenario, target_device_ip

### 2. High-risk command pre-check (when applicable: configuration deployment)

**Execution**: Direct

Check every command to be deployed against the blacklist, one by one. Hits the blacklist → refuse and explain why. Hits the whitelist → pass. Uncertain → ask_user to confirm.

**Rules**: even if the configuration contains a high-risk command, it must be refused — never silently skipped
**Success criteria**: every command marked safe/blocked/uncertain
**Artifacts**: command_safety_checklist

### 3. Build the execution command list

**Execution**: Direct

**⚠️ Mandatory step: every command (show and config alike) must be looked up in the CLI manual before execution.**

First grep `knowledge/data/markdown/product/cli_*_Chapter*.md` + `cli_*_Appendix*.md` to confirm each command's **full name and parameters** — copy the full form from the manual, never a shortened one. A truncated show command is often still accepted by the device but silently drops the very columns you came to verify (measured: omitting a trailing keyword returned a table without the method column), so a "working" short command can fail the verification without any error. `kb_footprint` carries device-verified command forms for the same purpose — check it before improvising, and when the manual and footprint disagree, prefer the footprint's on-device-verified form.

**Configuration deployment**: first confirm each command's full syntax and parameter constraints in the CLI manual (same CLI verification flow as config-answer), then order the commands marked safe in Step 2 by dependency.

**Rules**: never guess commands; every command must be found in the CLI manual
**Success criteria**: every command traceable to its definition in the CLI manual
**Artifacts**: show_commands_with_expected (read-only) / deploy_command_sequence (deployment)

### 4. Execute the commands

**Execution**: Direct (dev_rest first → dev_ssh fallback) or [human] (manual via ask_user)

**Priority**: `dev_rest` > `dev_ssh` > manual execution

1. **Prefer `dev_rest`**: the REST API is fastest (a single HTTP round-trip), no SSH handshake overhead, supports `\n` interactive commands. show and config commands are both a single POST — no mode switching needed
2. **Fall back to `dev_ssh`**: use SSH when the REST API is unavailable (connection failure / 401 / unsupported device)
3. **Last resort — human**: when neither works, ask_user to have the user execute manually, following `main/ist_core/skills/device-verify/reference/ssh_template.md`

**Human checkpoint**: before configuration deployment, confirm the user knows the device configuration will be modified (list the target device + the commands to deploy)

**Rules**: during deployment, never continue past a failed command; the REST-API-before-SSH order must not be reversed
**Success criteria**: all commands executed and outputs collected (or aborted at the first error)
**Artifacts**: execution_results

### 5. Compare and analyze (when applicable: read-only verification)

**Execution**: Direct

Compare device output against expectations item by item: values match? states normal? On mismatch, analyze the cause (not deployed / syntax error / stale config conflict).

**Success criteria**: every comparison has an explicit match/mismatch conclusion + difference analysis
**Artifacts**: comparison_results

### 6. Persistence and verification (when applicable: configuration deployment)

**Execution**: Direct

**Do not save by default**: after deployment, do **not** run `write memory`. Skip it unless the user explicitly asks to "save the configuration" or "persist". This avoids overwriting unsaved configuration already on the device.

**Verify the deployment**: run the corresponding show commands to confirm the configuration took effect. Verification passing completes the task; no extra save step.

**Success criteria**: configuration confirmed in effect + complete deployment summary (no save needed)
**Artifacts**: deploy_summary

### 7. Output the report

**Execution**: Direct

Output in the following structure (no tool calls once output starts):

```
### 设备信息
- 目标设备：<设备名> (<IP>)
- 操作类型：只读验证 / 配置下发
- SSH 用户：<用户名>

### 命令执行结果

| # | 命令 | 执行状态 | 输出摘要 |
|---|------|---------|---------|
| 1 | `<命令原文>` | success | ✓ 包含 <关键字段/值> |
| 2 | ... | error | ... |

### 详细分析
<对 error/mismatch 项的详细说明，附实际输出关键片段>

### 结论
- 成功：N 条 / 失败：N 条
- 建议：<修正建议或下一步>
```

**Rules**: no tool calls during the final output
**Success criteria**: the report contains the full four-section structure (device info + execution result table + detailed analysis + conclusion), with root-cause analysis for every abnormal item
