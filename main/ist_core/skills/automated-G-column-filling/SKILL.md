---
name: automated-g-column-filling
description: 自动为测试用例表格的 G 列生成具体内容，并可通过烟雾测试验证修正
context: inline
user-invocable: true
when_to_use: |
  Use when 用户要求填充测试用例 xlsx 的 G 列（具体内容列），或说要"跑测试"、"验证G列"、"烟雾测试"。
  Trigger phrases: 填G列, 填充用例, 生成具体内容, 补全测试步骤, filled_, G列, 跑测试, 烟雾测试, 验证G列
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

实际工作流程：
- `g-column-filler` — fork skill，查 CLI 文档生成 G 列命令
- 烟雾测试 — 上传 xlsx 到 Linux 执行 pytest，返回失败 case 详情，分析修正

你负责读取 xlsx、分析结构、委托 fork、写入结果。

## Inputs

- 测试用例 xlsx 文件路径（位于 workspace/inputs/）
- 文件名通常含模块关键词（如 `APV_SDNS_Listener` → SDNS Listener）

## Goal

产出 `workspace/outputs/filled_<原名>.xlsx`，G 列逐行填充并通过设备验证，check_point 与设备实际输出一致。

## Principles

- xlsx 写入必须用 `write_g_column.py` 脚本——**禁止自行构造输出文件名**。脚本自动将文件名加 `filled_` 前缀输出到 `workspace/outputs/`（如 `sdns_listener.xlsx` → `filled_sdns_listener.xlsx`）。
- **xlsx_path 必须指向 `workspace/inputs/` 下的源文件**，脚本会自动输出到 `workspace/outputs/filled_<原名>.xlsx`，不要传输出文件路径
- 所有 IP/设备参数以 network_topology_rag.md 为权威来源
- CLI 命令生成全部委托给 fork——你不要自行生成 APV 命令

## Steps

### 1. 读取用例 D/E/F 列

**Execution**: Direct（qa_exec + main/ist_core/skills/automated-G-column-filling/scripts/read_xlsx_rows.py）

qa_exec 运行 read_xlsx_rows.py 读取 D/E/F 列。跳过 C='0'、D/E/F 全空、E 和 F 均为空的元数据行。返回 JSON 含行号→{D,E,F,G} 映射。

```bash
python main/ist_core/skills/automated-G-column-filling/scripts/read_xlsx_rows.py <相对路径>.xlsx
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

**Execution**: Direct（qa_exec + main/ist_core/skills/automated-G-column-filling/scripts/write_g_column.py）

qa_exec 运行 write_g_column.py 写入 G 列。已有内容的行自动跳过。输出到 `workspace/outputs/filled_<原名>.xlsx`。脚本内置保护：拒绝源路径=输出路径的情况。

**⚠️ xlsx_path 参数必须是 `workspace/inputs/` 下的源文件路径**，脚本会自动输出到 `workspace/outputs/`。

```bash
python ../../main/ist_core/skills/automated-g-column-filling/scripts/write_g_column.py ../../workspace/inputs/<文件名>.xlsx '<g_updates JSON>'
```

执行完成后输出汇总：原文件/输出文件路径、总数据行数/基础配置行行号、已填充 N 行/跳过 N 行/未生成 N 行（列出未生成行号和原因，来自 fork 返回的 `unfilled`）。

**Success criteria**: 能确认输出文件路径 + 每行 G 列状态（已填充/跳过/未生成）可追溯
**Artifacts**: output_file_path, fill_summary

### 6. 烟雾测试验证与修正 (optional)

**Execution**: SCP 上传 + MCP tool（smoke_test_run）

当用户要求验证 G 列或运行自动化测试时，通过烟雾测试结果验证 G 列并自动修正。

**Step 6a**: **必须先上传再测试，不可跳过**。凭据从环境变量获取：
- `qa_exec` 执行 `import os; print(os.environ.get('LINUX_TEST_HOST'), os.environ.get('LINUX_SSH_USERNAME'), os.environ.get('LINUX_SSH_PASSWORD'))`
- 目标路径 `/home/test/apv_src/smoke_test/istcore/<stem>/`，stem 用 **filled 文件名**去 .xlsx（如 `filled_sdns_listener`，不是源文件 `sdns_listener`）
- 禁止问用户——凭据已在环境变量中
- 用 `qa_exec + paramiko` SFTP 上传。上传成功后才能进入 Step 6b

**Step 6b**: 上传确认后，调 `qa_smoke_test(filename="filled_<原名>.xlsx")`。返回每个失败 case 的详细信息。

**Step 6c**: 分析失败结果并修正。

**分析失败只能基于 MCP 返回的上下文**（步骤描述、执行的命令、Fail/Success 行），**禁止到设备上执行命令验证**。不要调 `qa_ssh`、`qa_restapi`、`qa_run_case`、`qa_probe_show` 等设备工具——烟雾测试已在真实设备上执行过，返回的报告就是权威结果。

**自动化平台执行逻辑**（理解失败原因的关键）：
- 平台按行号顺序执行每行：APV 配置命令 → 下发到设备；APV show 命令 → 执行并捕获输出；test_env → 在 Router 上执行 dig/curl 等；check_point → 在前一行捕获的输出中**字符串匹配** G 列的值
- `found` → 在输出中**必须找到** G 列的字符串；`not_found` → 在输出中**不能找到** G 列的字符串
- 失败原因解读：
  - `fail to find <G列值> in:` → 该值在设备输出中不存在，G 列的 check_point 填错了
  - `successed to find <值>` → 该值在输出中存在，check_point 正确
  - 查看报告中的设备输出片段（`in:` 后面的内容），对比 G 列的期望值，确定正确值应该是什么
- 常见失败模式：
  - IP 错误：G 列写了 `172.16.35.231` 但设备实际响应的 A 记录是其他 IP
  - 格式错误：G 列写了正则 `A\s+172.16.35.231` 但平台做的是纯字符串匹配
  - 命令参数错误：listener IP/端口写错导致 show 输出与预期不符

- `smoke_test_run` 返回了每 case 的 `Fail` 行和上下文（步骤/命令/check_point），直接分析失败原因
- G 列错误 → 定位对应行号，修正内容**必须逐行对号入座 E/F 列速查规范**。不只看 check_point，**所有行的修改都要遵守 g-column-filler 的规则**：
  - `APV | execute` → 必须从 `knowledge/data/auto_env/execute_action` 查找，严禁自行编造
  - `APV*` → 参数必须从 CLI 手册提取，严禁推断
  - `check_point | found` → 格式由前一行决定，不是自己决定
  - `test_env` → 参数从前面 APV 行提取
  - `time | sleep` → 只写数字
  如果某一行的修正需要查 CLI 手册或 execute_action，必须查完再改，不能跳过
- **修正要基于 D 列描述的预期行为**：D 列说"可以访问成功"→ check_point 应该是可达的后端 IP（如 `172.16.35.231`）；D 列说"配置添加成功"→ check_point 应该是 CLI 完整输出格式。修改值要符合 test case 设计的预期，不是照抄设备实际输出，更不能编造 `connection timed out` 等无关内容
- 修正后调用 `write_g_column.py` 写入 **Step 5 生成的 filled 文件**（`workspace/outputs/filled_<原名>.xlsx`），使用 `--overwrite` 覆盖已有内容。**禁止**生成新的 `_corrected` 文件
- **修正后必须重新上传到 Linux**（同 Step 6a），覆盖旧文件，然后再次 `qa_smoke_test`（最多 3 轮）
- **循环：分析→修正→写入→上传→测试→分析→...** 直到全部通过或无法自动修正
- 非 G 列错误（环境、设备配置等）→ 报告用户，不自动修正

触发条件：用户说"跑一下测试""验证G列""跑用例"。

**Success criteria**: 测试通过或失败已分析修正
**Artifacts**: smoke_test_result, corrections
