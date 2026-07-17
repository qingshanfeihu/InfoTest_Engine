# 官方中文 best-practices 全类目对照复检（任务 #30）

> 2026-07-18 · LLM-Eng。**只读**。基准=官方中文版 https://platform.claude.com/docs/zh-CN/agents-and-tools/agent-skills/best-practices（本次 WebFetch 全文，以中文版为准基）。
> 资产面：main/ist_core/skills/ 全部 **14 个 SKILL.md**（+references/）+ main/ist_core/agents/ **9 个 agent md** + agent_define.py 的 dyn 骨架生成模板。机械事实由子 agent grep 取证（file:line），判定与分级由我做；证据边界纪律=每条结论标 firsthand 核实 / 机读事实 / 推断。
> 对照基线：docs/AUDIT_skill_bestpractice_v2.md（2026-07-09 第二轮）+ 我 #7 报告（team4_skill_audit.md）。

## 0. 摘要（报 leader 数字）

- **官方要求枚举**：35 条（硬性 9 + 命名/结构/内容/模式/脚本/MCP 软性 26）。
- **矩阵总格数**：35 要求 × 23 资产（14 skill + 9 agent）= **805 格**（+ dyn 模板单列）；聚合呈现（每要求给全体判定+逐一点名例外，N.A. 记理由，不挑高价值项）。
- **相对 v2 新增/变化要求点**：4 条（详见 §3）。
- **发现分级**：**P0=0**（硬性规则全过，无行为面违反）/ **P1=4** / **P2=3** + 1 程序级 gap（评估集，与 v2 #21 同,📋 立项）。
- **冻结面 vs 独立项**：冻结面 2 条（裁决③ config-automation 脚本族、#15 doc-writer 删除——均已在既有裁决池）；独立可修 5 条（我域，走收口批双评审）。

**总判**：资产在**硬性规则面 100% 合规**（0/23 name/description 违规、0 body>500、0 Windows 路径、0 时效性条件、0 真 MCP 误引、agent_define 出厂即标准骨架）——#7/#19 已把 P0/P1 级清干净。本轮增量全部是**结构一致性/风格**层，且多数落在既有裁决池或已 DEPRECATED 项。

---

## 1. 官方要求全枚举（35 条，硬 H / 软 S）

**Frontmatter（硬性验证，官方 Note+技术说明）**：F1 name≤64 / F2 name 仅小写字母数字连字符 / F3 name 无 XML / F4 name 无保留词 anthropic·claude / F5 desc 非空 / F6 desc≤1024 / F7 desc 无 XML / F8 desc 含功能+何时用 / F9 desc **第三人称**（Warning 明列）。
**命名（软）**：N1 动名词形式建议（名词短语/动作导向可接受）/ N2 避免模糊(helper/utils/tools)·过于通用·保留词·集合内不一致。
**Body（软）**：B1 ≤500 行 / B2 简洁（只加 Claude 不知道的）/ B3 自由度匹配（高/中/低）。
**渐进式披露（软）**：P1 SKILL 作概述指向详情 / P2 引用仅一层深 / P3 >100 行参考文件加目录 / P4 按领域组织 / P5 描述性文件命名。
**工作流/反馈（软）**：W1 复杂任务分步+可复制 checklist / W2 反馈循环（验证器→修→重复）。
**内容（软）**：C1 无时效性信息（或"旧模式"部分）/ C2 术语一致。
**常见模式（软）**：M1 模板模式（严格/灵活分档）/ M2 示例输入/输出对 / M3 条件工作流决策点。
**评估（软）**：E1 eval-first / E2 ≥3 评估场景 / E3 用 Haiku·Sonnet·Opus 测试。
**反模式（软）**：A1 无 Windows 路径 / A2 不过多选项（给默认+escape hatch）。
**脚本（软，含代码 skill）**：S1 解决问题不推卸（错误处理）/ S2 无巫术常量（值有理由+文档）/ S3 预制实用脚本 / S4 明确执行 vs 参考阅读 / S5 可验证中间输出（计划-验证-执行）/ S6 包依赖列出+验证可用。
**MCP（软）**：MCP1 全限定名 ServerName:tool_name。
**依赖（软）**：I1 不假设包已安装。

---

## 2. 全类目对照矩阵（每要求 × 全体资产，聚合+点名例外+N.A. 理由）

| # | 要求 | 判定（全体 23 资产，例外点名 file:line） |
|---|---|---|
| F1 | name≤64 | **全 PASS**（7-22 字符，最长 config-answer-verifier 22） |
| F2 | name 字符集 | **全 PASS**（`^[a-z0-9-]+$` 23/23，无下划线/大写） |
| F3 | name 无 XML | 全 PASS | 
| F4 | name 无保留词 | 全 PASS（0 含 anthropic/claude） |
| F5 | desc 非空 | 全 PASS |
| F6 | desc≤1024 | **全 PASS**（最长 test-list-review 630） |
| F7 | desc 无 XML | 全 PASS（review-verifier 的 VERDICT/PASS 是裸词非标签） |
| F8 | desc 含功能+何时用 | 全 PASS（fork 类靠 desc 内嵌语境；inline 类另有 when_to_use） |
| F9 | desc **第三人称** | **全 PASS**（0 首人称；7 处 `"I "` 是 "CLI " 假阳性，子 agent 逐条核实） |
| N1 | 动名词优先 | PASS/N.A.：doc-authoring 为动名词；余为名词短语/动作导向（官方**可接受替代**，非违规）；explore 裸动词（可接受） |
| N2 | 避免模糊/通用 | 全 PASS（无 helper/utils/tools/data 类；explore 通用只读 agent 语义明确） |
| B1 | body≤500 | **全 PASS**（最长 SKILL test-list-review 181；最长 agent compile-worker 199） |
| B2 | 简洁 | PASS（抽查无基础概念解释；实证引用密度高但均"Claude 不知道的坑"，同 v2 判定） |
| B3 | 自由度匹配 | PASS（worker/attributor 高自由度给方向；emit 契约/固定序低自由度精确护栏——符合窄桥/田野原则） |
| P1 | SKILL 概述指向详情 | PASS（ist-compile-engine→references/contracts.md；device-verify→reference/*；ist-verify→mirror 源码） |
| P2 | 引用仅一层深 | **PASS**（device-verify 链已在 #7/#19 拍平；ist-compile-engine contracts.md 只指向 data/code 非另一 md，无 md→md→md 链） |
| P3 | >100 行参考加目录 | **N.A.**（全部参考文件 ≤67 行：ssh_template 67/contracts 45/removed-rules 35/theory-map 21，均免目录） |
| P4 | 按领域组织 | PASS（skills 按能力域；references 按契约/理论/删规分文件） |
| P5 | 描述性文件命名 | PASS（无 doc2.md 类；ssh_template/contracts/theory-map 等自描述） |
| W1 | 复杂任务分步+checklist | PASS（test-list-review Step0-8；device-verify 有 checklist 代码块；**ist-verify Steps1-8 无 checklist 代码块**——半落地，v2 B2-7 计划项，⚠见 §4） |
| W2 | 反馈循环 | PASS（config-answer draft→verify→CUT 重做；ist-verify 归因回流；emit 门→violation→重 emit） |
| C1 | 无时效性条件 | **全 PASS**（0 处日期作条件分支；所有 2026-XX 均实证引用/DEPRECATED 标注，firsthand 核实） |
| C2 | 术语一致 | **1 FAIL**：test-list-review `SKILL.md:3` desc 用 "**Trigger phrases:**" vs `:9` when_to_use 用 "Trigger keywords:"（#19 只改了 when_to_use 行，desc 残留）→ P2-a |
| M1 | 模板严格/灵活分档 | PASS（机读尾块=严格档；报告模板=灵活档） |
| M2 | 示例输入/输出对 | PASS（compile-worker desc 示例对；config-answer-draft 输出模板；fork 尾块模板） |
| M3 | 条件工作流 | PASS（config-answer 生成/翻译分叉；ist-verify 按层路由；device-verify 只读/下发分叉） |
| E1 | eval-first | PASS（体系级：prompt 结构门/标准包门/对照轮；#23 四面对比亦为 eval） |
| E2 | ≥3 评估场景 | **FAIL（程序级 gap）**：无 per-skill 3 场景评估集（test-list-review/config-answer/device-verify 零评估集）——**与 v2 #21 同,📋 立项未动** |
| E3 | 多模型测试 | **FAIL（程序级）**：未系统用 Haiku/Sonnet/Opus 三档测每 skill（体系跑 mimo/deepseek 主档）——📋 立项 |
| A1 | 无 Windows 路径 | **全 PASS**（0 反斜杠路径；仅 compile-worker.md:137 IP-port 正则转义） |
| A2 | 不过多选项 | PASS（无多库堆砌；config-automation 给默认+escape hatch） |
| S1 | 错误处理不推卸 | **部分 FAIL**：6 脚本零 try/except——config_generator.py/sdns_module/slb_module/smoke_config_generator/topology_parser（**冻结面裁决③**）+ memory_adapter.py（独立）→ P1-c |
| S2 | 无巫术常量 | PASS：grade_extract/sanity_check/ip_mapper 常量均带注释或命名（VIP_HOST_MIN=50 等）；apv_ssh_client 类常量命名 |
| S3 | 预制实用脚本 | PASS（apv_ssh_client/sanity_check/grade_extract 均预制） |
| S4 | 明确执行 vs 阅读 | **部分 FAIL**：孤儿脚本树无 execute/read 指令——config-automation 7py + test-list-review 2py 的 SKILL.md 零引用（config-automation→冻结③；sanity_check.py 已 DEPRECATED；余内部 helper）→ P2-c |
| S5 | 可验证中间输出 | PASS/部分体现（emit 门+lint 凭证=计划-验证；ist-verify runtime_slots 回填校验；needs_decision.json 中间态） |
| S6 | 包依赖列出+验证 | PASS：ssh_template 已声明 paramiko（#19 P3-3）；config-automation .py 内部 deps 未声明但 SKILL 不引用它们（随③退役） |
| MCP1 | MCP 全限定名 | **N.A.**（项目无 MCP 工具引用；dev_*/fs_* 是本地包装非 MCP server 注册；2 处 `X:Y` 是 module:attr 与 IP:port 假阳性） |
| I1 | 不假设包已安装 | PASS（ssh_template 声明 paramiko；无裸"用 X 库"指令） |

**dyn 模板（agent_define.py）单列**：出厂即标准骨架——name 正则+dyn- 前缀强制、desc≤1024+XML 拒、role/task/rules 骨架强制、tools⊆注册表、inherit-parent-prompt 硬编码 true、model 枚举、出厂自检回读。对 F1-F7/B/骨架**全 PASS**（correct-by-construction）。唯 F9 第三人称仅 docstring 记载未机械校验（低优先观察，dyn 是临时件不进 listing）。

---

## 3. 与 v2 审计对照（新增/变化要求点 + 上轮漏项）

**官方中文版 vs v2 基线**：中文版「高效 Skill 检查清单」= 与 v2 同源的 21 项 + body 正文要求（自由度/第三人称/命名/MCP/包依赖/计划-验证-执行）。**4 个新增/强化要求点**（v2 相对宽松或未展开）：

1. **F9 第三人称（Warning 明列强化）**：中文版用独立 Warning 框强调"始终第三人称，不一致人称致发现问题"。v2 曾抓 escalate 第二人称（#19 已修）→ **本轮 0 违规**，强化点已合规。
2. **S4 明确执行 vs 阅读（运行时环境节强化）**：中文版明列"运行 X"vs"参见 X"。据此**孤儿脚本树**（无任一指令）从 v2 的"⚠低优先常量审"升级为明确的 S4 结构缺口——但多数落冻结③/已 DEPRECATED。
3. **S5 计划-验证-执行中间输出**：中文版新增"可验证中间输出"节（changes.json 计划文件）。我们的 emit 门/lint 凭证/needs_decision.json 部分体现，非缺口。
4. **E3 多模型测试（Haiku/Sonnet/Opus）**：中文版检查清单明列三档。v2 #21 仅立项 per-skill eval，未含多模型——本轮并入 §4 程序级 gap。

**v2 按旧基准漏掉、本轮全覆盖surfaced 的项**：
- **config-answer when_to_use 缺 SKIP when:**（`SKILL.md:6-9`，firsthand grep 确认）——唯一 user-invocable 缺 SKIP，官方 SKIP 模式防误触。v2 未查此细节。→ P1-a
- **reference/ 单复数不一致**：device-verify/**reference**/ vs ist-compile-engine/**references**/——v2 只查链深未查单复数；且 invoke_skill 注入只识别单数（#7 P2-5）→ ist-compile-engine 的 contracts.md 永不进注入。→ P1-b
- **test-list-review desc 残留 "Trigger phrases"**：#19 P2-4 只改了 when_to_use 行，desc 字段（:3）残留——v2 早于 #19。→ P2-a
- **孤儿 reference docs**：theory-map.md/removed-rules.md 未从 SKILL.md 链接（维护者文档，官方要求 references 一层链接）。→ P2-b

**v2 已修、本轮复验通过**：escalate 第三人称、Explore→explore 小写、device-verify 引用链拍平、ssh_template paramiko 声明——firsthand 复验均 PASS。

---

## 4. 发现分级（P0/P1/P2 + file:line）

**P0（行为面违反）＝ 0**。硬性 frontmatter 全过、7 个 user-invocable 全带 when_to_use、无保证误触的缺陷——如实 P0=0（#7/#19 已清）。

**P1（结构一致性）＝ 4**：
- **P1-a｜config-answer when_to_use 缺 SKIP when:**（`skills/config-answer/SKILL.md:6-9`）——唯一 user-invocable 缺 SKIP，误触风险（通用 CLI 问答可能误入）。**独立·我域·收口批**。
- **P1-b｜reference/ vs references/ 目录名不一致**（`device-verify/reference/` 单数 vs `ist-compile-engine/references/` 复数）——invoke_skill 注入只识别单数,ist-compile-engine/references/contracts.md 永不进 `<skill_references>`。**性质细化(firsthand 复核 2026-07-18)**:contracts.md 是**维护者/评审者面**(SKILL.md:39 "documented in" informational 指针;tail block 真实消费者是引擎 `nodes.py:31 _TAIL_RE`,非主 agent 读它;fork 尾块格式来自各自 agent md)——故此不注入**无 active 行为损失**,是**潜在结构陷阱**(日后 agent-facing 参考误放复数目录会静默不注入)。拆两半:①单复数陷阱修=#20 卫生正确性;②contracts.md 是否留=#15 doc(冗余则清理/标 maintainer-only)。**独立·我域+基础设施(与 #20 关联)·收口批**。
- **P1-c｜6 脚本零 try/except**（S1 错误处理）——config_generator.py/sdns_module.py/slb_module.py/smoke_config_generator.py/utils/topology_parser.py（**冻结面·裁决③退役**）+ `test-list-review/memory_adapter.py:全文`（**独立·我域/评审**）。
- **P1-d｜frontmatter 键不一致**——user-invocable 键缺 3（compile-attributor/config-automation/test-list-review SKILL.md）、allowed-tools 仅 4/14、agents `model` 缺 2（doc-writer/report-generator）、`inherit-parent-prompt` 缺 3（doc-writer/document-author/report-generator）。**独立·我域·收口批**（注:标准包门未强制这些键,属一致性非合规）。

**P2（风格）＝ 3**：
- **P2-a｜术语不一致**：test-list-review `SKILL.md:3` desc "Trigger phrases:" vs `:9` "Trigger keywords:"。**独立·我域·收口批**（一行修）。
- **P2-b｜孤儿 reference docs**：`ist-compile-engine/references/theory-map.md`+`removed-rules.md` 未从 SKILL.md 链接（维护者文档,可保留或加"maintainer-only"标注）。**独立·我域·低优先**。
- **P2-c｜孤儿脚本树无 execute/read 指令**（S4）：config-automation 7py（**冻结③**）+ test-list-review sanity_check.py（**已 DEPRECATED**）/memory_adapter.py。多数已归属,残余靠 §裁决消化。

**程序级 gap（非 per-asset，📋 立项）**：E2/E3——无 per-skill ≥3 场景评估集 + 无多模型(Haiku/Sonnet/Opus)系统测试。与 v2 #21 同,未动。**独立·需用户/leader 立项决策**（非收口批范围）。

---

## 5. 冻结面 vs 独立项归属（供 #24/收口批）

**冻结面（落既有裁决池,本轮只标注不动）**：
- config-automation 脚本族（config_generator.py 等 7py 的 S1/S4 缺口）→ **裁决③（退役）**,退役即整体消解。
- doc-writer.md（已 DEPRECATED 标注）删除 → **#15 裁决池**。

**独立可修（我域,走收口批 Theory+Design 双评审）**：
| 项 | 文件 | 改动 | 分级 |
|---|---|---|---|
| P1-a | config-answer/SKILL.md | when_to_use 补 SKIP when: 子句 | P1 |
| P1-b | ist-compile-engine/references/ | 目录改单数 reference/ + 调用点(loader 注入面,与 #20 联) | P1 |
| P1-c | test-list-review/memory_adapter.py | 补 try/except（或标注内部 helper 免责） | P1 |
| P1-d | 多文件 frontmatter | user-invocable/allowed-tools/model/inherit 键补齐一致 | P1 |
| P2-a | test-list-review/SKILL.md:3 | desc "Trigger phrases"→"Trigger keywords" | P2 |
| P2-b | ist-compile-engine/references/ | theory-map/removed-rules 从 SKILL.md 链接或标 maintainer-only | P2 |

**立项（超收口批,需决策）**：E2/E3 per-skill 评估集+多模型测试。

---

**执笔纪律声明**：机械事实经子 agent grep 取证（file:line），关键项（Trigger phrases 残留、config-answer 缺 SKIP、C1 无时效性条件）我 firsthand 复 grep 坐实;P0=0 是硬性规则全过的如实结论非回避;冻结面项只标注归属不改。矩阵全 35 要求逐条判定、例外逐一点名、N.A. 记理由（P3/MCP1），未挑高价值项。
