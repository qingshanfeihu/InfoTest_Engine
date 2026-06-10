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

**⚠️ 填写每条 G 列前，必须先查此表对号入座。禁止凭感觉或跳步。**

| E 列 | F 列 | G 列必须填 | 常见错误 |
|------|------|-----------|---------|
| `APV*` | — | CLI 命令（参数必须从 CLI 手册提取，严禁推断） | 凭记忆写参数、跳过 CLI 验证流程 |
| `APV` | `execute` | 从 `execute_action` 查找的命令，严禁自行编造 | 自己编一个看着像的命令 |
| `check_point` | `found` | 可精确匹配的内容（格式由**前一行**决定，不是自己决定） | D列写"配置添加成功"就填裸IP |
| `check_point` | `not_found` | 前一行 show 的输出中**不应出现**该内容。格式同 found（写预期不出现的标识符），但含义相反 | 与 found 同组（紧邻且测试同一资源）时内容相同，属于正常；不同组时应从上下文推断 |
| `check_point` | `found times` | **只写数字**（如 `3`），不加任何其他文字 | 写成 `3 times` |
| `test_env` | — | Linux 命令行（dig/curl/ping 等），参数从前面 APV 行提取 | 编造端口号、加 `-6` 标志 |
| `time` | `sleep` | 纯数字（如 `5`），**不带单位不带引号** | 写成 `5s`、`sleep 5` |

**F=`cmd_config` 决策树**（按顺序判断，不跳步）：
1. 看**下一行**的 E：下一行是 `check_point` + F=`found` → **show 命令**（展示配置结果）
2. 否则 → 配置命令
3. 回看**前面 G 列**中该资源是否已出现 → 已出现=modify，首次出现=create

## Principles

- CLI 文档是 APV 命令的**唯一权威来源**——语法、参数顺序、必选/可选、取值范围、默认值全部以文档为准
- 基础配置必须是**完整的服务配置**，而非仅包含被测特性本身
- **IP/端口必须从上游数据严格引用**：IP 从 device_ip_map 或 topology_rag.md 精确取值；端口从基础配置行或前面 APV 行提取，禁止凭记忆写默认端口
- **D 列上下文引用推断**：当 D 列出现「同一个」「另一个」「不同的」「同上」「同前」「新增」「第二个」「第三个」等指代词时，**必须回看前面已填写行的 G 列内容来推断本行 G 列**：
  - 「同一个 XXX」→ 复用前面行中 XXX 的资源名/IP/端口（完全相同）
  - 「另一个 YYY」→ 使用与前面不同的值（从可用资源池中选取不同的，如 topology 中另一台服务器 IP、另一个端口号）
  - 「不同的 ZZZ」→ 与「另一个」同理，选取不同值
  - 「同上」「同前」→ 完全复制前面行 G 列内容
  - 「新增第N个」→ 在前面已创建资源的基础上，创建第 N 个同类型资源（命名递增，参数独立）
  - **判断前提**：先确定 D 列指代的是哪种资源（listener/real server/pool/VIP 等），再决定复用还是替换哪个参数
- 参数在 CLI 手册 md 分片或 code_format.json 中找不到明确定义 → 标记「未生成」
- **check_point 前置检查**：填 check_point 前必须先看前一行的 E 列和 G 列。前一行是 APV show/config → check_point 写 CLI 完整输出格式（如 SLB: `slb virtual http "v1" 172.16.34.100 80`），**绝对禁止裸 IP**。前一行是 test_env + D 列含「访问成功」→ check_point 填**后端服务器 响应内容或IP**（不是 DNS/VIP 的 IP）。只有前一行是 test_env（Linux 命令）且 D 列含「访问成功」时才写客户端侧的响应格式。**最容易犯的两个错误**：①看到 D 列「配置添加成功」就填裸 IP（前一行是 APV 时必须填 CLI 完整输出格式）；②看到 D 列「访问成功」就填 DNS/VIP 的 IP（应根据访问类型填后端服务器 响应内容或IP）。**found 和 not_found 的区别**：found = 预期该标识符在输出中存在；not_found = 预期该标识符在输出中不存在。两者格式相同但含义相反——found 和 not_found 紧邻时通常是同一资源的正反验证（先配置→found，再修改→not_found），内容相同是正确的，不要误判为错误。

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

#### 1b. 确定模块并查文档

用 `module_keywords` 确定范围。**搜索优先级**：

1. **首选** grep `knowledge/data/markdown/product/app__part*.md`、`app_21__part*.md` 或 `ePolicy用户指南.md`，查找该业务的**完整配置示例**（如 SLB 的 virtual server + real server + group + health check 完整创建流程）。找到后修改 IP/端口/名称即可
2. 主力 grep `knowledge/data/markdown/product/cli__part*.md`、`cli_74__part*.md`（纯文本 CLI 手册分片），对 1a 清单中的每种资源类型找到对应的 add/create/set 命令语法
3. 兜底 grep `knowledge/.intermediate/mineru/cli_*part*.code_format.json` 的 `markdown` 字段

#### 1c. 逐资源生成创建命令

按依赖顺序（先创建被依赖资源，再创建依赖资源）为 1a 清单中的每种资源生成创建命令。CLI 手册有配置示例时以此为模板。多条命令用换行分隔。只做搭建，不含清除命令（no/clear 等）。

**命令顺序原则**：先启用模块（如 `sdns on`），再创建基础资源（host/domain），然后创建服务组件（service/pool），最后创建接入层（listener）。启用命令必须放在第一条。

**Listener 创建策略**：基础配置行**通常不创建 listener**——listener 由后续各测试组按需创建（不同测试组有不同的 IP/端口/协议需求）。除非 1a 资源清单中只有一个固定的 listener 配置被所有后续行共用。

**常见模块的服务栈参考**（基础配置至少需覆盖该模块服务栈的全部层级）：

| 模块 | 服务栈层级（从底向上）                                         | 最少命令数 |
|------|-----------------------------------------------------|-----------|
| SDNS | sdns on → host → service → pool → listener          | ≥4 |
| SLB | virtual server → real server → group → health check | ≥3 |
| HA | ha unit → ha group → ha fip                         | ≥3 |

**硬性门槛**：如果生成的基础配置命令数少于该模块的最少命令数，说明遗漏了服务栈的某层，必须回到 1a 重新盘点。

#### 1d. 自检（每条必须通过，不通过则回到 1a）

1. 1a 清单中的**每一种**资源类型都有对应的创建命令？
2. 命令数达到模块最少命令数门槛？
3. 依赖顺序正确（先创建被依赖资源）？
4. 后续 check_point/test_env 中出现的域名/端口在基础配置中已创建？
5. 后续 show/统计操作有对应开启命令（如 log on）？
6. 每条 APV 参数已通过 CLI 验证流程（见 Step 2e）？
7. 需要手动启用的模块/功能/节点已追加启用命令？（查 CLI 手册确认默认启用状态，默认关闭的必须加 `sdns on`/`ha on` 等）
8. 跨模块资源已处理？
9. **无孤悬资源**：每个 real server 是否通过 group member 被引用？每个 health check 是否 bind 到了对象？每个 pool/group 是否被 virtual server 或 policy 使用？定义但无人引用的资源 → 补充引用或删除

**Success criteria**: 基础配置行命令完整覆盖 1a 资源清单中的所有资源类型，9 条自检全部通过

### 2a. check_point (when applicable)

对基础配置行之外 E=check_point 的行，G 列填写脚本可精确匹配的内容，禁止描述性文字。

**决定 G 列格式的不只是 D 列文字，还依靠前一行的 E 列和 G 列**。按下表从上到下匹配（第一条命中即停止），**适用所有模块**：

| 优先级       | 前一行特征 | G 列格式 | 示例（多模块）                                                                                                          |
|-----------|-----------|---------|------------------------------------------------------------------------------------------------------------------|
| **1（最高）** | 前一行 E=APV，G 列为 show 命令 | 该 show 命令的 CLI 完整输出格式 | SLB: `slb virtual http "v1" 172.16.34.100 80`；SDNS: `sdns listener 172.16.34.70`；HA: `ha group status HA active` |
| **2**     | 前一行 E=test_env（所有其他情况——含「dig」「curl」「ping」「访问」）| 该工具的标准输出格式，**不可留空** | dig: `A\s+172.16.35.231`；curl: `HTTP/1.1 200 OK`；ping: `64 bytes from`                                           |

**Rules**:
- **⚠ 前面是 APV show 命令时，check_point 必须写 CLI 完整输出格式**：如果本行 check_point 的**前一行是 APV 且其 G 列为 show/list/display 查看命令**，则本行值**必须**匹配该 show 命令的 CLI 输出完整格式（如 `sdns listener 172.16.34.70`），**绝对不允许只填裸 IP**。回看上一行即可判断。
  - **值的格式由 D 列检查内容决定**
- **check_point 必须体现本组测试焦点**：回看本组第一个有 D 列的行，提取测试焦点（端口/协议/IP 类型/超时值/状态码等），确保 check_point 包含该焦点的对应值。不同模块的测试焦点不同，但判断逻辑一致
- **最容易犯的两个错误**：
  - 看到 D 列「配置添加成功」就填裸 IP → 错误。前一行是 APV 时必须填 CLI 完整输出格式
  - 看到 D 列「访问成功」就填 DNS/VIP 的 IP → 错误。"访问成功"验证的是**后端可达性**，填写内容 必须是后端服务器的 响应（如 `HTTP/1.1 200 OK` ）或IP（如 `172.16.35.231`），不是访问的目标IP（如 VS 或 sdns listener 的ip）

**Success criteria**: 每条 check_point 可被脚本精确匹配，且反映本组测试焦点

### 2b. test_env (when applicable)

根据 D/F 列确定命令（dig/curl/ping/tcpdump/telnet/nc/wget），从前面 APV 行提取 IP/端口/域名组合为完整命令行。

**Rules**: D 列含 `udp` → dig 默认 UDP；含 `tcp` → dig 加 `+tcp`；含 `tcp/udp` 出现两次 → 第一次 UDP 第二次 `+tcp`。

**Success criteria**: 每条 test_env 命令参数完整、来源可追溯到前面 APV 行，dig 命令严格遵守格式规范

### 2c. time (when applicable)

F=sleep 时填数字。根据当前测试的功能配置和cli对此功能的描述推断；无法确定默认 `5`。

**Success criteria**: 每条 time 值有合理依据

### 2d. APV + F=execute (when applicable)

无论 D 列内容是什么，G 列必须从 `knowledge/data/auto_env/execute_action` 查找。按 D 列关键词匹配条目 → 找不到选语义最接近的 → 仍无法确定标记「未生成」。

**Rules**: 严禁自行编造 CLI 命令

**Success criteria**: 每条 execute G 列可追溯到 execute_action 原文，或标记「未生成」

### 2e. APV 通用 (when applicable)

两级查找：优先 grep `cli__part*.md` / `cli_74__part*.md` → 兜底 `knowledge/.intermediate/mineru/cli_*part*.code_format.json`。

CLI 验证流程（每条 APV 命令必须走完）：
1. 在 `cli__part*.md` 中用第一关键字 grep 定位语法骨架（命中章节标题或命令行示例）
2. `qa_footprint_lookup("<命令前缀>")` 查决策规则/已知缺陷
3. read_file 同一 md 分片中该命令所在段落（上下各扩 20–40 行），提取合法取值/默认值/约束；需要完整配置示例时 read_file `ePolicy用户指南.md` 或 `app__part*.md` 对应章节
4. 提取语法：必选参数（无 `[ ]`）、可选参数（`[param]`）、**逐参数提取约束**（手册中出现「取值必须为」「取值范围」「允许值」「可选值」等说明时，必须原样记录，绝不能凭感觉缩略或忽略）、默认值
5. 逐参数填写：必选→必须出现；可选不影响→省略；可选影响→**值必须严格在步骤 4 记录的约束范围内**；顺序与文档一致。手册写「取值必须为 1/2/3」就不能填 0 或 4；写「必须为 IP 地址格式」就不能填域名；写「必须为已创建的 xxx 名称」就必须引用前面已创建的资源名
6. 任何参数找不到明确定义 → 禁止填入，标记「未生成」

**Rules**: 禁止凭拓扑 IP 推断、凭命令名相似推断、画蛇添足写默认值。 

**Success criteria**: 每条 APV 命令的所有参数可追溯到文档定义，或标记「未生成」

### 2f. 跨模块资源 (when applicable)

`cross_module_deps` 非空时触发。

**SLB virtual server 未指定类型时，默认类型为 http，只有当前主要功能模块为 SLB 时才进行推断，否则禁止根据当前模块类型推断**（如 SDNS 模块 → `slb virtual dns` 是错误的）。

- D 列有内容的主步骤行 → 创建 SLB virtual server：`slb virtual http "v1" <VIP_IP> 80 arp 0`（类型固定 http，端口固定 80，arp 固定 0）
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
