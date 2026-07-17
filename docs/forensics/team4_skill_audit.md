# team4 skill 设计规范审计 + Langfuse 本轮编译观测（任务 #7/#8）

> 2026-07-17,LLM-Eng(team4)。**只读审计,零代码改动**;修复建议仅列方向,由 main 统一分配。
> 对象:`main/ist_core/skills/` 全部 14 个 skill(SKILL.md + references + 包内脚本)+ `main/ist_core/agents/` 全部 9 个 agent md + `tools/device/grade_extract_script.py`。
> 基线:`docs/skill_authoring_standard.md`、`docs/AUDIT_skill_standard_alignment.md`(2026-07-04 第一轮)、`docs/AUDIT_skill_bestpractice_v2.md`(2026-07-09 第二轮,B1-B5 修复清单)、机器门 `tests/ist_core/skills/test_skill_package_standard.py`。
> 判定纪律:机器门已覆盖项(frontmatter 完备/名字字符集/≤500 行/markdown 链接存在性/包内禁 tests//agent 骨架)全部实测通过,一笔带过;既有裁决的例外(when_to_use 中文触发词、`[未在文档直接命中]`/`Verdict:` 类机读令牌、user-facing 模板中文)**不作违规报**。本报告只报增量问题。

## 0. 摘要

| 级别 | 数量 | 一句话 |
|---|---|---|
| P1 | 3 | ① skill 包内 reference 对 agent 是**死链**(main/ 平台黑名单,实测复现);② config-automation **执行模型坏死**(工具签名/管线/白名单三处互相矛盾);③ device-verify 内嵌"正确命令表"违「零写死领域命令」红线 |
| P2 | 6 | 语言分层残留(4 文件+2 单词+装配面);doc-writer.md 死资产;V8 拓扑门缩水(SKILL phases 无门);Trigger keywords/phrases 措辞分裂;标准文档与现实漂移;write_todos 白名单缺位 |
| P3 | 5 | compile-worker.md 具体命令例证(红线张力,建议 redline 裁决);ist-verify checklist 未补(v2-B2 半落地);ssh_template 无 paramiko 声明;config-answer-draft epolicy 命令写死(窄桥可接受,记录);ip_mapper 网段硬编码 |
| Langfuse | — | 本轮实跑观测:worker 行为全绿(检索链/门自纠/尾块契约/断言溯源);遗留:emit 首发打回延续(yzg#6 同型)、trace 匿名(yzg#2 未修);ask/attributor 本时段无场景 |

五个重点 skill(ist-compile-engine / compile-worker / compile-attributor / ist-verify / test-list-review)整体质量高:B1-B5 修复绝大部分已落地(英文化/第三人称/Step 统一/锚点连号/尾块 STATUS:/ARTIFACT:/VERDICT: 英文契约/checklist 补 device-verify),theory-map/removed-rules 的「规则须溯源+删减留档」纪律是超出官方标准的好实践。问题集中在**外围 skill(远端并入未过分层)与基础设施缝隙(沙箱×渐进披露、门缩水)**。

---

## 1. P1 发现(影响 LLM 行为正确性 / skill 可用性)

### P1-1 skill 包内 reference 文件对 agent 是死链(渐进披露 L3 层结构性失效)

**现象**:`_agent_roots()` = knowledge/data + workspace(+inputs) + framework mirror + session/user(`tools/deepagent/file_tools.py:34`),`main/` 在 `_PLATFORM_DENIED_TOP_LEVEL` 黑名单。skill 包内引用文件全部位于 `main/ist_core/skills/...` → agent 的 `fs_read` 一律被拒。

**实测复现**(本审计执行):
```
fs_read("main/ist_core/skills/device-verify/reference/ssh_template.md")
→ error: path is in platform-denied directory: main/
fs_read("main/ist_core/skills/ist-compile-engine/references/contracts.md")
→ error: path is in platform-denied directory: main/
```

**受影响面**:
1. `device-verify/SKILL.md:42-44` 指引 "References (**read directly**, no indirection)" 列出 ssh_template.md 与 apv_ssh_client.py 两个路径;Step 4(L132)再次指引"following …/ssh_template.md"——LLM 照做必收沙箱拒绝。
2. `invoke_skill`(`tools/skills/__init__.py:93-106`)对 inline skill 注入 `<skill_references note="按需 fs_read,不必全读">` 列出 `main/ist_core/skills/<skill>/reference/*` 路径——**该机制自设计起与沙箱矛盾**,列出的每条路径都读不到。
3. `ist-compile-engine/SKILL.md:39` "machine contracts are documented in `references/contracts.md`"——main agent 侧同为死链(影响弱于前两者:engine 自跑,该文件主要给维护者)。
4. 机器门盲区:`test_skill_package_standard.py:101` 只验"文件存在"(维护者视角),不验"agent 可读"(运行时视角);且只匹配 markdown 链接 `](...)`,device-verify/ist-compile-engine 的反引号引用不进门。

**旁证**:编译链正确地把全部 LLM-facing 参考放在可读根下(`knowledge/data/compile_ref/EXCEL_FUNCTIONS.md`、`domain_grammar.json`、framework mirror)——说明约束已知,device-verify 的 reference/ 是历史遗留未搬。

**修法方向**(供 main 裁):① LLM-facing 参考迁 `knowledge/data/`(compile 链既有样板)或把 skills 目录加入只读根;② `invoke_skill` 注入面同步(要么内联 reference 内容、要么修根);③ 补门:SKILL.md 正文中指引 agent 读的路径必须落在 `_agent_roots()` 内。

### P1-2 config-automation 执行模型坏死(文档承诺与三处现实互相矛盾)

**现象**:`config-automation/SKILL.md` 的执行契约在当前架构下无任何路径可实现。

| SKILL.md 承诺 | 现实 | 证据 |
|---|---|---|
| L33 `invoke_skill(skill="config-automation", config_text="<完整配置文本>")` | `invoke_skill` 实签名 `(skill: str, brief: str = "")`,**无 config_text 参数** | `tools/skills/__init__.py:25` |
| L36 "A single call performs all replacements. The returned `Pipeline Execution Result` JSON contains: ip_mapping / config_script / verify_script / output_files" | inline skill 的 invoke_skill **只返回 SKILL.md 文本**,不执行任何管线 | 同上 L83-107(fork 才执行,inline 直接回文本) |
| L69 "The Python pipeline (`config_generator.py`) performs the mapping automatically" | `config_generator.py` 全仓**零消费方**(唯一 grep 命中是 tool_gating 的组映射);CLI 形态(argparse)需 shell 跑,但 allowed-tools 仅 `[fs_read, fs_write, fs_grep, fs_ls]`,**无 run_python/run_shell** | 全仓 grep;SKILL.md:9 |

即:LLM 被 when_to_use 触发后,照文档调用会传一个不存在的参数;即便调通也只拿回文档本身;想手工跑管线又没有执行工具授权。这是「文档描述旧机制(疑似曾有 python 直连管线),机制换代后文档未跟」的典型漂移。

**修法方向**:三选一由 main 裁——① 按现实重写 SKILL.md(LLM 读拓扑 JSON 自行替换,fs_write 落盘,config_generator 退役);② 补 run_shell 授权+改为"执行脚本"型 skill(官方 scripts 模式,声明执行语义);③ 整个 skill 与死管线一并退役(功能已被 compile 链 env_facts/emit 覆盖的话)。

### P1-3 device-verify 内嵌"正确命令表"——「零写死领域命令」红线违规

**现象**:`device-verify/SKILL.md:102-116` Step 3 内嵌 9 条具体 show 命令的"Verified correct commands"表(`show slb virtual all` / `show slb group method` / `show sdns listener` / `show running` …),并加"**use the exact commands from the table; never simplify**"与 Forbidden 段(禁写 `show slb group` 等简化形)。

**为什么是违规而非护栏**:CLAUDE.md 红线「零写死领域命令:prompt 里不出现具体设备命令;该探/该断言哪条命令,靠 LLM 查手册/先例/footprint 得出」;2026-07-13 用户裁决(destructive-command-killed-beds)只豁免两类——机械可推导引用与**安全边界禁令**。同文件的高危黑名单(L46-58)属后者,合规;但 Step 3 的命令表是**经验性命令知识**(哪条命令观察哪个对象),恰是裁决点名"一律走判例层(footprint),由 worker 检索后自主查手册决策"的那一类。表格会随 build 漂移(`show slb group method` 在未来版本变形时此表静默教错),这正是「参考文档只写机制,数据按引用」要防的。

**附带**:L44 写死 `APV_DEVICE_IP` (default 172.16.34.70)、L81 "APV0: 172.16.34.70 / APV1: 172.16.34.71"——拓扑数据内联(同一行明明已指引从 network_topology_rag.md 现查),换床即漂移。

**修法方向**:命令表整体删除,改为机制句("grep 手册确认每条命令的完整形态,注意省略尾参数会丢关键列——footprint 中有已验证形态");"never simplify"的实证教训入 footprint 判例层;具体 IP 改按引用。表格删除前建议 redline-reviewer 复核一次(该 skill 未列入其触发范围,属盲区)。

---

## 2. P2 发现(一致性 / 维护性)

### P2-1 语言分层残留(2026-07-09 B3 裁决未覆盖面)

| 位置 | 现象 | 说明 |
|---|---|---|
| `skills/doc-authoring/SKILL.md` | description + 正文全中文 | origin/main 2026-07-16 并入的远端新资产(见 tool_gating.py:66 注释),未过 B3 分层。其中「默认模板」「失败处理」的**输出文案**中文属例外(交付物模板),但指令区("必须先执行知识检索"等)是 LLM-facing |
| `skills/report-gen/SKILL.md` | 同上 | 同上 |
| `agents/doc-writer.md` | task/rules 全中文 | 同批远端资产 |
| `agents/report-generator.md` | task/rules 全中文 | 同上 |
| `agents/compile-worker.md:46` | "the concrete**替代** steps" | 单词级混杂(B3 精翻漏网) |
| `agents/compile-attributor.md:88` | "a MISS (no**同构** record anywhere)" | 同上 |
| fork 装配面 | Langfuse 实测:worker system prompt = `<inherited_rules>`(**中文**,来自 _prompt.py)+ agent md 骨架(**英文**) | 单条 system 内中英拼接。CLAUDE.md 分层条款点名"skill/agent md 正文与 description"英文,未点名 _prompt.py 共享块——是刻意保留还是遗漏,建议交用户裁决后要么翻译 inherited 块、要么在 CLAUDE.md 把主提示豁免写明 |

### P2-2 doc-writer.md 是死资产

全仓 grep(main/ + tests/)零消费方;`doc-authoring/SKILL.md` frontmatter `agent: document-author`,两文件内容高度重叠(document-author 为演进版:多 model: opus、多 wx_read_doc、CLI Safety 更严)。doc-writer.md 是旧版残留,建议删除(或注明弃用原因)。同类:`test-list-review/scripts/sanity_check.py`(499 行)已被 `tools/skills/__init__.py:9` NOTE 明示废弃("verifier subagent 自发 grep 探索,不再依赖机械扫描脚本"),但文件仍在包内,grade_extract_script.py 还把它当"模式参考"引用——保留则应标注 deprecated,否则新维护者会当活资产维护。

### P2-3 V8 拓扑门缩水:SKILL frontmatter phases 无人看守

CLAUDE.md 承诺"拓扑门断言图↔SKILL↔NODE_TYPES **三方**一致";V8 实际门 `tests/ist_core/compile_engine_v8/test_topology.py` 只断言 graph↔NODE_TYPES **两方**,全 tests 无一处读 `ist-compile-engine/SKILL.md` 的 `engine.phases`。本审计手工比对:当前 11 phases 与 NODE_TYPES **内容全同、序全同**(无漂移),但下次图改动时 SKILL 声明会静默过期。修法:test_topology 补一条 frontmatter 比对断言(YAML 读 phases == list(NODE_TYPES)),同时把 `engine.graph` 指针 `compile_engine_v8.graph:graph` 的可导入性纳入。

### P2-4 `Trigger keywords:` vs `Trigger phrases:` 措辞分裂

标准(`skill_authoring_standard.md:82-84`)明确"统一用 `Trigger keywords:`"(listing 提取按行首字面串匹配,phrases 兼容但不推荐)。现状:keywords 派 5(ist-compile-engine/ist-verify/config-answer/escalate-when-stuck/compile 链),phrases 派 5(test-list-review/config-automation/device-verify/doc-authoring/report-gen)。一次 sed 级统一。

### P2-5 标准文档与现实漂移(skill_authoring_standard.md 过时)

| 标准条款 | 现实 |
|---|---|
| `allowed-tools` 必填(字段表 YES) | 仅 4/14 skill 有(test-list-review/config-answer/config-automation/device-verify);fork 类 tools 正确地活在 agent md,inline 的 ist-verify/escalate-when-stuck/doc-authoring/report-gen 无。机器门也不查 |
| 目录规范只写 `reference/`(单数) | ist-compile-engine 用 `references/`(复数);invoke_skill 注入代码只认单数(`__init__.py:93`)→ 复数目录永不进 `<skill_references>`(在 P1-1 修复前这反而是歪打正着,修复后需统一) |
| 无 `effort:` 字段 | 8/14 skill 在用(loader 消费) |
| §五 skill listing 文案 | 与 per_turn_skill_reminder 现实现大体同步,但 name-only 降级、`.skill_overrides.json`(compile-worker/attributor name-only)未写入标准 |

修法:标准文档一次性对齐现实(allowed-tools 降为"建议"、补 effort/overrides 语义、单复数定死一个)。

### P2-6 test-list-review Step 0 依赖白名单外工具

`SKILL.md:52` Step 0 (mandatory) 要求第一步调 `write_todos`,但 frontmatter `allowed-tools`(L11)不含它。白名单虽是指引性,文档自相矛盾会让严格遵守白名单的模型跳过必做步。补进白名单即可。

---

## 3. P3 观察(记录,低优先)

1. **compile-worker.md 嵌具体命令例证(红线张力点,建议 redline-reviewer 裁决)**:L64-66 "a persistence defect shows on the reload path (`show startup`), never on the save artifact"——括号例证实际教了"persistence 类断言读哪条命令",按红线字面属领域判断答案;L136-139 `show sdns listener` 回显形态 + 667986 正则实录属失败叙事锚(允许类)。前者与 theory-map.md 的规则溯源纪律(③类 measured failure)有辩护空间,但 `show startup` 与 GA-CUT 教训里"算法类补 show statistics"的形态相似度高——不下结论,提请专项裁决。
2. **ist-verify 无 workflow checklist**:v2 审计 B2-7 计划"ist-verify / device-verify 补可复制 checklist"——device-verify 已补(L60-73),ist-verify(Steps 1-8,最长流程之一)未补。半落地。
3. **ssh_template.md 无 paramiko 可用性声明**(v2 审计 B1-4 计划项,未落):模板直接 `import paramiko`,未注明"框架环境自带/需确认"。
4. **config-answer-draft.md L35 写死 epolicy 三命令**(import/attach/class):F5 iRule→APV epolicy 是唯一正确翻译路径(低自由度窄桥),且命令经 build_command 文法闭集生成,判可接受;记录在案以防被复制成通用模式。
5. **ip_mapper.py:22-31 硬编码环境网段**(172.16.32-35.0/24)与 SKILL.md:64 "not inlined here — single source of truth is the topology JSON"自相矛盾;随 P1-2 处置一并解决。

---

## 4. 逐 skill × checklist 矩阵

图例:✅ PASS / ❌ FAIL / ⚠ 部分 / — N.A.。列:C1 描述具体含领域术语 · C2 功能+何时用 · C3 ≤500行 · C4 详情在单独文件 · C5 无时效性 · C6 术语一致 · C7 示例具体且合规(输出形态允许/领域答案禁) · C8 引用一层深 · C9 渐进披露适当 · C10 工作流清晰。

| skill | C1 | C2 | C3 | C4 | C5 | C6 | C7 | C8 | C9 | C10 | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ist-compile-engine | ✅ APV/SLB/SDNS/mindmap/case.xlsx | ✅ | ✅ 52 | ✅ references/×3 | ✅ run13 为实证锚非条件 | ✅ | ✅ ask 三边形态 | ✅ | ⚠ references 复数目录不进注入+死链(P1-1/P2-5) | ✅ 引擎自跑,恢复动作边界写清 | frontmatter phases 无门(P2-3) |
| compile-worker | ✅ case.xlsx/assertions(fork 不参与发现) | ✅ desc 承担(fork 无 when_to_use,合理) | ✅ 46 | ✅ 指 EXCEL_FUNCTIONS/grammar(knowledge/ 可读根,落位正确) | ✅ "40 of 46 measured"为实证 | ⚠ SKILL 用 orchestrator、agent md 用 main agent/engine 三词同指 | ✅ 双尾块 examples 教科书级 | ✅ | ✅ | ✅ | agent md 见 P2-1/P3-1 |
| compile-attributor | ✅ G/E/V/transient/defect/submit_attribution | ✅ | ✅ 8(骨架全在 agent md,分层正确) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | agent md L88 混杂(P2-1) |
| ist-verify | ✅ APV/SLB/SDNS/RUNTIME/四层归因 | ✅ | ✅ 144 | ✅ mirror/EXCEL_FUNCTIONS 按引用(可读根) | ✅ | ✅ | ✅ 报告模板=输出形态 | ✅ | ✅ | ⚠ 无 checklist 块(P3-2);Steps+Success criteria 齐 | 递归上限 300 等为机制事实 |
| test-list-review | ✅ APV/SLB/SDNS/HTTP/IPv6/P级 | ✅ | ✅ 193 | — 正文自足 | ✅ | ✅ Step 0-8 已统一(v2-B1 落地) | ✅ brief 结构模板 | ✅ | ✅ | ✅ | Trigger **phrases**(P2-4);write_todos 白名单缺(P2-6) |
| review-verifier | ⚠ 流程术语有、产品域词无(fork 可接受) | ✅ | ✅ 23 | ✅ | ✅ | ✅ | ✅ 输出骨架 | ✅ | ✅ | ✅ | VERDICT/LEVEL 契约与 review_gate 对齐 |
| config-answer | ✅ APV CLI | ✅ | ✅ 51 | — | ✅ | ✅ 步骤已连号(v2-B1 落地) | ✅ | ✅ | ✅ | ✅ | `[未在文档直接命中]` 为裁决保留令牌 |
| config-answer-draft | ✅ | ✅ desc | ✅ 17 | ✅ | ✅ | ✅ | ✅ 中文输出模板=user-facing 例外 | ✅ | ✅ | ✅ | agent md epolicy 表见 P3-4 |
| config-answer-verifier | ✅ | ✅ desc(Step 3 锚点已修) | ✅ 21 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | |
| config-automation | ✅ | ✅ | ✅ 74 | ⚠ 管线代码即"详情"但已死 | ✅ | ✅ | ❌ 调用示例与工具签名不符(P1-2) | ✅ | ⚠ | ❌ 执行流程不可执行(P1-2) | Trigger phrases(P2-4) |
| device-verify | ✅ | ✅ | ✅ 188 | ⚠ reference/ 死链(P1-1) | ✅ | ✅ | ❌ 命令表=领域答案禁类(P1-3) | ✅ 已拍平(v2-B2 落地) | ⚠ | ✅ checklist 已补 | 黑/白名单=安全边界,合规 |
| escalate-when-stuck | ✅ case.xlsx/check_point/弱断言 | ✅ 第三人称已修(v2-B1) | ✅ 39 | — | ✅ | ✅ | ✅ 形态方向不写命令 | ✅ | ✅ | ✅ 4 步诚实出口 | 质量高 |
| doc-authoring | ❌ 中文+无产品域词 | ⚠ when_to_use 有 | ✅ 150 | — | ✅ | ✅ | ✅ 模板=输出形态 | ✅ | ✅ | ✅ | P2-1 语言分层 |
| report-gen | ❌ 同上(有"测试报告"弱域词) | ⚠ | ✅ 58 | — | ✅ | ✅ | ✅ 枚举契约 | ✅ | ✅ | ✅ | P2-1 |

agents/*.md 补充:9/9 过骨架门与 metadata 门;`explore.md` 名字小写已修(v2 遗留项落地),`inherit-parent-prompt: false` 显式声明 ✅;doc-writer/report-generator 缺 `model:` 字段(其余 7 个都有,非必填,一致性观察);wx_*/report_to_doc 工具实测存在(wecom_bot_smart/doc_tool.py 经 main_agent.py 注入 fork registry),白名单可解析 ✅。

## 5. 脚本类 checklist 矩阵

列:S1 解决问题不推卸 · S2 错误处理明确 · S3 无巫术常量 · S4 依赖列出可用 · S5 文档清晰 · S6 无 Windows 路径 · S7 关键操作有验证 · S8 反馈循环。

| 脚本 | S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 | 判定 |
|---|---|---|---|---|---|---|---|---|---|
| tools/device/grade_extract_script.py(566 行) | ✅ 确定性信号,终判留给上机 | ✅ exit 0/1+可读错误 | ✅ 每个正则常量带"为什么"注释,词面全在 domain_grammar.json | ✅ 仅项目内+openpyxl | ✅ docstring 含原理→信号映射表+红线声明 | ✅ | ✅ 与 confidence_f 共用单一事实源防漂移 | ✅ 511 卷等价反扫验收器 | **典范** |
| device-verify/scripts/apv_ssh_client.py(259 行) | ✅ | ✅ CLI 错误 marker 收口共享模块+独立加载回退(一致性注释) | ⚠ timeout=10/15 无注释 | ✅ paramiko 顶部 import | ✅ | ✅ | ✅ 有 pytest(test_apv_ssh_client_cli_error) | ✅ | 良好;唯 SKILL 侧引用它是死链(P1-1) |
| config-automation/config_generator.py + utils/ + modules/(~880 行) | ⚠ verify 脚本生成的是占位注释 `# show running-config`(推卸给使用者) | ❌ 文件不存在直接 traceback | ⚠ ip_mapper 网段硬编码(P3-5);.50 起跳有注释 ✅ | ⚠ 裸 `from utils import`(仅 CWD=包目录可跑) | ✅ | ✅ | ❌ 无验证步骤 | ❌ 零消费方零测试 | **死管线**(P1-2 一并处置) |
| config-automation/scripts/smoke_config_generator.py | ✅ 诚实自述"手工冒烟,无断言" | ✅ | ✅ | ✅ | ✅ | ✅ | — | — | 合格(随管线处置) |
| test-list-review/scripts/sanity_check.py(499 行) | ✅ 6 类机械扫描设计合理 | ✅ | ✅ _MAX_LOCATIONS=20 截断有说明 | ✅ | ✅ | ✅ | — | — | **已废弃未标注**(P2-2) |
| test-list-review/memory_adapter.py | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ 有测试 | ✅ | 活资产,合格 |

---

## 6. Langfuse 观测:本轮编译 LLM 调用质量(任务 #8)

**通道**:自托管 Langfuse(`environment` 中 LANGFUSE_BASE_URL=lilizeze.synology.me:3443,已从先例的 jp.cloud 迁移),REST API basic auth 可达;本机无 node,langfuse-cli 不可用,改 curl 直连(等价)。观测窗:UTC 2026-07-16 15:54 起(本地 JST 07-17 00:54,Test-Eng 任务 #2 第一批 `CNAME pool支持ipo算法_dongkl` R1 编写轮),交叉对照盘上 fastlog(`compile_evidence.94478.live.log`)。

### 6.1 总体形态

- **模型**:全部 GENERATION `model=deepseek-v4-pro`(与 yzg 先例的 mimo-v2.5-pro 不同——本轮 provider 已切 DeepSeek,记录为环境事实)。
- **规模**(观测窗前 100 GENERATION):in 3.07M / out 63.5k tokens;单 worker fork 4-20 次 LLM 调用,in 83k-366k、out 2-9k。逐轮全量重发前缀的 agent-loop 形态正常,无爆量 trace,无 runaway 循环。
- **trace 结构**:8 个 worker fork 同刻并发起跑(15:55:41,引擎 author 节点扇出),单 fork 时长 3.5-5.5min。

### 6.2 worker 行为质量(抽 2 个已完成 trace 全序列复盘)

**035453(GA 算法案,20 gens)与 035608(15 gens)行为全绿**:

1. **检索链教科书级、零写死命令**:manifest 原文 → `kb_footprint`(5-6 个不同命令前缀)→ `domain_grammar.json` → 手册 glob/grep → 手册精读(带 offset 续读)→ `dev_probe`/`dev_help`(9 次语法确认,含逐参数试探 `sdns host pool "www.a.com" "cname1" "cname2"`)→ `compile_emit`。与 compile-worker.md 的 retrieval order 完全一致,红线(命令均本轮检索所得)实证遵守。
2. **断言溯源手册带行号,无 observe-then-assert**:最终 rationale 引 `app_10.5_Chapter25.md:125`、`cli_10.5_Chapter20.md:436/1057` 支撑 GA 优先级断言;035608 的 not_found 断言给出完整因果链(disable service → GA 判 CNAME 池不可用)。
3. **门反馈自纠环生效**:两 trace 的 `compile_emit` 首发均被打回(035453 打回 1 次、035608 连打 2 次),worker 均转读 `EXCEL_FUNCTIONS.md` 后重 emit 成功——**emit 首发打回延续 yzg 问题#6 形态税**(42% prov_parse 基线),与 `blocks-combinator-prompt-unclear` 记忆吻合:门能自纠不阻断,但 blocks/provenance 首发正确率仍是 prompt 优化方向。
4. **尾块契约 100%**:`STATUS: produced` + `ARTIFACT: workspace/outputs/<autoid>/case.xlsx`,格式分毫不差(引擎 reconcile 可机读)。
5. **思维链健康**:reasoning_content 英文、推进型("Now I have all the command syntax. Let me now probe…"),无空转/无绕门意图/无自我评估越权(worker 不自评,emit 过门即收尾,符合 skill 约束)。

### 6.3 发现与遗留

| # | 现象 | 判定 |
|---|---|---|
| L-1 | **trace name 匿名问题(yzg#2)未修**:同一 fork 双挂载点一名一匿(本轮 14 traces 中 8 个 `(anon)`),批量检索仍靠时间戳对位 | 可用性遗留,不影响数据完整性;修法同先例建议(CallbackHandler 按 autoid/节点命名) |
| L-2 | emit 首发打回 2/2 抽样 trace(1-3 次/卷) | yzg#6 同型;门自纠有效,首发正确率待 prompt/blocks 改进(与 run19 观察一致,记录不改) |
| L-3 | fork system prompt 实测 = `<inherited_rules>` 中文 + agent md 英文拼接 | 语言分层装配面观察 → 已并入 P2-1 |
| L-4 | ask 问题生成 | 本批 R1 零 NEEDS_USER_DECISION、归因轮 3 案全部 `ASK: none`——**无 ask 场景**,如实记录不臆测;TUI ask 交互质量由 Test-Eng 的 cmux 通道覆盖 |
| L-5 | token 消耗 | 无异常:worker 单案 in 中位 ~250k,较 yzg(mimo)单案 ~500k 低;attributor in 270k-563k(563k 者按 brief 指引读了 4 个兄弟案 attr_evidence+手册,属跨案核查成本);out/in 比正常,无思考截断迹象 |
| L-6 | **submit_behavior_fact 被锚门拒 ×2,attributor 未重试即收尾** | 035644(observe_cmd=`dig @…`)与 035453(observe_cmd=`sdns pool disable …`)均被拒:"observe_cmd is not among this case's APV commands on the sheet"。门行为正确(行为知识必须锚定卷面实际观察命令),但两个 attributor 都没对准锚、且被拒后 6s 内直接 final——**行为观察入库失败即蒸发**(agent md「Side duties」只说 "file via submit_behavior_fact with grounds",未说明 observe_cmd 的卷面锚约束)。P3:compile-attributor.md 补一句锚约束,或工具 docstring 前移该契约 |
| L-7 | **attributor 输出语言不稳定**(一英一中) | af818019 全英文、bebdd2d7 全中文(「分析总结/归因逻辑」)——compile-attributor.md 无 Language 指示(review-verifier/explore 均有 "Reply in English" 节)。VERDICT/ASK 尾块两者都正确,引擎解析不受影响;但与 B3 分层(LLM-facing 英文)不一致。P3:agent md 补 language 节 |

### 6.4 归因轮观测(UTC 16:11-16:14,3 attributor forks,补充)

批 1 上机(整卷 11 case 单跑,600s 窗)收束后 3 个 attributor fork 并发起跑,**3 traces 全部完整落库**(af818019 17 gens / bebdd2d7 8 gens / 6249a80f[匿名] 12 gens,首尾齐含最终输出)。抽 2 个全序列复盘,**行为与 compile-attributor.md 契约高度吻合**:

1. **quote-first 落实**:两案最终输出均以 verbatim quotes 块开头(设备回显/`Fail Num`/`Success Num` 行原文)。
2. **layer descent 逐层走**:version(读 show version 对 build,`10.5.0.585` 无 `^`)→ config-realized(A/AAAA 解析链逐段核对)→ 跨案一致性 → E 自检 → five checks。**yzg R2 归因教训的行为面已改善**:035453 案判 E 排除时引用「同案 1 个检查点通过 + dig `SERVER:` 行有应答 + 同批 6 案通过」三重证据(正是 yzg 655154「不可达」误判点名的裁决方式);035453 判 G 时明确「断言失败是语法拒绝的**下游后果**」(G 上游根因纪律)。
3. **跨案一致性核对真实发生**(yzg 复盘点名"值得机械化"的项,本轮 attributor 自发做了):035453 案对比兄弟案 035373 的 `sdns pool disable` 成功,推出「常规池 vs CNAME 池不支持 disable」的精确差异;035644 案读 3 个兄弟案 attr_evidence + 引擎先例卷比对配置形态。
4. **证据读取纪律**:两案第一动作都是 `fs_read <autoid>/attr_evidence.json`(单案证据),跨案用 fs_grep——遵守 agent md「do NOT fs_read the whole last_run.json(3.3x token burn)」约束。
5. **尾块契约 100%**:`VERDICT: V/reflow`、`VERDICT: G/reflow`、`ASK: none`,fix_direction 具体可执行(逐选项给替代机制)。
6. 遗留见 6.3 表 L-6(behavior_fact 锚门拒 ×2 未重试)与 L-7(输出语言一英一中)。

### 6.5 域内事故:「⚠ Langfuse 上报有失败」告警调查(leader 指派,已闭环)

**现象**:TUI footbar 自 01:12(JST)起常驻黄字「⚠ Langfuse 上报有失败,追踪可能不完整」(批 1 归因阶段)。

**根因(一手证据链)**:
1. `runtime/logs/tui.log` **全文仅 2 条 ERROR**(01:12:37 / 01:13:24 JST):`opentelemetry…trace_exporter: Failed to export span batch … Read timed out. (read timeout=4.999…)` ——OTLP span 批量导出撞 **5 秒读超时**。
2. 超时值来源:langfuse SDK v3 `LANGFUSE_TIMEOUT` **默认 5s**(`langfuse/_client/environment_variables.py:141-148`,environment 未设此变量)——与日志 4.999s 吻合。
3. 时机吻合:两次失败恰在 3 个 attributor fork 收尾、span 集中 flush 的窗口(16:12-16:13Z);自托管 Langfuse(synology)本审计实测 `/health` 都要 **2.09s**,大 batch 上传+入库超 5s 完全可能。
4. **告警是粘性的**:`observability.py:63-68` `_OtelExportErrWatch` 首次 ERROR 即置 `export_failing`,**无恢复清除机制**(设计意图"盲跑必须可见",2026-07-10 ¥96 盲跑实证背书)——16:15:00Z 起新 trace 已恢复成功入库,但黄字常驻,易误读为持续断流。

**影响面**:
- **主链路零影响**(不升 P0):OTLP 导出在后台线程,fastlog 显示 16:12-16:14 归因工具调用连续推进、submit_attribution 均落盘;失败只丢当批 span(read-timeout 属不可重试类,该 batch 丢弃)。
- **观测缺口很小**:trace 级 **21/21** 对齐引擎侧 fork 事实(events.jsonl 20 fork + 主链);3 个归因 trace 的 GENERATION 链首尾完整(含 VERDICT 尾块);丢失限于 2 个 batch 内的部分中间 span(丢失内容不可见,无法逐 span 对账——如实声明);16:15Z 后恢复正常。本报告各节结论不受影响。
- **定性:我们的配置缺口为主**(先怀疑自己):`LANGFUSE_TIMEOUT` 未按自托管慢后端调优(默认 5s 是对 cloud 的假设);服务器响应慢(synology,2s+ 常态)是环境侧放大因子。
- **修复建议**(并入 #19/#15):① P2:`environment`(及 environment.example §Langfuse 节)加 `LANGFUSE_TIMEOUT=30`(一行,零代码,已落地——见 8-bis 表);② P3:footbar 告警带失败计数+末次时间,或导出恢复后自动降级——现粘性告警无法区分「偶发丢批」与「持续断流」。

### 6.6 批3 实弹验证 + 批2 引擎中断因果定论(leader 指派 #8 收尾,2026-07-17)

**(1) 批3 实弹通过**:批3 新进程(PID 83994,≥17:00)全程零黄字 banner;`tui.log` mtime 停 14:48(批3 零写入=零 OTLP 失败)。`LANGFUSE_TIMEOUT=30` 生效。

**(2) 批2 断网性质(非我们代码)**:tui.log 批2 段 14:45-48 四条 OTLP 均 `[Errno 8] nodename nor servname provided`=**DNS 解析完全失败**=本机网络全断。与批1 的 `Read timed out(5s)` 是两种形态:批1=慢后端单次超时(30s 修的对象);批2=断网 max-retries 耗尽(任何超时值都救不了,属预期)。

**(3) 「14:47 引擎异常」= tui.log 唯一行是 Langfuse OTLP,非引擎**:`grep "14:47" tui.log` 仅 1 行=OTLP 失败;全 tui.log 6 条 OTLP+34 空行,零 Traceback。引擎中断的证据**不在 tui.log**(它只收 stderr),"14:47 引擎异常"是下面(5)那组现象的转述,非独立日志行。

**(4) Langfuse 传导路径架构层排除(铁证,无论引擎是否中断均成立)**:Langfuse span 导出跑在 OTEL BatchSpanProcessor 独立守护线程(`LangfuseSpanProcessor(BatchSpanProcessor)`,`langfuse/_client/span_processor.py:37`;tui.log "Failed to export span **batch**" 即该后台线程签名),失败只写 stderr、不 raise 回引擎主线程;加 `observability.py`/`langfuse_sink.py` 全 best-effort try/except(#8 已核)=**线程边界+异常边界双重物理隔离**。批2 可观测性 4 轮全挂期间引擎主链路不受其影响——best-effort 隔离设计的天然压测背书。

**(5) 引擎中断真实证据在 fastlog 94478,分两通道按证据等级如实记**(leader 首诊 + 我 firsthand 复核):
- **LLM 通道(我 fastlog 复核坐实)**:`compile_evidence.94478.events.jsonl` 有 **12 条 `"error":"Connection error."`**,全部 `calls:0, ai_rounds:0`(零 LLM 往返=连接建立阶段即失败=本机网络已死),`elapsed_s` 分布 1.3s×6 / 1.4s×4 / 1.5s×2=重编 fork 断网期连续秒失败。`calls:0` 是铁证:失败在连接层,与下游(含可观测性)无关。
- **SSH/digest 通道(leader 首诊,我未在 fastlog 独立定位该串)**:leader 亲诊子集上机 digest 返回 `[Errno 51] Network is unreachable` + 屏面 turn Cooked。我 grep fastlog 94478 未命中 `Errno 51`/`Network is unreachable`/`Cooked`(该文件 2 条 "unreachable" 系无关的 compile_emit 引用校验错误)——故此条以 leader 首诊/digest 返回值面为准,非 fastlog 落盘串。

**归因定论**:引擎中断 = LLM API 通道(fastlog 铁证)+ SSH 通道(leader 首诊)**随本机断网直接失败**,与 Langfuse 失败是**同一「本机断网」根因的并列后果,非 a→b 传导**;引擎错误经 fastlog fork_end / 屏面呈现、不落 tui.log stderr 属预期。**三层锁定**:①14:47 tui.log 唯一异常=Langfuse OTLP;②Langfuse 传导架构层物理排除;③引擎中断=自身 LLM/SSH 通道断网直接失败(LLM 侧 fastlog 坐实、SSH 侧 leader 首诊)。#8 因果定论干净收口。

---

## 7. 已合规项(一笔带过,不展开)

机器门 7 断言全过(本审计跑读为主,未重跑 pytest,以文件实态核对);B1-B5 已落地项:5 目录连字符化+别名、_prompt.py XML 五块、agents 9/9 role→task→rules、escalate 第三人称、test-list-review Step 统一、config-answer 连号+verifier 锚点、device-verify 引用拍平+checklist、explore 小写+显式 inherit false、机读尾块英文契约(STATUS/ARTIFACT/VERDICT,contracts.md 与实测 trace 双确认)、`.skill_overrides.json` name-only 降噪、references/(ist-compile-engine)机制-不-抄-数据纪律、removed-rules.md 删减留档、theory-map 规则溯源门。所有日期戳均为实证锚或维护者文档,无时效性条件分支。

## 8-bis. 修复执行记录(任务 #19,2026-07-17,LLM-Eng)

**合入状态(机读账核实,2026-07-17)**:本批 skill 域改动**已合入 HEAD = commit `69f8f133`**("fix(skills): team4 skill 域——config-automation…/device-verify…/语言分层…/doc-writer DEPRECATED/LANGFUSE_TIMEOUT")——批2→3 窗口合入,批3 重启已加载生效(firsthand `git log -1 -- agents/compile-worker.md`=69f8f133、`git status skills/`干净、`merge-base --is-ancestor 69f8f133 HEAD`=真)。environment 的 `LANGFUSE_TIMEOUT=30` 属 gitignored 本地文件(key 不入库,by design);environment.example 模板行随 69f8f133 入库。**先前"未 commit(归#15)"系记忆滞后**——机读账优先于记忆(全队纪律实例:我 grep 到落盘却漏查 commit 状态,leader 机读账纠正)。**批3 可观测验证边界(如实)**:compile-worker/attributor agent md(单词修复 substitute/isomorphic)由批3 每个编译 fork 加载运行(结构确证=它们即 fork agent),但单词级修复无独立行为可观测签名;device-verify/config-automation 系用户直调 inline skill、**不在编译批次链路**,批3 零实弹 touch——其正确性靠评审非实跑背书。影响面门测试 120 passed(过 skill 标准包门/prompt 结构门);全量 pytest 归 #15 统一跑(避 k_signals 生产流水污染)。

**收口批批量补审清单(leader 裁定 2026-07-17:双评审强制流程对新改动前向生效、不溯及既往;类2 已合入 69f8f133,收口批由 Theory+Design 一次性过审,非单独轮。全部 in commit 69f8f133)**:

| # | 文件 | 改动点 | 理由 | 现有背书 | 补审重点 |
|---|---|---|---|---|---|
| 1 | `skills/config-automation/SKILL.md` | 删 config_text/Pipeline JSON 错误示例,执行模型改 LLM 直接 fs_*(读拓扑→映射→替换→落盘) | 文档与 invoke_skill 实签名对齐(P1-2) | redline(未单独走)+leader 验收 | **是——批3 零实弹 touch,不在编译链** |
| 2 | `skills/device-verify/SKILL.md` | 9条 show 命令表撤除→机制句;补 kb_footprint 白名单;IP 按引用;报告示例中性化 | 零写死领域命令红线整改(P1-3) | redline 整改 clean+leader 验收 | **是——批3 零实弹 touch,不在编译链** |
| 3 | `agents/compile-worker.md` | "concrete替代 steps"→"substitute" | 语言分层单词修复(P2-1) | leader 明确豁免+**批3 全量 fork 加载实弹** | 否 |
| 4 | `agents/compile-attributor.md` | "no同构 record"→"isomorphic" | 同上(P2-1) | 同上(批3 fork 加载) | 否 |
| 5 | `skills/doc-authoring/SKILL.md` | 指令区英文化+description 补 APV 域词 | 语言分层(P2-1) | leader 验收 | 否(非编译链,WeCom 文档 skill) |
| 6 | `skills/report-gen/SKILL.md` | 指令区英文化 | P2-1 | leader 验收 | 否(非编译链) |
| 7 | `agents/report-generator.md` | 英文化 | P2-1 | leader 验收 | 否(非编译链) |
| 8 | `agents/doc-writer.md` | frontmatter description 加 `[DEPRECATED-PENDING-RULING]` 标注(**删除动作=类1冻结/#15**) | 死资产标记(P2-2) | leader 验收 | 否 |
| 9 | `skills/test-list-review/scripts/sanity_check.py` | docstring 头 DEPRECATED 标注 | P2-2 | leader 验收 | 否 |
| 10 | 5×`SKILL.md`(test-list-review/config-automation/device-verify/doc-authoring/report-gen) | `Trigger phrases:`→`Trigger keywords:` | 措辞统一(P2-4) | leader 验收+标准包门 | 否 |
| 11 | `docs/skill_authoring_standard.md` | allowed-tools/when_to_use/context/effort 如实化+reference 单数+黑框警示 | 标准文档漂移修正(P2-5) | leader 验收 | 否(纯文档) |
| 12 | `skills/device-verify/reference/ssh_template.md` | paramiko 可用性声明 | P3-3 | leader 验收+核 requirements.txt | 否(纯文档) |
| 13 | `environment.example` | LANGFUSE_TIMEOUT 注释模板行(environment 本地 gitignored) | 自托管慢后端适配 | leader 批准+**批3 实弹验证生效** | 否 |

重点两项(#1/#2)：批3 编译批次不调 device-verify/config-automation(用户直调类 inline skill),故其整改正确性目前**仅靠 redline+leader 验收背书、无实弹**——收口批 Theory/Design 需着重核这两项语义/红线一致性。其余 11 项或有批3 fork 实弹(#3/#4)、或非编译链纯文档(#5-12)、或已实弹验证(#13)。

| 项 | 处置 |
|---|---|
| P1-2 config-automation | SKILL.md 重写:删除错误 `invoke_skill(config_text=…)` 示例与 "Pipeline Execution Result JSON" 承诺,执行模型改为 LLM 直接以 fs_* 完成(读拓扑 JSON → 建映射 → 逐行替换 → 配验证命令 → 落 workspace/outputs/);映射规则(VIP .50 起跳/不占用既有 IP/示例网段闭集)保留为机制句;正文英文化,user-facing 输出格式(IP映射表等)保留中文 |
| P1-2 附:config_generator.py 处置**提案**(不动文件,待裁) | **建议退役**整条 python 管线(config_generator.py + utils/ + modules/ + scripts/smoke_config_generator.py,~880 行):①零消费方(全仓 grep 唯一命中是 gating 组映射);②无执行路径(allowed-tools 无 run_python/run_shell,invoke_skill 无参数通道);③其能力(拓扑读取+IP 映射)LLM 按重写后的 SKILL.md 直接可做,且编译主链已有 env_facts 承担同类事实投影。若保留则需补授权+改"执行脚本"型 skill(官方 scripts 模式)——不推荐,双实现漂移面 |
| P1-3 device-verify | Step 3 命令表(9 条 show)+Forbidden 段撤除 → 机制句(手册全形态+截短静默丢列后果+footprint 已验证形态优先);实证教训一般化,零具体命令。frontmatter 补 `kb_footprint` 白名单;L44/L81 具体 IP 改按引用(topology_rag 单一事实源);报告示例中性化(`<命令原文>` 占位);黑/白名单(安全边界)原样保留 |
| P2-1 语言分层 | doc-authoring/SKILL.md、report-gen/SKILL.md、agents/report-generator.md 三文件指令区英文化(description 同步补 APV 域词,顺修矩阵 C1 两处 FAIL);user-facing 交付模板/输出文案(「⚠ 待确认」「来源:」「未找到可用的测试结果」等)按裁决保留中文;compile-worker.md "concrete替代 steps"→"concrete substitute steps"、compile-attributor.md "no同构 record"→"no isomorphic record" |
| P2-2 死资产 | agents/doc-writer.md **标记待裁**(frontmatter description 改 `[DEPRECATED-PENDING-RULING]`,leader 指令——曾先删除后按指令恢复,删除裁决上呈 #15);test-list-review/scripts/sanity_check.py 头部加 DEPRECATED 标注(保留:grade_extract_script.py docstring 引用其脚本模式) |
| P2-4 措辞统一 | `Trigger phrases:` → `Trigger keywords:` ×5(test-list-review/config-automation/device-verify/doc-authoring/report-gen),与标准 §三 对齐 |
| P2-5 标准文档漂移修正 | `docs/skill_authoring_standard.md`:`allowed-tools` 必填→如实(建议性,fork 白名单在 agent md,附 5/14 现状);`when_to_use` 必填→"user-invocable 时 YES"(与机器门一致);`context` 标 YES(机器门强制显式声明);补 `effort` 字段行;目录结构注明 reference/ 单数(invoke_skill 注入只识别单数)+ **加黑框警示:给 agent 读的参考资料放 knowledge/data/ 不放 skill 包内**(P1-1 实证,沙箱级修复见 #20) |
| 附带 P3-3 | ssh_template.md 补 paramiko 可用性一行(已验证:requirements.txt `paramiko>=3.4,<4` + venv importable 3.5.1) |
| LANGFUSE_TIMEOUT=30(leader 批准) | `environment` 追加实际行(带自托管慢后端注释;bash append,全程未读/未回显 key);`environment.example` Langfuse 节加注释模板行+实证说明。**实弹验证点已交 Test-Eng:批 2 重启 TUI 后黄字警告应不再出现** |
| 红线自查(四问) | ①零写死设备命令(新增文本无任何具体命令)②无 observe-then-assert 引导 ③未触及 IP 恢复契约 ④无关键字白名单;语言分层例外(中文触发词/user-facing 文案)全部保留 |

**正式建议(记录性,#15 上呈)**:① `redline-reviewer` 触发范围建议扩展——其现范围(case_compiler / ist_compile_* / ist_verify / compile_* / agents 定义)不含 device-verify 等含设备命令面的外围 skill,P1-3 违规正是在此盲区滋生;建议改为「全部含设备命令面的 skill/agent md」。② config_generator.py 退役提案见上表(影响面:零调用方;退役时同步删 tool_gating `_SKILL_GROUPS` 的 config-automation→device 映射亦可保留 fail-safe)。

**未在 #19 范围、留待对应任务**:P1-1 死链(#20 Py-Eng+security 联审,我从 skill 消费视角复核方案);P2-3 拓扑门补断言、P2-6 write_todos 白名单、P3-1/L-6/L-7(compile-worker/attributor md 语义改动需 redline 裁决)——归 #15 汇总或后续分配。

## 8. 建议的修复优先序(供 main 分配)

1. P1-1(死链):影响所有含 reference 的 skill 的运行时行为,且修法涉及沙箱根/invoke_skill 两处基础设施——建议与 security-reviewer 联审(动 `_agent_roots` 属沙箱范围变更)。
2. P1-2 + P3-5(config-automation):先裁"修 or 退役",再动文档。
3. P1-3(device-verify 命令表):删表改机制句 + redline-reviewer 复核;顺手修 P3-3(paramiko 声明)。
4. P2-1(语言分层):doc-authoring/report-gen/doc-writer/report-generator 四文件英文化 + 两处单词修复;inherited_rules 中文与否提请用户裁决。
5. P2-2/P2-3/P2-4/P2-6:机械小修一批(删死资产/补拓扑门断言/统一 Trigger keywords/补 write_todos)。
6. P2-5:标准文档对齐现实(纯文档)。
