---
name: config-automation
description: IP replacement for APV load-balancer (SLB / SDNS) configurations. Replaces example IPs (10.x / 192.168.x) in a network configuration the LLM has already generated with the automation environment's real IPs, and produces matching verification commands.
context: inline
when_to_use: |
  Use when the LLM has already produced a configuration containing example IPs and the user asks to replace them with the environment's real IPs.
  Trigger keywords: 替换IP, 真实IP, 自动化环境, 10.x/192.168.x 配置
  SKIP when: the user only asks about command usage or theory, with no concrete config IP replacement involved.
allowed-tools: [fs_read, fs_write, fs_grep, fs_ls]
---

# IP Replacement Skill

Sole responsibility: **take configuration text the LLM has already generated, replace the
example IPs in it with real IPs from the automation environment, and produce the matching
verification commands.** This skill does not look up documentation, search command syntax,
or discover configurations — the configuration text comes from the conversation.

## Core rules

1. **IP replacement only**: never change domains, names, ports, weights, TTLs, or any other non-IP parameter
2. **No config line lost**: process line by line; do not drop a single line
3. **Verification paired**: for every configured object, provide the corresponding verification command (look its form up in the manual / footprint — do not invent it)
4. **Write to file**: results are written under `workspace/outputs/` (the agent's only writable root) — one subdirectory per run

## Execution steps (you perform these directly with fs_* tools)

1. **Read the topology** — `fs_read knowledge/data/auto_env/network_topology.json`
   (machine source of truth for device / server / segment addresses; the human-readable
   description is `network_topology_rag.md`). Never hard-code addresses from memory:
   a testbed swap changes the JSON, not this skill.
2. **Build the IP mapping** by the rules below (example IP → real IP, one row per distinct IP).
3. **Apply the mapping** to the configuration text line by line (rule 1 and 2 above).
4. **Produce the verification commands** for the replaced objects (rule 3 above).
5. **Write the outputs** — the replaced config script, the verification commands, and the
   mapping table — into a run-specific subdirectory under `workspace/outputs/`, then present
   the summary in the conversation using the format below.

## Mapping rules (mechanism — addresses come from the topology at run time)

- **VIP** → any unoccupied IP on the segment (start scanning from `.50` upward to skip
  gateways and other low-numbered infrastructure addresses)
- **Backend services** → the real server IPs from the topology
- **Never** seize an IP already held by an existing device
- **Example IP ranges** to detect and replace: `10.0.0.0/8`, `192.168.0.0/16`, `127.0.0.0/8`,
  and `172.16.0.0`–`172.16.31.255`. The environment's own segments (per the topology JSON)
  are real addresses and are never replaced.

## Output format (user-facing, keep in Chinese)

### IP映射表
| 原始IP | 替换IP | 角色 |
|--------|--------|------|

### 配置脚本
```text
<已替换IP的完整配置>
```

### 验证脚本
```text
<验证命令>
```

### 输出文件
| 文件名 | 说明 |
|-------|------|
