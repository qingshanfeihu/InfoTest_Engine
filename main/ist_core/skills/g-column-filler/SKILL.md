---
name: g-column-filler
description: 接收 structured brief，查询 CLI 文档，为测试用例每行生成 G 列内容，返回 g_updates JSON
context: fork
agent: g-column-filler
user-invocable: false
when_to_use: |
  Use when automated-g-column-filling 需要生成 G 列 CLI 命令。
  SKIP when: 不应由用户直接触发——仅通过 qa_invoke_skill 由 inline skill 间接调用。
allowed-tools:
  - qa_deepagent_read_file
  - qa_deepagent_grep(knowledge/data/markdown/product/*)
  - qa_deepagent_grep(knowledge/data/auto_env/*)
  - qa_deepagent_ls
  - qa_exec
  - qa_bash
  - qa_footprint_lookup
---

# G-Column Filler

接收来自 automated-g-column-filling 的结构化 brief，为每行生成 G 列内容，返回 g_updates 作为 machine-readable JSON。

**Your output IS the machine-readable result for the caller**——不要写文件，不要输出用户报告，返回结构化 JSON 即可。

## Brief

$ARGUMENTS

## E/F 列速查

| E 列 | F 列 | G 列应填 |
|------|------|---------|
| `APV*` | — | CLI 命令，参数严禁推断，必须走 CLI 验证流程 |
| `APV` | `execute` | 从 `knowledge/data/auto_env/execute_action` 查找，严禁自行编造 |
| `check_point` | `found` | 应匹配到的标识符。前一行通常是 test_env 或 APV show——验证上一行的操作结果 |
| `check_point` | `not_found` | 应不存在的标识符。典型模式：正向 found → 改配置 → not_found（反向测试） |
| `check_point` | `found times` | 只写数字（如 `3`） |
| `test_env` | — | Linux 命令行（dig、curl、ping 等） |
| `time` | `sleep` | 等待秒数（纯数字，不带单位） |

F=`cmd_config` 时需判断 create / modify / show：下一行 check_point+found → show；否则配置命令。回看前面 G 列，资源已出现 → modify，首次出现 → create。

## Principles

- CLI 文档是 APV 命令的**唯一权威来源**——语法、参数顺序、必选/可选、取值范围、默认值全部以文档为准
- 基础配置必须是**完整的服务配置**，而非仅包含被测特性本身
- **IP/端口必须从上游数据严格引用**：IP 从 device_ip_map 或 topology_rag.md 精确取值；端口从基础配置行或前面 APV 行提取，禁止凭记忆写默认端口
- 参数在 code_format.json 中找不到明确定义 → 标记「未生成」
- **check_point 前置检查**：填 check_point 前必须先看前一行的 E 列和 G 列。前一行是 APV show/config → check_point 写 CLI 完整输出格式（如 SLB: `slb virtual http "v1" 172.16.34.100 80`），**绝对禁止裸 IP**。前一行是 test_env + D 列含「访问成功」→ check_point 填**后端服务器 响应内容或IP**（不是 DNS/VIP 的 IP）。只有前一行是 test_env（Linux 命令）且 D 列含「访问成功」时才写客户端侧的响应格式。**最容易犯的两个错误**：①看到 D 列「配置添加成功」就填裸 IP（前一行是 APV 时必须填 CLI 完整输出格式）；②看到 D 列「访问成功」就填 DNS/VIP 的 IP（应根据访问类型填后端服务器 响应内容或IP）。此规则适用所有模块

## Steps

### 1. 生成基础配置行 G 列

基础配置行是**整个用例的基石**——后续所有行都依赖它创建的资源。生成过程分四步，**必须按顺序执行，禁止跳过**。

#### 1a. 资源盘点（不可跳过）

逐行扫描后续所有行的 D/E/F/G 列，提取每个被引用或将被操作/访问/验证的资源，按类型归类为资源清单：

| 资源类型 | 来源（行号+D列关键词） | 需要的参数 |
|---------|---------------------|-----------|
| host/domain | 行X D列提到"域名""host" | 域名值 |
| service/pool | 行X D列提到"服务""pool" | 服务名 |
| listener | 行X D列提到"监听""listener""端口" | IP、端口、协议 |
| real/server | 行X D列提到"服务器""real" | IP、端口 |
| virtual/VIP | 行X D列提到"vip""virtual" | VIP IP、端口 |
| health check | 行X D列提到"健康检查""health" | 检查类型 |
| log/统计 | 行X D列提到"查看""统计""show" | 对应模块 |

**域名/端口提取规则**：从后续所有行中提取域名（如 `autotest.com`）和端口号（如 `53`、`80`），这些值必须在基础配置行中出现对应的创建命令。如果后续行中首次出现了访问某域名，基础配置行或该访问行之前的配置行必须有创建该域名的命令。**禁止**在后续行凭空出现一个基础配置行或该访问行之前的配置行未创建的域名访问。

#### 1b. 确定模块并查 CLI 手册

用 `module_keywords` 确定 CLI 手册范围。优先 grep `cli_*_commands.md`（纯文本）；兜底 grep `cli_*part*.code_format.json` 的 `markdown` 字段。对 1a 清单中的每种资源类型，找到对应的 add/create/set 命令语法。

#### 1c. 逐资源生成创建命令

按依赖顺序（先创建被依赖资源，再创建依赖资源）为 1a 清单中的每种资源生成创建命令。CLI 手册有配置示例时以此为模板。多条命令用换行分隔。只做搭建，不含清除命令（no/clear 等）。

**命令顺序原则**：先启用模块（如 `sdns on`），再创建基础资源（host/domain），然后创建服务组件（service/pool），最后创建接入层（listener）。启用命令必须放在第一条。

**Listener 创建策略**：基础配置行**通常不创建 listener**——listener 由后续各测试组按需创建（不同测试组有不同的 IP/端口/协议需求）。除非 1a 资源清单中只有一个固定的 listener 配置被所有后续行共用。

**常见模块的服务栈参考**（基础配置至少需覆盖该模块服务栈的全部层级）：

| 模块 | 服务栈层级（从底向上） | 最少命令数 |
|------|---------------------|-----------|
| SDNS | sdns on → host → service → pool → listener | ≥4 |
| SLB | virtual server → real server → group → health check | ≥3 |
| HA | ha group → ha config → ha track | ≥3 |
| FW | fw enable → fw zone → fw rule → fw policy | ≥3 |

**硬性门槛**：如果生成的基础配置命令数少于该模块的最少命令数，说明遗漏了服务栈的某层，必须回到 1a 重新盘点。

#### 1d. 自检（每条必须通过，不通过则回到 1a）

1. 1a 清单中的**每一种**资源类型都有对应的创建命令？
2. 命令数达到模块最少命令数门槛？
3. 依赖顺序正确（先创建被依赖资源）？
4. 后续 check_point/test_env 中出现的域名/端口在基础配置中已创建？
5. 后续 show/统计操作有对应开启命令（如 log on）？
6. 每条 APV 参数已通过 CLI 验证流程（见 Step 2e）？
7. 跨模块资源已处理？

**Success criteria**: 基础配置行命令完整覆盖 1a 资源清单中的所有资源类型，7 条自检全部通过

### 2a. check_point (when applicable)

对基础配置行之外 E=check_point 的行，G 列填写脚本可精确匹配的内容，禁止描述性文字。

**决定 G 列格式的不是 D 列文字，而是前一行的 E 列和 G 列**。按下表从上到下匹配（第一条命中即停止），**适用所有模块**：

| 优先级 | 前一行特征 | G 列格式 | 示例（多模块） |
|-------|-----------|---------|-------------|
| **1（最高）** | 前一行 E=APV，G 列为 show/list/display 命令 | 该 show 命令的 CLI 完整输出格式 | SLB: `slb virtual http "v1" 172.16.34.100 80`；SDNS: `sdns listener 172.16.34.70`；HA: `ha group status HA active` |
| **2** | 前一行 E=APV，G 列为配置命令（非 show）| CLI 完整输出格式 | SLB: `slb real tcp "rs1" 172.16.35.231 80`；FW: `fw rule 10 permit` |
| **3** | 前一行 E=test_env，D 含「访问成功」| 后端服务器 IP 或响应内容 | `172.16.35.231` |
| **4** | 前一行 E=test_env（所有其他情况——含「dig」「curl」「ping」「访问」或 D 为空）| 该工具的标准输出格式，**不可留空** | dig: `SERVER: 172.16.34.70#53`；curl: `HTTP/1.1 200 OK`；ping: `64 bytes from` |

**Rules**:
- **⚠ 前面是 APV show 命令时，check_point 必须写 CLI 完整输出格式**：如果本行 check_point 的**前一行是 APV 且其 G 列为 show/list/display 查看命令**，则本行值**必须**匹配该 show 命令的 CLI 输出完整格式（如 `sdns listener 172.16.34.70`），**绝对不允许只填裸 IP**。回看上一行即可判断。
  - **值的格式由 D 列检查内容决定**
- **check_point 必须体现本组测试焦点**：回看本组第一个有 D 列的行，提取测试焦点（端口/协议/IP 类型/超时值/状态码等），确保 check_point 包含该焦点的对应值。不同模块的测试焦点不同，但判断逻辑一致
- **最容易犯的两个错误**：
  - 看到 D 列「配置添加成功」就填裸 IP → 错误。前一行是 APV 时必须填 CLI 完整输出格式
  - 看到 D 列「访问成功」就填 DNS/VIP 的 IP → 错误。"访问成功"验证的是**后端可达性**，填写内容 必须是后端服务器的 响应或IP（如 `172.16.35.231`），不是 DNS listener 的 IP（如 `172.16.34.70`）

**Success criteria**: 每条 check_point 可被脚本精确匹配，且反映本组测试焦点

### 2b. test_env (when applicable)

根据 D/F 列确定命令（dig/curl/ping/tcpdump/telnet/nc/wget），从前面 APV 行提取 IP/端口/域名组合为完整命令行。

**Rules**: D 列含 `udp` → dig 默认 UDP；含 `tcp` → dig 加 `+tcp`；含 `tcp/udp` 出现两次 → 第一次 UDP 第二次 `+tcp`。

**Success criteria**: 每条 test_env 命令参数完整、来源可追溯到前面 APV 行，dig 命令严格遵守格式规范

### 2c. time (when applicable)

F=sleep 时填数字。配置生效 5~10；服务重启 30~60；无法确定默认 `5`。

**Success criteria**: 每条 time 值有合理依据

### 2d. APV + F=execute (when applicable)

无论 D 列内容是什么，G 列必须从 `knowledge/data/auto_env/execute_action` 查找。按 D 列关键词匹配条目 → 找不到选语义最接近的 → 仍无法确定标记「未生成」。

**Rules**: 严禁自行编造 CLI 命令

**Success criteria**: 每条 execute G 列可追溯到 execute_action 原文，或标记「未生成」

### 2e. APV 通用 (when applicable)

两级查找：优先 grep `cli_*_commands.md` → 兜底 `cli_*part*.code_format.json`。

CLI 验证流程（每条 APV 命令必须走完）：
1. 在 commands.md 中用第一关键字 grep 定位语法骨架
2. `qa_footprint_lookup("<命令前缀>")` 查决策规则/已知缺陷
3. 利用 commands.md 头部的 `> 来源` 标注，read_file 跳转 code_format.json 对应行段，提取合法取值/默认值/约束
4. 提取语法：必选参数（无 `[ ]`）、可选参数（`[param]`）、合法取值、默认值
5. 逐参数填写：必选→必须出现；可选不影响→省略；可选影响→值从合法取值中选取；顺序与文档一致
6. 任何参数找不到明确定义 → 禁止填入，标记「未生成」

**Rules**: 禁止凭拓扑 IP 推断、凭命令名相似推断、画蛇添足写默认值。**Listener 端口只在 D 列明确提到时才附加——包括默认 DNS 端口 53 也不例外。** D 列只写协议类型（如「协议-IPV4」「协议-IPV6」「IP类型-port ip」「tcp/udp」）而无具体端口号 → 不附加任何端口。D 列写了具体端口号（如「port-10001」）→ 才附加该端口。Listener IP 未指定时用设备第一个 IPv4。**D 列含「系统ip」→ 使用当前模块设备的第一个 IPv4，不是其他设备的 IP。** 传输协议类 D 列（仅含 tcp/udp）→ 配置标准 listener（不带端口）。

**Success criteria**: 每条 APV 命令的所有参数可追溯到文档定义，或标记「未生成」

### 2f. 跨模块资源 (when applicable)

`cross_module_deps` 非空时触发。

**SLB virtual server 未指定类型时，默认类型为 http，只有当前主要功能模块为 SLB 时才进行推断，否则禁止根据当前模块类型推断**（如 SDNS 模块 → `slb virtual dns` 是错误的）。

- D 列有内容的主步骤行 → 创建 SLB virtual server：`slb virtual http "v1" <VIP_IP> 80 arp 0`（类型固定 http，端口固定 80，arp 固定 0）
- D 列为空的补充行 → 创建当前模块引用该 VIP 的命令（如 `sdns listener <VIP_IP> <port>`）
- VIP IP 从 `cross_module_deps` 中获取，禁止复用设备物理 IP 作为 VIP

**Success criteria**: 跨模块依赖行的 G 列可追溯到对应模块的 CLI 文档，SLB virtual server 类型为 http

### 3. 输出 g_updates

将所有生成的 G 列内容以 JSON block 输出（这是给 caller 的 machine-readable 数据）：

```json
{
  "g_updates": {
    "<行号>": "<G列内容>",
    ...
  },
  "unfilled": [
    {"row": "<行号>", "reason": "<原因>"},
    ...
  ]
}
```

之后附一段简短的中文摘要：基础配置包含哪些命令、多少行已填充、未填充的原因。

**Success criteria**: `g_updates` 覆盖所有数据行，`unfilled` 中每项有明确的未生成原因
