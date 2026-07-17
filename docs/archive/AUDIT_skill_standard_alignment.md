# 审计:IST-Core 资产封装对标 Agent Skills 官方标准(2026-07-04)

> ⚠️ **历史存档（2026-07-17 归档,team4 docs 整编）**：第一轮 skill 对标(2026-07-04),被 AUDIT_skill_bestpractice_v2.md(第二轮,覆盖全部条目)取代。事实存档不删,现状勿引本文。

> 触发:用户判定「元数据/指令/资源分离做得差;skill 与 MCP/工具边界没对齐;必载/按需混乱;无 skill 标准包;核心定义缺 metadata;核心指令无 XML 角色/任务/规则区分」。本审计以官方规范原文为基准(platform.claude.com Agent Skills best-practices,2026-07-04 拉取)+ 盘上实测数据逐条核实。lint 原型全量扫描 13 skill + 7 agent 定义,量化 20 条违规。

## 一、对标基准(官方规范要点)

1. **frontmatter**:必填仅 `name`(≤64,小写字母/数字/连字符,禁 XML tag/保留词)+ `description`(非空≤1024,第三人称,含 what+when——它是 100+ skill 里被选中的唯一依据)。
2. **渐进披露三层**:启动只预载全部 skill 的 name+description → 触发才读 SKILL.md body(≤500 行) → 捆绑文件(references/scripts/assets)按需读;**脚本执行不读入上下文,只有输出耗 token**。
3. **包布局**:SKILL.md + 按域组织的 reference 文件(一层深引用,>100 行带目录)+ scripts/(可执行,声明"执行"还是"读作参考")。
4. **上下文是公共品**:"Default assumption: Claude is already very smart"——只加模型没有的上下文。
5. **MCP 工具引用带全限定名**(ServerName:tool_name)。
6. **eval 先行**:先建评测再写文档;按自由度匹配约束强度(窄桥精确/开阔田野给方向)。

## 二、逐条审计(用户点名 6 项,全部证实,程度不一)

### 1. 元数据不一致/缺失 —— 证实

- 13 个 SKILL.md 的 frontmatter 字段集有 **5 种不同组合**(有的带 when_to_use/allowed-tools/effort/version/source,有的只有 name/description/context/agent)。
- lint 实测违规(修复前):`config-automation`/`test-list-review` 缺 `context`(加载语义未声明);`escalate-when-stuck` user-invocable 但缺 `when_to_use`(listing 触发条件缺失);5 个 skill 名含下划线(官方仅允许连字符):compile_worker/ist_compile/ist_compile_draft/ist_compile_grade/ist_verify。
- agents/*.md frontmatter 仅 name/description/tools/model,无 version/effort 等分层字段(工具白名单已显式声明——这条合规)。

### 2. 核心指令无结构化表达 —— 证实

`agents/_prompt.py`(11,096 字符,每请求常驻):
- 全 markdown `#` 平铺 13 节,**无 XML 标签区分角色(role)/任务(workflow)/规则(rules)/工具指引(tool guidance)/环境(env)**;约束、身份、工作流、沟通风格混排同级。
- 中英混杂(Identity/Evidence Discipline 英文,文件边界/反空转中文,同节内也混)——官方"术语一致"红线的语言版违背。
- **领域资源烧进常驻指令**:Product Domain 节含厂商命令关键词表(slb/sdns/gslb/hi/hip/chi/pto/hh/chh/pu/hq…)——这是"资源"(该进 knowledge reference),不是"指令",且与「skill/agent 零写死领域命令」红线精神相悖(主 prompt 目前豁免于该红线,但分离原则同样适用)。
- 7 个 agents/*.md body 同样无角色/任务/规则结构区分(lint 实测 7/7)。

### 3. 必载 vs 按需混乱 —— 部分证实(有做对的,有严重缺口)

实测分层现状(每次 LLM 调用的常驻集):

| 层 | 内容 | 实测体量 | 判定 |
|---|---|---|---|
| 常驻·工具 schema | 32 个工具的 docstring+参数 schema | 仅 loader 注册的 27 个即 **52,224 字符**(dev_ssh 5.3k/compile_emit 4.7k/dev_rest 3.2k/emit_merged+fanout 各 2.6k) | **主要缺口**:无分层,低频工具(submit_attribution/compile_writeback/grade_extract…)全量常驻 |
| 常驻·系统提示 | _prompt.py 输出 | 11,096 字符 | 偏重:工具用法节与 docstring 重复讲一遍 |
| 常驻·L3 记忆 | memory/AGENTS.md | 3,226 字符 | 合理 |
| 每轮·skill listing | per_turn_skill_reminder | ≤8,000 字符预算,desc 截 250,超额降级 name-only,优先级排序 | **做得对**——正是官方 L1 metadata 模型,还多了预算护栏 |
| 触发·SKILL body | invoke_skill 才注入 | 34-192 行/个 | **做得对**(官方 L2) |
| 触发·fork prompt | agents/*.md fork 时才加载 | 1.8k-18k 字符/个 | 做得对(官方 L2) |
| 按需·references | 仅 device-verify 有 reference/ | — | **缺口**:其余 12 个 skill 无 L3 层,细节全挤在 body 或工具 docstring |

结论:**skill 侧的渐进披露基本对齐官方;工具侧完全没有渐进披露**——52k+ 常驻里大量是"流程知识伪装成工具说明"。

### 4. skill vs 工具/MCP 边界没对齐 —— 证实

官方分工:**skill=流程知识(触发加载),工具=原子能力(schema 常驻,故必须瘦)**。现状违背处:

- **工具 docstring 塞编排知识**:何时派 grade/节流策略/归因层解释/子集复测指引……写在 dev_run_batch_digest、compile_fanout 等 docstring 与返回文本里,同样内容 SKILL.md 再讲一遍 → **双份维护必然漂移**。实锤:2026-07-04 redline 评审在 ist_compile SKILL 红线段抓到「送 grade 几次」残留(grade 换源时工具/凭证/CLAUDE.md 都改了,prompt 高权重段漏改)——这不是笔误,是同一知识散在 N 处的结构性后果。
- **无能力归属基准表**:哪些能力属设备框架 MCP(deliver/run/status)、哪些属本地确定性工具(compile_*机械门)、哪些属流程知识(SKILL),没有一张对齐表,历次演进按撞按补。
- 官方"MCP 工具全限定名"条款:本项目 dev_* 是 MCP 客户端的本地包装(非直连 MCP server 注册),暂不适用;但 SKILL 里引用工具名无任何命名空间说明,依赖 CLAUDE.md 的 `fs_*/dev_*/compile_*` 前缀约定——约定存在,未写进 skill 规范。

### 5. 无 skill 标准包 —— 证实

- 13 个 skill 仅 `device-verify` 接近官方布局(SKILL.md+reference/+scripts/);其余无 references/。
- `config-automation` 包内混 `tests/`——**pytest 从不收集 skill 包内测试**(pytest.ini testpaths 根本不含它),这份"测试"自创建起从未在 CI 跑过,且它本身无断言(手工冒烟脚本假装成测试)。
- **pytest.ini `testpaths = main/tests` 指向不存在的目录**——裸 `pytest` 收集不到任何东西,全靠大家手工 `pytest tests/`。配置死项。
- 无 lint/校验门:上述问题存在多久都不会被任何机制发现。

### 6. 加载语义声明缺失 —— 证实(见 1/3)

`context:` 字段(inline/fork)是 loader 的加载语义开关,却有 2 个 skill 不声明、靠 loader 默认值——"哪些必须加载哪些按需加载"在定义层就没写清。

## 三、能力归属基准表(本审计确立,后续演进按此对齐)

| 资产层 | 承载什么 | 加载时机 | 现有实体 |
|---|---|---|---|
| **常驻系统提示** | 身份/语言/文件边界/证据纪律/反空转——跨任务不变的最小集 | 每请求 | _prompt.py(待 XML 结构化+减重) |
| **skill(SKILL.md)** | 流程知识:编排顺序/决策点/触发与跳过条件/自由度分层约束 | L1 metadata 每轮 listing;L2 body 触发注入;L3 references 按需 fs_read | 13 个 |
| **agent(agents/*.md)** | fork 容器的角色约束(单 case 编写/审批/验证行为) | fork 时作 system prompt | 7 个 |
| **本地工具(@tool)** | 原子能力+机械门(确定性校验/凭证/围栏);docstring=契约(何物/入参/错误语义/1-2 句何时),**不承载编排** | schema 每请求常驻 → 必须瘦 | 32 个 |
| **MCP(设备框架 stdio)** | 设备侧执行:deliver/run/status/日志收割 | dev_* 工具内部经跳板机调用 | FrameworkMCPClient |
| **knowledge/ 资源** | 手册/拓扑/先例/footprint——领域事实 | 全部按需(fs_read/kb_*) | knowledge/data + footprints |

判据一句话:**随任务变的是 skill,跨任务不变的是 prompt,确定性可执行的是工具,领域事实是资源;工具 docstring 出现"什么时候/接下来该"字样即为越界信号。**

## 四、补齐计划(A 已落地 / B 待拍板 / C eval-gated)

### A. 机械项(2026-07-04 本轮已落地,零行为风险)

1. `pytest.ini` testpaths 修为 `tests`(原指向不存在的 main/tests)。
2. `config-automation`/`test-list-review` 补 `context: inline`;`escalate-when-stuck` 补 `when_to_use`。
3. config-automation 伪测试迁 `scripts/smoke_config_generator.py`(明示手工冒烟,非 pytest);skill 包内 tests/ 目录清除。
4. **永久门** `tests/ist_core/skills/test_skill_package_standard.py`(7 断言):frontmatter 完备性/name 规则(存量下划线白名单挂 B1)/description ≤1024 禁 XML/context 必声明/fork agent 可解析/user-invocable 必带 when_to_use/body ≤500 行/引用文件存在且正斜杠/包内禁 tests//agents 定义 metadata 完备。新增违规从此进不了库。

### B. 结构重写(内容不动,骨架标准化)

1. **skill 名连字符化(2026-07-05 已落地)**:5 个目录 git mv 连字符名 + 全仓 43 处活跃引用批量更新(CLAUDE.md/SKILL 交叉引用/pipeline 硬编码/测试;docs 与 scripts/debug 为历史件不动)。别名层 `loader.resolve_skill_dirname`(下划线/连字符互通,TUI slash 侧本就互通零改动)接进 invoke_skill + execute_fork_skill——历史对话/旧脚本用旧名照常工作;`tool_gating._SKILL_GROUPS` 新旧双键(历史消息里的旧名激活语义不丢)。标准包门白名单**清空**(新 skill 禁下划线名),别名解析进永久测试。
2. **_prompt.py XML 结构化(2026-07-04 已落地)**:13 节重组为 `<role>`/`<rules>`(文件边界/证据纪律/读≠验/忠实汇报/反空转/沟通风格)/`<workflow>`(skills-first/任务追踪/探索/fork brief/不过度委托)/`<tool_guidance>`/`<env>`(可选);语言统一中文;关键词表迁 `knowledge/data/compile_ref/vendor_cli_keywords.md` 留指针。**实测:主提示 11,096→6,583 字符(-40%)**,26 个承重锚点由 `tests/ist_core/agents/test_prompt_structure.py`(5 断言)门守;继承块改为 `<inherited_rules>` 包裹、范围校验(必含 5 节共享约束/必不含身份与工作流)。
3. **agents/*.md 同款结构化(2026-07-04 已落地,7/7)**:统一 `<role>→<task>→<rules>` 骨架,rules 收尾紧邻 $ARGUMENTS 注入点(注意力最高位);内容零删改只组块。骨架进永久门(`test_agent_bodies_have_role_task_rules_structure`)——这同时是后续**动态生成 agent 的模板契约**。fork 装配实测:`<inherited_rules>`+三段骨架序正确。
   - **eval 记录(如实)**:CLAUDE.md 原引用的 e2e_cookie_review_v2 脚本从未入 git、已丢失(文档已修正);本轮 eval=pytest 1536 全绿(结构保真门+装配端到端)+行为验证挂 34-case 编译对照轮。

### C. 减负(C2 已落地为根治;C1 前提被测量修正)

1. **C1 修正(2026-07-05,测量驱动,如实记录)**:原假设"docstring 塞大量编排叙事,迁走可 52k→35k"——**测量证伪**。实测 40 工具 description 总量 23k 字符,其中含取证叙事的句子仅 618 字符(2%);参数级再挖 364 字符。常驻重量的大头是**参数 schema(≈44k)且属契约**(列语义/安全闸/通道说明),本就该在工具上,迁走即断契约。据此 C1 收缩为:修剪叙事密度最高的 4 处(事故日期/token 数字/具体 autoid 对 LLM 零信息,规则+短 why 保留,完整取证仍在 CLAUDE.md/docs);**放弃迁移型大改**——按错误前提硬迁恰是要防的"高风险裸迁"。
2. **C2 工具渐进披露 middleware(2026-07-05 已落地)**:`middleware/tool_gating.py`——按能力域分组(前缀即域:compile_/submit_→compile,dev_→device,其余=基础组常驻),`wrap_model_call` 用 `request.override(tools=…)` 过滤。激活全走机械信号:①历史 `invoke_skill(skill=X)` 按 `_SKILL_GROUPS` 映射;②历史已用过 gated 工具→组粘性激活;③未知 skill/参数不可解析/过滤异常→全量放行(fail-open)。**实测:全量 34 工具 67k 字符 → 基础模式 14 工具 26k(-61%)**。默认开(2026-07-05 对照轮验收后翻默认,`IST_TOOL_GATING_ENABLED=0` 关)。回归 10 断言(`tests/ist_core/middleware/test_tool_gating.py`),含预算验收(基础模式 ≤35k)与 skill 映射覆盖门(新 skill 漏配映射当场报)。

### D. 动态 agent 生成(2026-07-05 已落地,用户追加目标)

main 可随时按本审计确立的标准流程自主生成子 agent 协助任务:**`agent_define` 工具**(`tools/skills/agent_define.py`)——main 只传语义(role/task/rules 三段 + 工具白名单 + model 档),骨架/frontmatter/共享硬约束由工具拼装(correct-by-construction,与 compile_emit 组合子同哲学)。

- **模板 = B2 骨架**:生成物就是一份标准 `<role>/<task>/<rules>` agent md + context:fork 派发壳(body=$ARGUMENTS),落 `runtime/dyn_agents|dyn_skills/`。
- **三道安全闸**:name 白名单正则强制 `dyn-` 前缀(防冒充静态件);tools 必须 ⊆ 工具注册表(未注册即拒,不静默丢);`inherit-parent-prompt` 强制 true(证据纪律/忠实汇报/反空转不可剥离)。结构标签注入/frontmatter 破坏(多行/`---`)在入口拦截;runtime/ 在文件工具黑名单内——创建/覆盖只有这一条有闸的路(门挂凭证路)。
- **派发零新机制**:invoke_skill 单发、`compile_fanout(skill="dyn-…", briefs_path=…)` 批量并发(载荷走文件通道);loader 静态目录优先、动态目录兜底;同名覆盖须显式 overwrite=True 且自动清 runnable 缓存;出厂自检(写完按加载路径读回)。
- 不进 per-turn listing(临时件不污染 L1 metadata 预算);tool_gating 对未知 dyn skill fail-open 全量放行(设计时已预留)。

### 双评审结论(2026-07-05,B1/D 收尾)

- **红线评审:PASS**(四红线零命中;B2/B1 的批量改写实为净清除既有红线残留——写死 Hit 正则/具体 sdns 语法/dnsperf 工具名等)。抓到 2 个确认缺陷已修:①三处指引误指写沙箱必拒的 `workspace/tmp/`(改 `workspace/outputs/<autoid>/`);②CLAUDE.md 用例编译节残留「逐 case 派 grade」旧主路句(与 V4 换源自相矛盾,B1 sed 只换了名没换语义)。观察项机械化:**agent_define 拒授上机执行权**(dev_run_*/dev_init_device——互斥/残留探测/run-identity 护栏全在 ist-verify 链上,dyn 直跑=绕过)。
- **安全评审:agent_define 机制 PASS**(名字白名单+固定目录零穿越面;description 注入经 YAML 实测不可利用且出厂自检兜底;tools ⊆ 注册表;inherit 硬编码;fork agent 无 agent_define=不能递归自造)。附带抓到 1 个**中危**已修:compile_fanout 的 evidence_from_xlsx 注入曾在 except 里吞掉沙箱拒绝后回退原始路径(读闸旁路)——改为拒绝即放弃注入,永不裸读;新增回归测试(沙箱外 last_run.json 不再进 brief)。
- 修复后 pytest **1554** 全绿。

### 验收断言(机器可测)

- A:pytest 全绿(已达 1552,含标准包门/prompt 结构门/gating/agent_define);裸 `pytest` 与 `pytest tests/` 收集数一致。✅
- B:门白名单清空 ✅;编译对照轮首跑 pass 率不降(待跑,task #33)。
- C:基础模式常驻工具 schema 26k(≤35k 目标,固化为测试)✅;C1 按测量修正收缩 ✅。
- D:agent_define 校验闸 8 项拒绝路径 + 全链路派发(stub)+ 静态件不受影响,永久测试 ✅。
