# Leader 调研：nettest/网络测试自动化领域可借鉴项目对照

> 2026-07-18，leader 亲研（用户令：探索外部可参考项目，尤其专利方向类似的 nettest 相关，加速开发）。
> 方法：web 检索五轮（学术/IETF/工业框架/专利面），对照本项目五组件逐条映射「可借鉴→省什么」。
> 检索为 US-only，中文专利库（CNIPA）未覆盖——用户手上若有具体 nettest 专利号/关键词可给我深挖。

## 一、最强对照：NeTestLLM（多 agent LLM 网络协议测试，生产部署级）

来源：arXiv 2510.13248《Automated Network Protocol Testing with LLM Agents》+ ACM ANRW 2025；
已在生产环境部署数月、商用网络设备案例验证。

| NeTestLLM 组件 | 本项目对应 | 对照结论 |
|---|---|---|
| 分层协议理解（hierarchical RFC understanding，低层建模抽 testing points） | KMS 手册 markdown + 脑图编译 prep | 同构；它从 RFC 抽测试点，我们从脑图+手册。**可借鉴：低层建模（协议字段/FSM 迁移点枚举）作为覆盖度维度** |
| 迭代生成+覆盖评估（breadth/depth 两维评价再补生成） | worker 单案自由编写（无批级覆盖评估） | **它有我们无**：批级覆盖两维评估器。可借鉴为「脑图测试点 → 卷面覆盖对账」的机械审计（我们只有单案 lint，无批级覆盖度量） |
| 可执行产物生成（NL→可执行代码，retrieval-enhanced） | compile_* 工具链 → case.xlsx | 同构；它检索增强翻译，我们判例/footprint 检索。等价 |
| **运行时反馈分析：fault corrector 把错误分类（语法/配置/不支持命令）+ 检索历史修复提案** | compile_attribute（G(^) 语法拒绝/文件级崩溃/undetermined 交 LLM）+ 判例店 + frozen 换法 | **高度同构**——错误分类学几乎一样（语法拒绝=我们的 G(^)；不支持命令=我们的 command_existence 欠定）。互相印证架构方向对。它的「历史修复检索→提案」= 我们判例 adopt 的同类物 |
| 测试用例 JSON 结构（title/objective/steps/expected/reference/topology） | 脑图案 → steps 数组 → xlsx 行 | 同构 |
| 成绩：OSPF/RIP/BGP 生成 4632 用例、覆盖 41 个 FRRouting 历史 bug（国标方法仅 11）、产物生成效率 8.65× 人工 | 四脑图 ~139 案、缺陷候选单、25/26 交付 | 它的评价口径（历史 bug 覆盖数、对比国标/人工基线）**可直接借用为我们的准入报告口径** |

**加速点（NeTestLLM→我们）**：
1. **批级覆盖评估器**：per-脑图「测试点抽取→卷面覆盖对账」机械审计（防漏编而非只防错编）——我们现在没有这层。
2. **准入报告口径**：用「历史缺陷覆盖数 vs 基线」讲价值（对用户汇报和专利叙事都更硬）。
3. 其错误分类学与我们归因层一致——**方向自信**，不必重设计。

## 二、IETF 标准化动向（同一学术团队在 NMRG 推标准，三份草案）

1. **draft-cui-nmrg-auto-test-00**《Framework and Automation Levels for AI-Assisted Network Protocol Testing》（2025-07）：
   定义 AI 辅助协议测试框架（协议理解/用例生成/脚本与配置合成/反馈迭代——与 V8 拓扑同构）+
   **L0（全手工）→L5（全自主自适应）自动化成熟度分级**。
   **可直接借用**：我们的「4 脑图准入判据」和向用户汇报的阶段语言可以对齐 L0-L5 分级——
   当前本项目≈L3-L4（人机协同：欠定问询+批级放行），准入目标可表述为「特定域 L4」。
   对专利叙事同样有用：标准化语言是权利要求的参照系。
2. **draft-cui-nmrg-llm-nm-01**《LLM Agent-Assisted Network Management with Human-in-the-Loop》：
   human-in-the-loop 框架——与我们 ask 面板/裁决链同构，可引用其术语规范化我们的交互设计文档。
3. **draft-cui-nmrg-llm-benchmark-02**《Evaluate LLM Agents for Network Configuration》：
   LLM 网络配置评测框架——收口批后若做模型换档评测（IST_MODEL A/B），可参照其维度。

## 三、执行/断言层成熟框架（上机验证层可借鉴）

1. **pyATS/Genie（Cisco）**：网络测试事实标准。分层=核心框架（拓扑/设备抽象）+Genie（**show 命令输出→结构化数据 parser 库**）+业务层；AEtest 提供 CommonSetup/Testcases/CommonCleanup 结构。
   **可借鉴**：Genie 的「parser 先结构化、断言打在结构化字段上」路线 vs 我们「found/not_found 正则窗口打在原始回显」——
   我们的恒真断言族问题（^锚/窗口命中命令原文）在 parser 路线下结构性不存在。
   **但**：Genie parser 库是 Cisco 生态（数千个 show parser 人工积累），我们的 sdns/APV 设备无现成 parser——
   全面切换不现实；**可取中间态**：对高频命令（show statistics 类）让 footprint 判例层沉淀「字段抽取正则」，
   等效于自建微型 parser 库（纯数据层扩展，符合自愈合四层架构，零代码）。
2. **ANTA（Arista）**：YAML 声明式测试目录（catalog）+ AntaTest 抽象类 + **pydantic 输入校验** + 每测试强制配 pytest。
   **可借鉴**：test catalog 声明式组织（我们 xlsx 即等价物，无需改）；
   「每个测试类强制带单测」纪律与我们宪法级守门测试一致（互证）。
3. **nuts（pytest 插件）/Robot Framework**：关键字驱动网络测试——与我们 xlsx F 列方法体系同构，无新增可借鉴。

## 四、专利面（诚实边界）

- 未检索到与「**脑图→测试用例编译→上机断言真覆盖**」直接同构的已授权专利（US 检索面）；
  最接近的公开物是 NeTestLLM（论文，2025-10 公开）与 USPTO 7010782（2006，CLI/SNMP 交互式测试 GUI，年代久、无 LLM）。
- **潜在差异化点**（若用户走专利方向，这些是本项目相对 NeTestLLM 公开物的可主张差异）：
  ①脑图（人工用例意图）为输入源（NeTestLLM 从 RFC 出发）；②断言真覆盖机械门族（恒真/恒假必崩门、
  crash-gate、found→abs_found 等——对「假验证」的形式化防护）；③事件溯源事实流+效力投影的可审计裁决链
  （压盖律/凭证门）；④判例 shape-aware 采信+quarantine 的知识治理。
- 「nettest」具体前作我未能定位（US-only 检索限制+关键词过泛）——**用户给专利号/申请人/中文关键词，我可定向深挖对照**。

## 五、加速建议汇总（按性价比排序）

| # | 借鉴 | 落点 | 成本/收益 |
|---|---|---|---|
| 1 | L0-L5 自动化分级语言（IETF draft） | 准入报告+#24 六裁决方案的阶段表述 | 零代码；汇报/专利叙事立即可用 |
| 2 | 批级覆盖评估器（NeTestLLM breadth/depth） | 新机械审计：脑图测试点→卷面覆盖对账 | 中等（一个 compile_* 工具）；堵「漏编」盲区 |
| 3 | 历史缺陷覆盖数作准入口径（NeTestLLM 评价法） | 准入报告：本引擎卷面覆盖的历史 bug 数 vs 人工卷基线 | 低（kb_bug_search 已有数据源） |
| 4 | footprint 沉淀字段抽取正则（Genie parser 思路的数据层微型化） | 判例层新增条目类型，零代码 | 低；渐进消解正则窗口断言的脆弱面 |
| 5 | IETF human-in-the-loop 术语对齐 | 交互设计文档术语规范 | 零代码；文档级 |

**Sources**:
- [Automated Network Protocol Testing with LLM Agents (arXiv 2510.13248)](https://arxiv.org/abs/2510.13248)
- [LLM Driven Automated Network Protocol Testing (ACM ANRW 2025)](https://dl.acm.org/doi/10.1145/3744200.3744763)
- [draft-cui-nmrg-auto-test (IETF)](https://datatracker.ietf.org/doc/draft-cui-nmrg-auto-test/)
- [draft-cui-nmrg-llm-nm (IETF)](https://datatracker.ietf.org/doc/draft-cui-nmrg-llm-nm/)
- [draft-cui-nmrg-llm-benchmark (IETF)](https://datatracker.ietf.org/doc/draft-cui-nmrg-llm-benchmark/)
- [Cisco pyATS](https://developer.cisco.com/docs/pyats/)
- [ANTA - Arista Network Test Automation](https://anta.arista.com/)
- [USPTO 7010782 (2006 CLI/SNMP 测试 GUI)](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/7010782)
