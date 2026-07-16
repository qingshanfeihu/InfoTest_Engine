# Team2 · Skill 规范审计(对标 Anthropic Agent Skills + 负载均衡产品自动化测试域)

> 任务(用户 #5):检查所有 skill 是否符合 Claude 官方 skill 设计规范,且作为**负载均衡产品自动化测试**的规范描述。逐 skill×逐项打分。
> 基准:platform.claude.com Agent Skills best-practices + 本项目 CLAUDE.md「资产封装标准」「skill/agent prompt 编写红线」+ 既有审计 `docs/AUDIT_skill_standard_alignment.md`(2026-07-04)。
> 写权限:`main/ist_core/skills/**`、`main/ist_core/agents/*.md`。红线:通过率不降;承重锚点保真;语言分层;零写死设备命令;frontmatter 契约不破。
> 图例:✓ 合规 · ✗ 违规(修复) · △ 可接受(轻微/有理由不改) · N.A. 不适用。

## 门测试基线(修复前)

`pytest test_skill_package_standard.py test_prompt_structure.py` → **21 passed**(9 + 12)。全部 frontmatter/name/description/context/body≤500/引用一层深/agent 骨架均已绿。本次审计在此基线上只做**低风险增益**,不触碰任何被测试断言的锚点句。

---

## 一、SKILL.md × checklist 矩阵(12 skills × 10 项)

列:C1 描述含领域术语 · C2 描述含功能+何时用 · C3 正文≤500 · C4 额外详情单独文件 · C5 无时效性信息 · C6 术语一致 · C7 示例具体 · C8 引用一层深 · C9 渐进披露 · C10 工作流清晰

| skill(行数) | C1 | C2 | C3 | C4 | C5 | C6 | C7 | C8 | C9 | C10 |
|---|---|---|---|---|---|---|---|---|---|---|
| **test-list-review** (193) | ✓* | ✓ | ✓ | △ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **ist-compile-engine** (52) | ✓* | ✓ | ✓ | ✓✓ | △ | ✓ | ✓ | ✓ | ✓✓ | ✓ |
| **ist-verify** (144) | ✓* | ✓ | ✓ | △ | △ | ✓ | ✓ | ✓ | ✓ | ✓✓ |
| **device-verify** (188) | ✓ | ✓ | ✓ | ✓ | △ | ✓ | ✓ | ✓ | ✓ | ✓✓ |
| **config-answer** (51) | ✓ | △ | ✓ | N.A. | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **config-automation** (95→64) | ✗→✓ | ✓ | ✓ | ✗→✓ | ✗→✓ | ✗→✓ | ✓ | ✓ | △→✓ | ✓ |
| **escalate-when-stuck** (39) | △ | ✓ | ✓ | N.A. | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **compile-worker** (46, fork) | △ | ✓ | ✓ | N.A. | △ | ✓ | ✓✓ | ✓ | ✓ | ✓ |
| **compile-attributor** (8, fork) | △ | ✓ | ✓ | N.A. | ✓ | ✓ | N.A. | ✓ | ✓ | N.A. |
| **config-answer-draft** (17, fork) | ✓ | ✓ | ✓ | N.A. | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **config-answer-verifier** (21, fork) | ✓ | ✓ | ✓ | N.A. | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **review-verifier** (23, fork) | △ | ✓ | ✓ | N.A. | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

`*` = 本次修复后达标(见修复清单);`✗→` = 修复前后。

### 逐项理由(仅记 ✗/△/N.A. 与关键 ✓)

**C1 描述含领域关键术语(SDNS/SLB/APV/负载均衡)** — 任务第二目标「负载均衡产品自动化测试规范描述」的核心项。
- 修复前:test-list-review / ist-compile-engine / ist-verify 三个**用户可调入口** skill 的 description 只写「test cases / compile / case.xlsx」,无一处 SLB/SDNS/APV/负载均衡领域锚——在 per-turn listing 里与通用测试工具无从区分。**已修**:三者 description 前置 `APV load-balancer (SLB / SDNS …)` 锚(见修复清单 §1)。
- config-automation description 原为泛化「network configuration」→ 已加 SLB/SDNS 锚。
- device-verify / config-answer / config-answer-draft / config-answer-verifier:description 已含 `APV`,✓。
- △(fork skill,不进 listing,领域锚增益低,不改):compile-worker / compile-attributor / review-verifier 由编排器**按名**派发而非 listing 选中,description 域锚对选择无影响;强改需同步改 agents/*.md frontmatter 双份、churn 高收益低,记录不改。escalate-when-stuck 是领域中立的诚实上报出口(锚在「compile task」),同理不改。

**C2 描述含功能+何时用**
- △ config-answer:description「must be answered from the CLI manual, never from memory」是**祈使规则**而非第三人称「what+when」描述形态(官方建议 description 陈述能力+触发)。when_to_use 已补齐触发,功能可读,故仅轻微不达形态。记录,低优先(改动会动到 `[未在文档直接命中]` 邻近语义,收益小)。
- 其余 ✓:均含能力陈述 + when_to_use/Used when。

**C3 正文≤500** — 全部通过(最长 test-list-review 193 行)。门已守。

**C4 额外详情在单独文件**
- ✓✓ ist-compile-engine:52 行入口 + `references/{contracts,removed-rules,theory-map}.md` 三份——官方渐进披露范本。
- ✓ device-verify:`reference/ssh_template.md` + `scripts/apv_ssh_client.py`。
- ✗→✓ config-automation:原 `<Reference>` 段内联 device→IP 资源池表(环境数据)。**已修**:改为指向拓扑单一事实源 `network_topology.json`/`network_topology_rag.md`,只留 VIP 分配**规则**(机制)与稳定的示例网段口径,真实地址按引用现读。
- △ test-list-review / ist-verify:无 references/,但正文 <500 且内容内聚(P 级定义表、brief 模板、8 步各自 Success criteria),无强外移必要。
- N.A.:fork skill 深度细节按设计在 agents/*.md,SKILL 只做薄壳——符合官方 fork 分层。

**C5 无时效性信息** — 官方指「会过期变错的信息」(日期/currently/版本特定断言)。
- 全仓 SKILL/agent 正文**已无裸日期**(既有审计 2026-07-04 已清)。
- △ ist-compile-engine「V8」= 当前引擎工件名,与 frontmatter `graph: main.ist_core.compile_engine_v8`(已核实模块存在)一致,是**指针非过期教训**,保留。(注:CLAUDE.md 仍写「V6 引擎主路」,与 SKILL 的 V8 存在文档漂移——不在本队写权限内,转记 docs 维护。)
- △ ist-verify「since draft v3」轻微版本引用;`observed: 4 churn rounds / zero conversions` 为**实证 why**——项目证据优先纪律所要(CLAUDE.md 准则 1/12),非日期型时效性,保留。
- △ compile-worker「measured: 40 of 46 … only 6」为同类实证 why;具体计数对 LLM 信息量低(既有审计 C1 结论),但删数字有触碰机读尾块叙事的风险,**保留 measured 机制句、记录可选精简**。
- ✗→✓ config-automation:内联 IP 池 + 硬编码 `workspace/outputs/yzg/` 批名 = 会随测试床漂移的环境数据/巫术常量——**已修**(IP 池改指针;`yzg` 改为通用 `workspace/outputs/`「唯一可写根,每次运行一子目录」)。

**C6 术语一致**
- ✗→✓ config-automation:原为全仓唯一使用**首字母大写 XML 分节标签** `<Role>/<Rules>/<Agentic_Workflow>/<Output_Format>/<Reference>`;其余 inline skill 一律纯 markdown `## 节`,fork agent 一律小写 `<role>/<task>/<rules>`。**已修**:转为 markdown `## Core rules / ## Execution flow / ## Output format / ## IP resource pool` 分节,与同类 inline skill 一致(核实无 py 代码消费旧标签,inline 逐字注入无解析器,零功能影响)。
- 其余 ✓:case.xlsx / reflow / footprint / attribution / G-E-V-transient 等术语各 skill 内自始至终一致。

**C7 示例具体非抽象** — 全部 ✓。均为**输出形态/格式**类示例(官方鼓励):brief 模板、报告模板、STATUS/ARTIFACT 尾块、todo 清单、build_command 调用样例——非「领域判断答案」示例(后者被红线禁,本轮未发现违规)。

**C8 文件引用一层深 + 正斜杠** — 全部 ✓。仅 ist-compile-engine(`references/contracts.md`)、device-verify(`reference/ssh_template.md`、`scripts/apv_ssh_client.py`)有盘上引用,均一层深、正斜杠、文件存在(门已守)。

**C9 渐进式披露** — ✓✓ ist-compile-engine 最佳;△ config-automation 因 IP 表撑大正文(外移后改善)。余 ✓。

**C10 工作流步骤清晰** — ✓✓ ist-verify / device-verify(Steps + Execution/Success criteria/Artifacts/Rules 四元);ist-compile-engine 步骤在图内、SKILL 列 loop 阶段(恰当);fork skill 委托 agent md。全部 ✓/N.A.。

---

## 二、agent 定义(agents/*.md)结构审计(6 份)

全部通过 `<role>→<task>→<rules>` 骨架门(`test_agent_bodies_have_role_task_rules_structure`)与 frontmatter name/description/tools 门。补充观察:

| agent | 骨架 | frontmatter | 备注 |
|---|---|---|---|
| compile-worker | ✓ | ✓ tools 白名单 + inherit-parent-prompt | 深度范本;**含未提交的「读取通道区分 sample/member」bullet(89-99),绝不回退** |
| compile-attributor | ✓ | ✓ | 层次归因深;`measured:` 实证 why 密集(证据优先纪律所要,保留) |
| config-answer-draft | ✓ | ✓ model:haiku | 数据抽取表 + build_command 红线 |
| config-answer-verifier | ✓ | ✓ model:opus | 语义验证四查 |
| review-verifier | ✓ | ✓ | 对抗探针 + Verdict 机读块 |
| explore | ✓ | ✓ `inherit-parent-prompt: false` | 通用探索器,故意不继承项目上下文(与其「Do not assume CLAUDE.md」规则一致) |

承重锚点(两门断言)已全部核对,本轮编辑均**避开**:worker 的 `root@console`/`different door`/`wrong-door symptom`/`sampling luck`/`Σ hits == N sent`/`algorithm_classes.distribution`/`GA-CUT`/`h-in-λ (distribution sampling) only`/`dist\` combinator`/`Capacity / existence / enumeration checks read membership`/`dev_probe`/`667986`/禁 `Hit:`;attributor 的 `passed check point num`/`environment is reachable`/`root@`/`does not auto-downgrade`/`independent corroboration`/`not preset a default`。

---

## 三、脚本层 × checklist 矩阵(skill 内引用脚本)

列:S1 脚本解决问题非推给 Claude · S2 错误处理明确 · S3 无巫术常量 · S4 所需包已列/验证 · S5 清晰文档 · S6 无 Windows 路径 · S7 关键操作有回读校验 · S8 有反馈循环

| 脚本 | S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 |
|---|---|---|---|---|---|---|---|---|
| config-automation/config_generator.py | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |
| config-automation/modules/sdns_module.py | ✓ | N.A. | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ |
| config-automation/modules/slb_module.py | ✓ | N.A. | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ |
| config-automation/utils/ip_mapper.py | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | N.A. | N.A. |
| config-automation/utils/module_manager.py | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | N.A. | N.A. |
| config-automation/utils/topology_parser.py | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ | N.A. | N.A. |
| config-automation/scripts/smoke_config_generator.py | ✗ | ✓ | ✗ | ✓ | ✓ | ✓ | ✗ | ✗ |
| test-list-review/scripts/sanity_check.py | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | N.A. | N.A. |
| test-list-review/memory_adapter.py | ✓ | N.A. | ✓ | ✓ | ✓ | ✓ | N.A. | N.A. |
| device-verify/reference/ssh_template.md | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | N.A. |
| device-verify/scripts/apv_ssh_client.py | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | N.A. |

包核对(S4 全绿):config-automation 全链 + sanity_check 纯 stdlib;memory_adapter→langchain_core(requirements.txt:8)、ssh_template/apv_ssh_client→paramiko(requirements.txt:5);venv 实测 paramiko 3.5.1 / langchain_core 可导入。

### 脚本 ✗ 项证据 + 修法方向(报告为主,**未改**——理由见 §4「记录不改」)

- **[高] ip_mapper.py:28-31 硬编码 VIP 段(S3)** — `VIP_SEGMENTS = 172.16.32/33/34/35.0/24` 写死在 .py,与 topology JSON 的真实网段重复。违背「拓扑 JSON 是唯一事实源,换床只改 JSON」(CLAUDE.md 架构决策)——换床改了 JSON,VIP 段不跟随,会在旧网段生成 VIP。另 `:22` `EXAMPLE_NETWORKS = 172.16.0.0/19`(覆盖 .0–.31)恰卡在 VIP 段 .32 之下,是无注释隐式耦合;若有人改成 /16,示例检测会把真实 VIP 段当示例 IP 误替换。**修法**:VIP 段从 `self.topology` 现有网段推导(设备 IP 所在 /24);`/19` 边界写明依赖。此项需**专门回归测试**兜底后再改。
- **[中] smoke_config_generator.py 是空壳非真 smoke(S1/S7/S8)** — docstring 自述「无断言,靠人读」;`:67` 只判 `returncode==0`,从不校验产物内容(是否真替换 IP、有无示例 IP 泄漏)。生成乱码但 exit 0 时照报「✓成功」。`:41/:88` `parents[5]` 无注释魔法层级索引,文件挪位即断。**修法**:抽 IP 后回读产物,断言「示例网段 IP 计数==0 且映射数>0」。
- **[中] topology_parser.py:82 格式漂移静默返空(S2)** — 设备段正则 `### 第N层:` 不匹配时静默返回空 `NetworkTopology` 零告警,下游 IP 映射静默产出空表(吞失败)。**修法**:解析到 0 设备时返回带 warning 的显式信号。
- **[低] config_generator.py 三处 `open('w')`(:127-142)无 try/except(S2)** — 失败抛裸 traceback;`:97` `len(parsed_data)` 打印「配置项数量」实为 dict 键数(SDNS 恒 8),诊断误导。写 3 文件后无回读(S7)。**修法**:open 加守卫 + 写后回读行数。
- **[共性/by-design] 生成链无上机反馈环(S8)** — config-automation 是离线生成,verify 脚本产出后无环节自动上机执行,生成→上机校验→修正闭环开口,依赖人/agent 手动接。属该 skill 固有质量缺口。
- **轻微魔数(未达 ✗)**:sdns_module.py:29 / slb_module.py:41 的 `identify` 用裸 `>=2` 阈值无注释;建议补一句注释。

**达标亮点**:memory_adapter.py:107-123 finalizer 刻意返 None 打断「越评越懒」环(有文档背书);module_manager.py:70-71 发现失败逐模块 print 模块名+异常不炸整轮;sanity_check.py 9 类确定性检测 + `:426-432` 文件缺失/读异常返 error dict;apv_ssh_client.py 共享 device_errors + 独立加载回退,send_cmd 带 deadline + `--More--` 回读。

---

## 四、修复清单

### 已改(低风险增益)

1. **描述域锚定(C1)** — 三个用户可调入口 skill 的 description 前置 `APV load-balancer (SLB / SDNS …)` 领域锚:
   - `test-list-review`:`Reviews APV load-balancer (SLB / SDNS / HTTP / IPv6) test cases / test strategy …`
   - `ist-compile-engine`:`… turns a mindmap of APV load-balancer (SLB / SDNS) test cases into …`
   - `ist-verify`:`Runs an already-compiled APV load-balancer (SLB / SDNS) case.xlsx …`
   - 理由:直接服务任务第二目标;description 变更不影响 tool_gating(按 name 映射),不触碰任何门断言;域锚前置以在 250 字截断的 listing 内可见。

2. **config-automation SKILL.md 收口**(全仓唯一结构离群 skill,正文 95→64 行):
   - **C1 域锚**:description 加 `IP replacement tool for APV load-balancer (SLB / SDNS) configurations`。
   - **C6 骨架一致**:`<Role>/<Rules>/<Agentic_Workflow>/<Output_Format>/<Reference>` 首字母大写 XML 标签 → markdown `## 节`,与同类 inline skill 统一。
   - **C4/C5 数据按引用**:内联 device→IP 资源池表 → 指向拓扑单一事实源 + 只留 VIP 分配规则(机制)。
   - **C5 巫术常量**:`workspace/outputs/yzg/` → 通用 `workspace/outputs/`。
   - 核实:无 py 代码消费旧标签/yzg 路径;description 无 XML tag;body 64≤500。

### 报告不改(脚本层缺陷,§3 有精确修法方向)

脚本在 `skills/**` 属本队写权限内,但均在**无 pytest 覆盖的运行时路径**上(config-automation 的 IP 替换 live 链;config-automation 旧「测试」已降级为手工 smoke)。按全队红线**「通过率不降」**,对无测试兜底的运行时代码做外科手术,回归风险高于本次规范对齐的收益。故**全部报告不改**,`ip_mapper.py` VIP 段硬编码标为**首要跟进**(需先补专门回归测试)。

### 记录不改(有理由)

- device-verify 内联 show 命令表(`show slb virtual all` 等):与「零写死领域命令」红线存在张力,但为**只读 show** 助记且 skill 同时要求先 grep 手册;既有设计,改动风险高、超本次规范对齐范围——**转 redline-reviewer 队评估**。
- fork skill(compile-worker/attributor/review-verifier)description 域锚:按名派发不进 listing,增益低 churn 高;强改需同步双份 agents/*.md frontmatter。
- 各处 `measured:`/`observed:` 实证 why:证据优先纪律核心(CLAUDE.md 准则 1/12),非日期型时效性,保留。
- config-answer description 祈使形态:轻微,改动收益小。
- CLAUDE.md「V6 引擎主路」与 SKILL「V8」文档漂移:不在本队写权限内(CLAUDE.md),转记 docs 维护。

---

## 五、门测试结果(修复后)

- `pytest test_skill_package_standard.py test_prompt_structure.py` → **21 passed**(与基线一致,零回归)。
- 扩大范围 `pytest tests/ist_core/skills/ tests/ist_core/agents/ tests/ist_core/middleware/test_tool_gating.py` → **119 passed**(loader/tool_gating 按 skill 名映射,description 与正文结构变更不影响;fork 装配/prompt 承重锚点全绿)。
- 承重锚点两门断言逐条核对,本轮编辑全部避开——0 处触碰。

**结论**:12 skill 规范对齐,唯一结构离群者(config-automation)已收口;4 处描述(test-list-review / ist-compile-engine / ist-verify / config-automation)达成「负载均衡产品自动化测试规范描述」域锚;脚本层缺陷取证入档、按无回归红线报告不改并给精确修法方向;门全绿零回归。
