---
name: decompose-test-cases
description: 拆分用例+生成xlsx。TRIGGER: 拆分用例, decompose, 完整拆分, 流水线
when_to_use: |
  用户提供原始测试用例文件(.txt脑图/.xlsx用例表)要求拆分为原子步骤；用户要求生成xlsx测试用例文件；用户要求一条龙流水线(拉取→提取→拆分→生成xlsx→填充G列)；用户提到"拆分用例""用例分解""生成测试用例xlsx""补全用例""测试用例流水线"。SKIP: 用户只要求查看/搜索已有用例；只要求执行测试；只要求修改xlsx中某几个单元格。
allowed-tools: qa_fetch_test_cases qa_extract_test_cases qa_decompose_test_cases qa_inject_init_and_deps qa_generate_test_case_xlsx qa_invoke_skill qa_deepagent_write_file qa_deepagent_read_file
---

## Pipeline

**BLOCKING: 流水线必须从 step 0 执行到 step 4，缺一不可。在 step 4 执行完毕前，不得向用户报告任务完成。**

依次调用工具，不要手写 JSON：

```
# 0. （可选）从 Agile 平台拉取
qa_fetch_test_cases(case_id=<id>)
# 返回的 .txt 路径自动保存到 workspace/inputs/yzg/

# 1. 提取
qa_extract_test_cases(file_path="workspace/inputs/yzg/<name>.txt")
# 返回的 JSON 存为 <name>_extracted.json

# 2. 拆分
qa_decompose_test_cases(extracted_json_path="workspace/inputs/yzg/<name>_extracted.json")
# 返回的 JSON 存为 <name>_decomposed.json

# 2.5 处理 need_verify（见 2.3）
# 主 agent 读取 decomposed.json，找到 need_verify 的 check_point，推断并注入缺失的 trigger/verify 步骤，写回
qa_deepagent_read_file(file_path="workspace/outputs/yzg/<name>_decomposed.json")
# 主 agent 分析后用 qa_deepagent_write_file 写回修改后的 JSON

# 3. 生成 xlsx
qa_generate_test_case_xlsx(decomposed_json_path="workspace/outputs/yzg/<name>_decomposed.json")
# 返回的 xlsx 路径保存到 workspace/outputs/<name>/

# 4. 填充 G 列（调用 automated-g-column-filling skill）
qa_invoke_skill(skill="automated-g-column-filling", brief="对 workspace/outputs/<name>/ 下所有 xlsx 文件填充 G 列。decomposed JSON 路径: workspace/outputs/yzg/<name>_decomposed.json")
```

**关键：`<name>` 必须替换为实际人名**（如 `0001`、`yzg`、`dongkl`），否则输出文件名前缀不对。

**禁止中途停止：step 3 生成 xlsx 后，必须继续调用 step 4 的 `qa_invoke_skill` 填充 G 列。
仅当 step 4 返回成功后，流水线才算完成。**


## Step 1 提取

从脑图中提取测试用例，做简单的结构分解。

**职责**：
- 识别节点类型：P1=模块，P2=用例，P3=前置条件
- 提取模块级前置（P3 节点在模块层级）→ `modules[module].module_prerequisites`
- 提取用例级前置（P3 节点在用例子节点中）→ `case.case_prerequisites`
- 提取步骤（有孙节点的子节点 或 非末位叶子）→ `case.steps`
- 提取检查点（孙节点 或 末位叶子）→ `case.expected`

**输出**：extracted.json


## Step 2 拆分

对提取到的数据进行详细拆解，生成原子步骤。

**职责**：
- 注入模块级前置（优先 module_prerequisites，fallback 硬编码）
- 注入功能依赖（跨模块依赖）
- 拆分步骤（见 2.1）
- 推断 phase 和 type（见 2.2）
- 推断 actor（APV_0/APV_1/test_env/check_point）
- 推断 action（cmd_config/routera/clientc/found/not_found）
- 推断 g_fill（llm_pdf/llm_infer/direct）
- 注入 check_point（无条件注入，不依赖关键词过滤）
- 标记 `need_verify: true`（仅标记，由主 agent 在 Step 2.5 推断注入，见 2.3）

**输出**：decomposed.json


### 2.1 步骤拆分规则

一个步骤可能包含多个动作，需要拆分为原子步骤。

**拆分模式**：

1. **编号子步骤**：`1.配置xxx 2.使用dig请求tcp` → 拆成两步
2. **复合动作**：用逗号、顿号、"并且"、"然后"连接的多个动作 → 拆成多步
3. **配置+客户端动作**：`配置sdns，dig访问` → 拆成配置步骤 + 客户端步骤

**拆分示例**：

```
原始: "配置vh1协议为TLSv1.1，创建sdns service sdnsdc1 43.43.43.9将其与hc1绑定,
       rs配置为双向认证，并且发送certificate request报文，抓包查看健康检查"

拆分:
1. 配置vh1协议为TLSv1.1                    → Setup, device_config
2. 创建sdns service sdnsdc1...将其与hc1绑定  → Setup, device_config
3. rs配置为双向认证                         → Setup, device_config
4. 发送certificate request报文              → Trigger, client_action
5. 抓包查看健康检查                         → Verify, capture_verify
```

**注意**：
- 每个拆分后的步骤必须以动作关键词开头（配置/创建/发送/抓包/show 等）
- 如果某部分不是以动作关键词开头，可能是前一个动作的延续，不拆分
- 拆分后需要重新推断每个步骤的 phase 和 type


### 2.2 Phase + Type 框架

用 **phase** 三段式（Setup / Trigger / Verify）和 **type** 区分步骤类型。

**Phase（阶段）**：

| Phase | 含义 | 特点 |
|-------|------|------|
| Setup | 配置阶段 | 顺序执行，准备环境 |
| Trigger | 触发阶段 | 执行测试动作 |
| Verify | 验证阶段 | 必须有 expected |

**Type（类型）**：

| Type | 含义 | 示例 |
|------|------|------|
| device_config | 在设备上下发配置 | sdns on, sdns host name |
| client_action | 客户端发包/请求 | dig, curl, ping |
| capture_verify | 抓包/日志/命令行验证 | tcpdump, show, 查看 |
| device_query | 设备上查询状态 | show sdns service ip |

**推断规则**：

| 关键词 | Phase | Type | Actor |
|-------|-------|------|-------|
| 配置/创建/添加/设置/删除/启用/禁用 | Setup | device_config | APV_0 |
| sdns/slb/ha/firewall/ip | Setup | device_config | APV_0 |
| 初始化/基础环境/前置 | Setup | device_config | APV_0 |
| dig/ping/curl/发包/访问/请求 | Trigger | client_action | test_env |
| 抓包/tcpdump/查看/验证/检查/show | Verify | capture_verify | APV_0 |
| 断言/预期/应该/成功/失败 | Verify | capture_verify | check_point |

**输出格式**：
```json
{
  "c": 1,
  "phase": "Setup",
  "type": "device_config",
  "actor": "APV_0",
  "action": "cmds_config",
  "describe": "[前置] 初始化SDNS基础环境",
  "g_fill": "llm_pdf",
  "hint": "sdns on; sdns host name..."
}
```


### 2.3 验证步骤推断规则（主 Agent 推断）

decomposer 输出 `need_verify: true` 标记在 check_point 上。**主 agent 在 Step 2.5 中读取 decomposed.json，用自己的推理能力分析并注入缺失的 trigger/verify 步骤，再写回。**

**处理流程**：

1. `qa_deepagent_read_file` 读取 decomposed.json
2. 遍历每个 case 的步骤，找到 `need_verify: true` 的 check_point
3. 分析 check_point 前的步骤序列，判断缺失的是 trigger 还是 verify
4. 在 check_point 前插入推断的步骤
5. 重新编号 C 列
6. `qa_deepagent_write_file` 写回修改后的 decomposed.json


#### 两种缺失场景

**场景 A：缺少 Trigger 步骤**

check_point 描述含客户端关键词（"客户端/返回/访问/解析/dig/响应"），但前面**全是 Setup 步骤**，没有 Trigger。

→ 需要在 check_point 前注入一个客户端触发步骤。

判断依据：
- check_point.describe 包含 "客户端"、"返回"、"访问"、"解析"、"dig"、"响应" 等关键词
- check_point 前最近的非 check_point 步骤的 phase 全是 "Setup"

LLM 推断时分析：
1. check_point 描述 → 断言什么结果（如 "客户端能够返回A v4地址"）
2. 前面步骤的 hint → 配置了什么（如 sdns host name、sdns listener）
3. 从 hint/describe 中提取参数 → IP 地址、域名、端口等
4. 用例模块 → SDNS 用 dig，SLB 用 curl，通用用 ping

注入格式：
```json
{
  "c": N,
  "phase": "Trigger",
  "type": "client_action",
  "actor": "test_env",
  "action": "routera",
  "describe": "客户端发起DNS请求: dig @<ip> <domain>",
  "g_fill": "llm_infer",
  "hint": "dig @<listener_ip> <domain> [+tcp/+udp]"
}
```

**场景 B：缺少 Verify 步骤**

check_point 前是设备配置步骤，但没有 show 命令确认配置生效。

→ 需要在 check_point 前注入一个设备查询步骤。

判断依据：
- check_point 前最近的步骤 actor 是 APV_0/APV_1
- 该步骤的 action 是 cmd_config/cmds_config

LLM 推断时分析：
1. 前面配置步骤的 describe/hint → 配置了什么命令
2. 对应的 show 命令是什么（如配置了 sdns listener → show sdns listener）

注入格式：
```json
{
  "c": N,
  "phase": "Verify",
  "type": "device_query",
  "actor": "APV_0",
  "action": "cmd_config",
  "describe": "APV_0 执行 show sdns listener 确认配置生效",
  "g_fill": "llm_pdf",
  "hint": "show sdns listener"
}
```


#### 注入后的 C 列重编号规则

注入新步骤后，从注入位置开始，后续所有步骤的 C 值 +1。注入步骤继承被插入位置的原 C 值，原步骤及后续步骤顺延。


## Step 3 生成 xlsx

将 decomposed.json 转换为标准 xlsx 文件。

**职责**：
- 按 group 拆分，一个 group 生成一个 xlsx
- 列映射：A=autoid, B=优先级, C=步骤号, D=步骤描述, E=操作对象(actor), F=操作方法(action), G=数据
- G 列留空，由 Step 4 填充

**输出**：`workspace/outputs/<name>/<group>_test_cases.xlsx`


## Step 4 填充 G 列

调用 automated-g-column-filling skill 填充 G 列。

**职责**：
- 读取 xlsx 的 D/E/F 列
- 分析用例结构
- 读取拓扑文件
- 委托 g-column-filler fork skill 生成 G 列命令
- 写入 G 列

**输出**：`workspace/outputs/<name>/filled_<group>_test_cases.xlsx`


## 描述格式

D 列描述规则：**原文完整保留，不截断**。

| Phase | Type | 描述格式 |
|-------|------|---------|
| Setup | device_config | `APV0 下发配置: <完整原文>` |
| Trigger | client_action | `客户端发起请求: <完整原文>` |
| Verify | capture_verify | `断言应出现: <完整原文>` |
| Verify | device_query | `APV_0 执行 <命令>` |

**关键：原文是 CLI 命令时要完整显示**，如 `sdns host persistence 10 "www.zyq.com" "24" 64 "A"`，一个字不能少。


## D 列与步骤对应规则

**D 列必须准确描述该步的动作，不能张冠李戴。**

常见问题：case 描述（如"配置A类型的会话保持，使用ipv4访问"）覆盖了"配置 + 访问"两个动作，但第一步实际只做了配置。应拆为两步，各自用各自的 describe：

| C | Phase | Type | D | G |
|---|-------|------|---|----|
| 2 | Setup | device_config | `APV0 下发配置: sdns host persistence 10...` | `sdns host persistence...` |
| 3 | Trigger | client_action | `客户端发起DNS请求: 连续使用客户端ipv4请求...` | `dig @...` |

检查方法：每个 step 的 D 列文本应能从该 step 自身的 describe/hint 中找到对应关键词。如果 D 列描述的动作在 G 列找不到对应，说明 D 列用错了。
