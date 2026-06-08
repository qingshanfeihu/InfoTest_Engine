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

# 1.5 结构自检（必须执行，见下方规则）

# 1.6 语义梳理（必须执行，见下方规则）

# 2. 拆分
qa_decompose_test_cases(extracted_json_path="workspace/inputs/yzg/<name>_extracted.json")
# 返回的 JSON 存为 <name>_decomposed.json

# 3. 生成 xlsx
qa_generate_test_case_xlsx(decomposed_json_path="workspace/outputs/yzg/<name>_decomposed.json")
# 返回的 xlsx 路径保存到 workspace/outputs/<name>/

# 4. 填充 G 列（直接调用 g-column-filler fork skill）
qa_invoke_skill(skill="g-column-filler", brief="对 workspace/outputs/<name>/ 下所有 xlsx 文件填充 G 列。decomposed JSON 路径: workspace/outputs/yzg/<name>_decomposed.json")
```

**关键：`<name>` 必须替换为实际人名**（如 `0001`、`yzg`、`dongkl`），否则输出文件名前缀不对。

**禁止中途停止：step 3 生成 xlsx 后，必须继续调用 step 4 的 `qa_invoke_skill` 填充 G 列。
仅当 step 4 返回成功后，流水线才算完成。**


## Step 1.5 结构自检规则

Step 1 提取完成后，**必须**用 `qa_deepagent_read_file` 读取原始脑图 `.txt`，对照 extracted JSON
的 `steps`/`expected` 分配是否正确。规则由叶子上推：

### 规则

1. **最后一个叶子 → 检查点（expected）**
2. **非末位叶子 → 步骤（steps）**
3. **case 标题（P2 节点文本）→ 用例描述，不是步骤**
4. **有孙节点的子节点 → 默认是步骤（孙节点是检查点），但需判断**：
   - 如果内容是可执行的 CLI 命令或操作描述 → **步骤**
   - 如果内容是标题/分块名称（如"正常场景""异常场景"）→ **描述**，不是步骤。其子节点才是真正的步骤

### 修正方法

发现分类错误时，直接编辑 extracted JSON 的 `steps` 和 `expected` 列表：
- 误归为步骤的检查点 → 移到 `expected`
- 误归为检查点的步骤 → 移到 `steps`
- 误归为步骤的描述标题 → 移到 `description` 或删除，其子节点内容不变
- 缺少预期的步骤 → 补充 `step_expected` 映射


## Step 1.6 语义梳理（结构自检后、分解前必须执行）

结构修正后，**必须**通读 extracted JSON 中每个用例，对照原始脑图 `.txt`，从语义层面判断
用例完整性并补全。不要依赖关键词匹配，而是理解用例意图后做判断。

### 检查项

**1. 残缺用例 — 只有配置缺少验证**

steps 只有 1-2 条配置命令，但 expected 描述了行为验证（如"保持不变"/"一致"/
"维持"/"不变"/"相同"/"不发生"/"始终"/"跳变"/"切换"/"轮询"），说明只拆出了配置步骤，
缺少客户端运行时验证步骤。

→ 在 `steps` 中补充客户端操作步骤（dig/ping/curl/发包/多次查询），
  在 `expected` 中补充对应的断言（如"两次查询返回相同IP"）。

**2. 缺失断言 — expected 存在但不会被转为 check_point**

expected 非空，但内容是比较/趋势/持续性的描述（如"service ip 保持不变"、"配置不丢失"），
而非明确的正负向断言（成功/失败/显示/报错）。这类 expected 在分解阶段会被丢弃。

→ 将 expected 改写为可验证的断言形式：
  - "XX 保持不变" → "多次操作后 XX 结果一致" + "XX 值始终为 <具体值>"
  - "XX 不丢失" → "重启后 show XX 仍包含 <配置项>"
  - "正常转发" → "抓包/TCPdump 中包含转发数据"

**3. 隐含前置 — step 引用未创建的资源**

step 中提到 pool/service/host/zone/rule 等资源名称，但 steps 和 `case_prerequisites`
中都没有对应的创建步骤。

→ 在 `case_prerequisites` 中补充资源创建步骤（如 "sdns pool name <name>"、
  "sdns service ip <name> <ip>"）。

**4. 步骤粒度 — 多动作合并在一条 step 中**

一条 step 同时包含"配置"和"客户端验证"两个动作（如 "开启会话保持，使用客户端dig查看"），
应拆为独立步骤。

→ 拆分为配置步骤 + 客户端验证步骤，各自写入 `steps` 列表。

### 操作方法

直接编辑 extracted JSON 文件修改 `steps` / `expected` / `case_prerequisites` 字段，
补全后再调 `qa_decompose_test_cases`。


## 描述格式（如果工具生成的描述不对，手动修正）

D 列描述规则：**原文完整保留，不截断**。

| actor | 描述格式 |
|-------|---------|
| APV_0/APV_1 | `APV0 下发配置: <完整原文>` |
| test_env | `客户端发起请求: <完整原文>` |
| check_point + found | `断言应出现: <完整原文>` |
| check_point + not_found | `断言不应出现: <完整原文>` |

**关键：原文是 CLI 命令时要完整显示**，如 `sdns host persistence 10 "www.zyq.com" "24" 64 "A"`，一个字不能少。

## check_point 前验证步骤注入规则

在断言（found/not_found）之前，必须注入验证步骤确认变更生效：

- **设备检查点**（APV_0/APV_1 的配置变更验证）→ 注入 `show` 命令步骤
- **客户端检查点**（dig/ping/curl/发包/打流量 的响应验证）→ 客户端动作本身就是验证，不需要额外注入

判断方式：看 check_point 前面最近的步骤是什么 actor：
- 前面是 APV_0/APV_1 的 cmd_config/cmds_config → 注入 show（从 hint 推断对应的 show 命令）
- 前面是 test_env 的 routera/clientc → 不注入（客户端已执行验证动作）

检查方法：每个 check_point 行之前，如果缺少对应的 show 步骤，需手动补上。

**关键：原文是 CLI 命令时要完整显示**，如 `sdns host persistence 10 "www.zyq.com" "24" 64 "A"`，一个字不能少。

## D 列与步骤对应规则

**D 列必须准确描述该步的动作，不能张冠李戴。**

常见问题：case 描述（如"配置A类型的会话保持，使用ipv4访问"）覆盖了"配置 + 访问"两个动作，但第一步实际只做了配置。应拆为两步，各自用各自的 describe：

| C | D | G |
|---|----|----|
| 2 | `APV0 下发配置: sdns host persistence 10...` | `sdns host persistence...` |
| 3 | `客户端发起DNS请求: 连续使用客户端ipv4请求...` | `dig @...` |

检查方法：每个 step 的 D 列文本应能从该 step 自身的 describe/hint 中找到对应关键词。如果 D 列描述的动作在 G 列找不到对应，说明 D 列用错了。
