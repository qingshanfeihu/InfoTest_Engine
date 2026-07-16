---
name: doc-authoring
description: 基于知识库生成技术文档，保存为企业微信云文档
context: fork
agent: document-author
user-invocable: true
when_to_use: |
  Use when 用户要求"写一个文档"、"创建文档"、"写配置指南"、"操作手册"、
  "输出方案文档"、"写一个xxx的文档"、"生成xxx文档"、"企微云文档"。
  Trigger phrases: 写文档, 创建文档, 配置指南, 操作手册, 方案文档, 写一个, 企微文档, 云文档
  SKIP when: 用户要求生成测试报告（用 report-gen）、只是普通问答、没有明确创建意图。
effort: medium
---

# Doc Authoring

基于知识库生成技术文档并保存为企业微信云文档。本 skill 是「知识库驱动的文档生成」，不是自由内容创作。

## Knowledge Source Policy（核心规则）

生成技术文档前，**必须先执行知识检索**。文档中的技术内容必须有来源。

**知识来源优先级**：
1. CLI 手册 / 官方技术文档（`knowledge/data/markdown/product/` 下的 cli_*.md / app_*.md）
2. 项目知识库（`knowledge/data/markdown/` 全目录）
3. 已验证配置案例（`knowledge/footprints/` / 历史先例）
4. 历史企微文档（`wx_search_doc` 搜索已有文档）

**禁止**：
- 仅依靠 LLM 参数记忆生成设备配置
- 根据经验猜测 CLI 命令
- 补全不存在的设备参数
- 编造未在知识库中出现的命令

## CLI Safety Rules（红线）

如果文档涉及设备配置、CLI 命令、参数说明、show 命令、验证命令，**每条命令必须能追溯到知识库来源**。

**如果找到来源**：直接引用，标注「来源：{文件名}」。

**如果没有找到来源**：必须明确输出：

> ⚠️ 该命令未在知识库中确认，请人工核对设备手册后补充。

**禁止生成以下格式的虚构命令**：
- 未经确认的 `xxx config` / `xxx enable` / `xxx set`
- 猜测的参数名或参数值
- 假设的 show 命令输出格式

## 执行流程

### Step 1: 理解文档主题

分析用户需求，确定文档覆盖的功能范围和目标设备。

### Step 2: 知识检索（必须执行，不可跳过）

按主题关键词搜索知识库。例如用户要求「HTTP SLB 配置文档」：

```
fs_grep("slb", path="knowledge/data/markdown/")
fs_grep("virtual.server", path="knowledge/data/markdown/")
fs_grep("real.server", path="knowledge/data/markdown/")
fs_grep("health.check", path="knowledge/data/markdown/")
fs_grep("service.group", path="knowledge/data/markdown/")
fs_grep("load.balan", path="knowledge/data/markdown/")
```

用 `fs_read` 读取匹配文件的相关章节。

如果 `wx_search_doc` 可用，搜索已有企微文档获取参考。

**记录每个检索结果的来源文件路径**。

### Step 3: 整理检索结果

分类整理：
- **CLI 命令**：带完整语法和参数说明，标注来源文件
- **配置流程**：从手册中提取的步骤顺序
- **功能说明**：手册中的概念描述
- **验证方法**：手册中的 show 命令和预期输出

### Step 4: 生成 Markdown

按默认模板组织内容（见下方）。每条 CLI 命令后标注来源。

### Step 5: 内容检查

生成后自查：
- [ ] 每条 CLI 命令是否有知识库来源？
- [ ] 参数名和参数值是否在手册中出现过？
- [ ] 配置流程是否完整（从创建到验证）？
- [ ] 是否有虚构的命令或参数？

未通过检查的内容，替换为「⚠️ 待确认」提示。

### Step 6: 创建企微云文档

调用 `wx_create_doc(title=标题, content=完整Markdown, topic=主题标识)`。

topic 格式：`doc-{关键词}-{YYYY-MM-DD}`。

返回文档链接。

## 技术配置类文档默认模板

```
# {功能名称} 配置指南

## 功能说明
{功能用途、适用场景}

## 配置前准备
- 环境要求（软件版本、License）
- 网络条件（接口、IP、路由）
- 依赖模块（需要先启用的功能）

## 配置步骤

### Step 1: {步骤名称}
**目的**：{这一步做什么}
**命令**：
\`\`\`
{CLI 命令}
\`\`\`
**说明**：{参数含义}
**来源**：{知识库文件路径}

### Step 2: ...

## 验证方法
{show 命令 / 流量测试 / 日志检查}

## 注意事项
{已知限制、风险提示、最佳实践}
```

## 失败处理

**知识不足时**：不要生成完整配置文档。明确告知用户：

> 当前知识库没有找到 {模块名} 的配置资料，无法生成可靠文档。请提供 CLI 手册或相关技术资料后再试。

**部分知识不足时**：已确认的部分正常生成，未确认的部分标注「⚠️ 待确认：知识库中未找到相关资料，建议查阅设备手册」。

## 通用规则

- Markdown 总长度不超过 50000 字符
- 一次性完成，不调用 invoke_skill
- 创建成功后返回文档链接
