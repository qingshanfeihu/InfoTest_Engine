---
name: automated-g-column-filling
description: 自动为测试用例表格的 G 列生成具体内容（已知 D/E/F 列的前提下）
context: inline
user-invocable: true
when_to_use: |
  Use when 用户要求填充测试用例 xlsx 的 G 列（具体内容列），或说"帮我填用例"、"生成 G 列"、"补全测试步骤"、"填一下这个xlsx"。
  Trigger phrases: 填G列, 填充用例, 生成具体内容, 补全测试步骤, filled_, G列
  SKIP when: 用户只问 CLI 用法、产品规格说明、缺陷详情查询，或要求评审用例。
allowed-tools:
  - qa_deepagent_read_file
  - qa_deepagent_grep(knowledge/data/auto_env/*)
  - qa_deepagent_ls
  - qa_exec
  - qa_bash
  - qa_invoke_skill
effort: high
---

# Automated G-Column Filling

根据 D（步骤描述）/E（操作对象）/F（操作方法）列自动生成 G 列（具体内容），并在真实设备上验证 show 命令和 check_point 的准确性。G 列以 D 列描述为准，所有 IP/设备参数以 `knowledge/data/auto_env/network_topology_rag.md` 为权威来源。

实际工作由两个 fork skill 在独立 subagent 中完成：
- `g-column-filler` — 查 CLI 文档，生成 G 列命令
- `g-column-verify` — 设备上执行 show 命令，验证并修正 check_point

你负责读取 xlsx、分析结构、委托 fork、写入结果。

## Inputs

- 测试用例 xlsx 文件路径（位于 workspace/inputs/）
- 文件名通常含模块关键词（如 `APV_SDNS_Listener` → SDNS Listener）

## Goal

产出 `workspace/outputs/filled_<原名>.xlsx`，G 列逐行填充并通过设备验证，check_point 与设备实际输出一致。

## Principles

- xlsx 必须用 qa_exec + openpyxl 读写，输出加 `filled_` 前缀，禁止覆盖原文件
- 所有 IP/设备参数以 network_topology_rag.md 为权威来源
- CLI 命令生成全部委托给 fork——你不要自行生成 APV 命令

## Steps

### 1. 读取用例 D/E/F 列

**Execution**: Direct（qa_exec + main/ist_core/skills/automated-g-column-filling/scripts/read_xlsx_rows.py）

qa_exec 运行 read_xlsx_rows.py 读取 D/E/F 列。跳过 C='0'、D/E/F 全空、E 和 F 均为空的元数据行。返回 JSON 含行号→{D,E,F,G} 映射。

```bash
python main/ist_core/skills/automated-g-column-filling/scripts/read_xlsx_rows.py <相对路径>.xlsx
```

**Success criteria**: 能列出所有数据行的行号和 D/E/F/G 内容
**Artifacts**: rows_map, header_row

### 2. 分析用例结构

**Execution**: Direct

遍历 rows（按行号升序），从文件名提取测试主题关键词（如 `APV_SDNS_Listener` → SDNS Listener）。第一个数据行通常为**基础配置行**。

按 E 列分类每行（APV* / test_env / check_point / time / execute）。

**跨模块依赖检测**：
- D 列含 `slb vip`/`slb virtual`/`vip` → SLB；`port-`（非当前模块端口，如 `port-10001`）→ 需 SLB VIP；`ssl`/`https` → SSL；`fw`/`acl` → FW/ACL，且与当前模块不同 → 跨模块
- D 列含 `port-` 且当前模块非 SLB → 先创建 SLB virtual server，再创建当前模块引用命令（两步，如 human reference 中 row 65-66）
- IP 不在 network_topology_rag.md 任何设备 IP 中 → 需动态创建（通常是 VIP）

**Success criteria**: 能列出文件名关键词 + 基础配置行行号 + E 列分类 + 跨模块依赖清单
**Artifacts**: module_keywords, base_config_row, e_column_types, cross_module_deps

### 3. 读取拓扑文件

**Execution**: Direct（qa_deepagent_read_file）

读 `knowledge/data/auto_env/network_topology_rag.md`，提取所有设备 IPv4/IPv6、网段、连接关系。D 列中的设备名直接查表得 IP。

服务器 IP 选择：多台可选时优先选 IP 最多的 → 其次字母序最前。基础配置行选定后，后续所有行必须保持一致。

**Success criteria**: 能列出设备名→IP 映射表 + 网段信息
**Artifacts**: device_ip_map, subnet_info

### 4. 委托 fork skill 生成 G 列

**Execution**: Fork skill（qa_invoke_skill）

将 Steps 1-3 的产出组装为结构化 brief，调 `qa_invoke_skill(skill="g-column-filler", brief=...)`。

⚠️ **关键约束**：
- skill 名必须是 `g-column-filler`（fork skill），**不是** `automated-g-column-filling`（你已加载的 inline skill）
- `g-column-filler` 是 fork skill，会在独立 subagent 中执行 CLI 文档查询和命令生成，返回结构化 g_updates

**brief 结构**：

```text
xlsx_path: <原 xlsx 路径>
base_config_row: <行号>
module_keywords: <从文件名提取的模块关键词>
cross_module_deps: <跨模块依赖清单>
device_ip_map: <设备名→IP 映射 JSON>
subnet_info: <网段信息>
rows_map: <所有数据行的 D/E/F/G JSON，含行号>
e_column_types: <每行 E 列分类>
```

**Success criteria**: task 返回含 `g_updates` JSON block 的结果
**Artifacts**: g_updates (fork 产出的 {行号: G列内容} 映射), unfilled (未生成清单)

### 5. 写入 G 列并输出汇总

**Execution**: Direct（qa_exec + main/ist_core/skills/automated-g-column-filling/scripts/write_g_column.py）

qa_exec 运行 write_g_column.py 写入 G 列。已有内容的行自动跳过。输出到 `workspace/outputs/filled_<原名>.xlsx`。

```bash
python main/ist_core/skills/automated-g-column-filling/scripts/write_g_column.py <原文件相对路径>.xlsx '<g_updates JSON>'
```

执行完成后输出汇总：原文件/输出文件路径、总数据行数/基础配置行行号、已填充 N 行/跳过 N 行/未生成 N 行（列出未生成行号和原因，来自 fork 返回的 `unfilled`）。

**Success criteria**: 能确认输出文件路径 + 每行 G 列状态（已填充/跳过/未生成）可追溯
**Artifacts**: output_file_path, fill_summary

### 6. 设备验证 (optional)

**Execution**: Fork skill（qa_invoke_skill）

当用户要求验证 G 列准确性，或用例中包含 APV show 命令需要确认 check_point 时，调 `qa_invoke_skill(skill="g-column-verify", brief=...)` 在实际设备上重放配置并执行 show 命令，逐条验证 check_point 与设备输出是否一致。

触发条件：用户明确说"验证一下""上机确认"或在用例中看到 show 命令后询问用户是否需要验证。

brief 结构同 Step 4，追加 `target_device` 字段（设备 IP，从 topology 获取或询问用户）。

验证结果中 `corrections` 非空时，用 write_g_column.py 再次写入修正后的 G 列。

**Success criteria**: show 命令已设备执行、check_point 已验证或修正
**Artifacts**: corrections (验证 fork 返回的修正), show_outputs
