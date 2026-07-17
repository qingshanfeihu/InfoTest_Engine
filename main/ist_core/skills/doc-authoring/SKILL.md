---
name: doc-authoring
description: Generates a technical document (configuration guide / operation manual / solution doc) for the APV load-balancer product grounded in the knowledge base, and saves it as a WeCom cloud document. Every CLI command and parameter must trace to a knowledge-base source — knowledge-driven authoring, not free-form writing.
context: fork
agent: document-author
user-invocable: true
when_to_use: |
  Use when 用户要求"写一个文档"、"创建文档"、"写配置指南"、"操作手册"、
  "输出方案文档"、"写一个xxx的文档"、"生成xxx文档"、"企微云文档"。
  Trigger keywords: 写文档, 创建文档, 配置指南, 操作手册, 方案文档, 写一个, 企微文档, 云文档
  SKIP when: 用户要求生成测试报告（用 report-gen）、只是普通问答、没有明确创建意图。
effort: medium
---

# Doc Authoring

Generate a technical document grounded in the knowledge base and save it as a WeCom cloud
document. This skill is **knowledge-driven authoring**, not free-form content creation.

## Knowledge Source Policy (core rule)

Before generating any technical document, **run knowledge retrieval first**. Every piece of
technical content must have a source.

**Source priority**:
1. CLI manual / official technical docs (`cli_*.md` / `app_*.md` under `knowledge/data/markdown/product/`)
2. Project knowledge base (all of `knowledge/data/markdown/`)
3. Verified configuration precedents (`knowledge/footprints/` / historical precedents)
4. Existing WeCom documents (search via `wx_search_doc`)

**Forbidden**:
- Generating device configuration from LLM parameter memory alone
- Guessing CLI commands from experience
- Filling in device parameters that do not exist
- Fabricating commands that never appear in the knowledge base

## CLI Safety Rules (red line)

If the document involves device configuration, CLI commands, parameter descriptions, show
commands, or verification commands, **every command must trace to a knowledge-base source**.

**Source found**: quote it directly and annotate 「来源：{文件名}」.

**No source found**: output explicitly:

> ⚠️ 该命令未在知识库中确认，请人工核对设备手册后补充。

**Never emit fabricated commands in these shapes**:
- Unconfirmed `xxx config` / `xxx enable` / `xxx set`
- Guessed parameter names or values
- Assumed show-command output formats

## Workflow

### Step 1: Understand the document topic

Analyze the request; determine the feature scope and target device the document covers.

### Step 2: Knowledge retrieval (mandatory, never skip)

Search the knowledge base by topic keywords. For example, for an "HTTP SLB configuration
guide" request, grep `knowledge/data/markdown/` for the feature's object words (virtual
server / real server / health check / service group …) and read the matched files.

Read the relevant sections of matched files with `fs_read`.

If `wx_search_doc` is available, search existing WeCom documents for reference.

**Record the source file path for every retrieval result.**

### Step 3: Organize the retrieved material

Classify into:
- **CLI commands**: full syntax and parameter description, source file annotated
- **Configuration flow**: step order extracted from the manual
- **Feature description**: concept text from the manual
- **Verification method**: show commands and expected output from the manual

### Step 4: Generate the Markdown

Organize content per the default template below. Annotate the source after every CLI command.

### Step 5: Content self-check

After generating, verify:
- [ ] Does every CLI command have a knowledge-base source?
- [ ] Did every parameter name and value appear in the manual?
- [ ] Is the configuration flow complete (from creation to verification)?
- [ ] Any fabricated command or parameter?

Content that fails the check is replaced with a 「⚠️ 待确认」 note.

### Step 6: Create the WeCom cloud document

Call `wx_create_doc(title=<标题>, content=<完整Markdown>, topic=<主题标识>)`.

topic format: `doc-{关键词}-{YYYY-MM-DD}`.

Return the document link.

## Default template for configuration documents (deliverable content — keep in Chinese)

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

## Failure handling

**Insufficient knowledge**: do not generate a full configuration document. Tell the user explicitly:

> 当前知识库没有找到 {模块名} 的配置资料，无法生成可靠文档。请提供 CLI 手册或相关技术资料后再试。

**Partially insufficient**: generate the confirmed parts normally; annotate the unconfirmed
parts with 「⚠️ 待确认：知识库中未找到相关资料，建议查阅设备手册」.

## General rules

- Markdown total length ≤ 50000 characters
- Complete in one pass; do not call invoke_skill
- Return the document link after successful creation
