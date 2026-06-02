---
name: decompose-test-cases
description: 拆分用例+生成xlsx。TRIGGER: 拆分用例, decompose, 完整拆分, 流水线
allowed-tools: qa_fetch_test_cases qa_extract_test_cases qa_decompose_test_cases qa_inject_init_and_deps qa_fill_g_column qa_deepagent_write_file qa_deepagent_read_file
---

依次调用工具，不要手写 JSON：

```
# 0. （可选）从 Agile 平台拉取
qa_fetch_test_cases(case_id=<id>)
# 返回的 .txt 路径自动保存到 workspace/inputs/yzg/

# 1. 提取
qa_extract_test_cases(file_path="workspace/inputs/yzg/<name>.txt")
# 返回的 JSON 存为 <name>_extracted.json

# 1.5 结构自检（必须执行，见下方规则）

# 2. 拆分
qa_decompose_test_cases(extracted_json_path="workspace/inputs/yzg/<name>_extracted.json")
# 返回的 JSON 存为 <name>_decomposed.json

# 3. 注入
qa_inject_init_and_deps(decomposed_json_path="workspace/inputs/yzg/<name>_decomposed.json")

# 4. 生成 xlsx（必须指定路径）
qa_fill_g_column(decomposed_json_path="workspace/inputs/yzg/<name>_decomposed.json")
```

**关键：`<name>` 必须替换为实际人名**（如 `0001`、`yzg`、`dongkl`），否则输出文件名前缀不对。


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
