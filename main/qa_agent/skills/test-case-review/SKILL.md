---
name: test-case-review
description: 评审测试用例文件（xlsx / markdown / Test List），对照产品缺陷/需求和历史测试策略审视用例覆盖与缺口。TRIGGER when 用户输入包含"评审"、"测试用例评审"、"review test cases"、"按之前评审要求"、"测试用例文件"、"Test List"、"BUG-数字"、"xlsx 评审"，或用户提供 knowledge/data/markdown/qa/ 下的 .md 文件并要求检查覆盖、缺口、测试质量。SKIP when 用户只问 CLI 用法、产品规格说明、缺陷详情查询，或要求生成新用例（不评审现有用例）。
allowed-tools: qa_deepagent_read_file qa_deepagent_grep qa_deepagent_ls qa_exec qa_bash web_bug_search qa_sanity_check qa_ask_user
---

# 测试用例评审 Skill

你正在评审一份测试用例。使用 task 工具调用 explore 子代理收集证据，然后基于证据写评审报告。

## 评审标准（P0-P7）
- P0：覆盖所有功能细节 + 非常丰富的兼容性/负面/压力用例 + corner case
- P1：覆盖所有功能细节 + 丰富的兼容性/负面/压力用例
- P2：覆盖所有功能细节 + 比较丰富的兼容性/负面/压力用例
- P3：覆盖所有功能细节 + 一定的兼容性/负面/压力用例
- P4：覆盖所有功能细节 + 一定的负面/压力用例
- P5：覆盖所有功能 + 一定的负面/压力用例
- P6：覆盖基本功能 + 包含负面和压力类型
- P7：无法覆盖基本功能，不包含负面和压力类型

## 两条核心提醒
1. **关注研发修改内容和具体产品实现**——逐项理解修改了什么参数、行为、选项
2. **参考以往测试用例和测试策略**——看类似功能历史上关注过什么维度

## 证据收集（依次调用 6 次 task）

必须严格按顺序调用 6 次 task(subagent_type="explore", description="...")。
每次 explore 返回后确认收到证据再调下一步。**不可跳步、不可合并、不可省略。**
如果某步 explore 返回"未找到"，仍然继续下一步。

### Step 1：读缺陷/需求

```
task(subagent_type="explore", description="
任务：查找缺陷/需求 {ticket_id} 的完整信息。

操作：
1. 调用 web_bug_search(ticket_id='{ticket_id}') 获取完整缺陷描述
2. 如果返回的信息中有'关联 bug'或'相关需求'，记录下来

必须返回：
- 缺陷/需求标题
- 研发修改方案（具体修改了什么 CLI 命令、新增了哪些参数/枚举值）
- 影响版本和功能模块
- 关联的其他 bug/需求 ID
- 严重度

格式：用 Markdown 列表，每项一行。
")
```

### Step 2：读产品设计文档

```
task(subagent_type="explore", description="
任务：在产品文档中查找 {功能关键词} 的设计细节。

操作：
1. grep knowledge/data/markdown/product/ 搜索 '{关键词1}|{关键词2}'，output_mode='files_with_matches'
2. 对命中的文件，用 grep output_mode='content' context=5 获取上下文
3. 如果内容不够，用 read_file 读取关键段落（限制 200 行）

必须返回：
- 功能在系统中的位置和模块层级
- 上下游耦合关系（与哪些其他功能交互）
- 设计边界（哪些是核心功能，哪些是边缘/兼容选项）
- 影响的网络层级（HTTP 版本、IPv4/IPv6、SSL 等）
- 处理流程（请求侧/响应侧分别做什么）

格式：按'来源文件 + 行号 + 内容摘录'组织。
")
```

### Step 3：读 CLI 手册

```
task(subagent_type="explore", description="
任务：在 CLI 手册中查找 {命令名} 的完整参数定义。

操作：
1. grep knowledge/data/markdown/product/cli__part*.md 搜索 '{命令名}'，output_mode='content' context=10
2. 找到命令定义后，read_file 读取完整的命令段落（通常 20-50 行）
3. 如果有相关的 no/show/clear 命令，也一并查找

必须返回：
- 命令完整语法（包括所有可选参数）
- 每个参数的合法值范围和默认值
- 参数之间的依赖关系（互斥、包含、条件必填）
- 相关的 no/show/clear 命令语法
- 配置示例（如果文档中有）

格式：按命令分组，每个命令列出完整参数表。
")
```

### Step 4：读测试方法论

```
task(subagent_type="explore", description="
任务：查找与 {功能关键词} 相关的测试策略文档。

操作：
1. grep knowledge/data/markdown/qa/ 搜索 'Test Strategy'，output_mode='files_with_matches'
2. 对找到的 Test Strategy 文件，grep '{功能关键词}|{相关协议}' 确认相关性
3. 对相关的策略文件，read_file 读取关键段落（测试目标、覆盖范围、测试方法）

必须返回：
- 相关测试策略文件名和路径
- 该策略要求覆盖的测试维度（如 HTTP 版本、IPv6、性能、安全等）
- 测试重点和方法论（边界值分析、等价类划分、错误推测法等）
- 明确要求的测试场景（如'empty cookie, abnormal cookie, very long cookie'）

如果没找到直接相关的策略，返回最接近的策略文件及其覆盖维度。
格式：按策略文件分组。
")
```

### Step 5：读同类历史用例

```
task(subagent_type="explore", description="
任务：查找与 {功能关键词} 同功能族的历史测试用例作为基线参考。

操作：
1. grep knowledge/data/markdown/qa/ 搜索 '{功能族关键词}'，output_mode='files_with_matches'
2. 排除当前正在评审的文件本身（{当前用例文件名}）
3. 对找到的历史用例，read_file 读取前 100 行了解其结构和覆盖模式
4. 重点关注：模块划分方式、测试维度、用例数量级

必须返回：
- 找到的历史用例文件名和路径
- 该用例的模块划分（CLI/WebUI/Function/Integration/Stress 等）
- 覆盖的测试维度（正向/负向/边界/兼容性/性能）
- 用例数量和质量水平
- 可作为对标参考的设计模式

如果没找到同功能族用例，搜索同协议层（如 HTTP/SLB）的用例作为参考。
格式：按文件分组，每个文件列出结构概览。
")
```

### Step 6：全文读当前用例 + 自检

```
task(subagent_type="explore", description="
任务：全文读取当前用例文件并执行字面自检。

操作：
1. read_file('{用例文件路径}', limit=200, offset=0) 读取第一部分
2. 继续分页读取直到文件结束（每次 200 行）
3. 如果用例中出现不认识的命令或功能模块，用 grep knowledge/data/markdown/product/cli__part*.md 确认其作用
4. 最后调用 qa_sanity_check(target_file='{用例文件路径}', bug_severity='{严重度}') 做字面自检

必须返回：
- 用例总行数和有效用例条数
- 模块构成（CLI/WebUI/Function/Integration/Stress 各多少条）
- 覆盖的功能点清单（按模块列出）
- 覆盖的参数组合和测试类型（Positive/Negative/Boundary/Configuration）
- qa_sanity_check 的完整结果（问题数量和分类）
- 发现的明显问题（如重复段落、错字、格式不一致）

格式：先给结构概览表格，再列 sanity_check 结果。
")
```

## 补充调研

如果 explore 返回的证据不够充分，你可以直接使用 grep/read_file 等工具自行补充调研。
Explore 是推荐路径，不是唯一路径。

## 评审输出（四段式）

收集完 6 步证据后，直接写最终报告（**不再调任何工具，避免 TUI 截断**）：

### ✅ 执行校验清单
*(打印 Step 1-6 的打钩状态)*

### 一、读取到的证据
按 Step 1-6 简述每步的关键发现

### 二、基于证据的评级
判断用例是 P0-P7 中的哪个级别，给出详细理由

### 三、证据缺口
知识库里没找到但可能影响判断的信息

### 四、建议修改汇总
按严重程度分级，每条给出具体位置和修改方向

## 参考资料
`reference/` 目录是可选参考，按需读取。
