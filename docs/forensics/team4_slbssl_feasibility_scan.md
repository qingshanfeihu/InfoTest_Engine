# SLB/SSL 扩域可行性评估（任务 #47，风险先行）

> 用户令 2026-07-19。read-only 扫描。Py-Eng 四面(人工用例+模板函数+CLI 手册+footprint)另节;本文 = **LLM-Eng 知识层就绪度**（文法层/判例层/prompt 假设/评审入口)。

## 知识层就绪度（LLM-Eng，2026-07-19）

**一句判定**：扩域**可行、风险中低**——框架层(prompt/引擎/评审)大部分 domain-agnostic,主冷启动缺口=**文法层 slb/ssl 对象·引用形态**(中成本、可 author)+ precedent(低、自愈);footprint 已富。优先补文法层 statements。

### 点1 · 文法层（`knowledge/data/compile_ref/domain_grammar.json`）⚠ 主缺口

- **现状**：核心结构 **sdns-only**——`statements` 7 条全 DNS 对象(`service_ip_define`/`pool_service_member`/`host_pool_bind`/`host_name_define`/`cname_member_ref(_inline)`/`method_algorithm_line`)、`reference_closures` 1 条 sdns、`persistence_channels` 3 条 sdns。外围键有零星 slb(`occupancy_semantics` slb=3、`bed_l23_write_forms` slb=1)但不成对象体系。整体命中 slb=498/ssl=133 系命令清单等外围,非文法结构。
- **缺口**：**slb**(virtual service / real service / group 对象与绑定)、**ssl**(cert / profile / policy 对象)的 `statements` 对象定义 + `reference_closures` 引用形态 = **0**。这是自愈四层的**文法层冷启动缺口**——worker 编 slb/ssl 用例时无对象/引用文法可锚。
- **补法成本**：**中**。机制上是 JSON 新增条目(零代码,CLAUDE.md 自愈架构),但需**领域专家 author** slb/ssl 的 N 条 statement 形态 + 引用闭包 + provenance(比照 sdns 7 条)。**需一条流程**去填(非自然增长)。估:slb ~6-8 条 + ssl ~4-6 条 statements。

### 点2 · 判例层（compile_precedent 检索面）✅ footprint 富 / ⚠ precedent 冷启动

- **现状**：**footprint 层丰富**——2408 节点中 slb **349** / ssl **261**(sdns 314),CLI 手册已富覆盖 slb/ssl 语法·行为事实。**但** compile_precedent 的**同意图 compiled-case 先例**(retrieval 源含 outputs delivered 卷)全来自 4 批 sdns/DNS 用例(#43 语料),slb/ssl compiled-form precedent = **0**。
- **缺口**：无同意图的**已验证 slb/ssl 编译形态**可检索(precedent 冷启动);首批 slb/ssl 用例只能靠 footprint(有)+手册,不能靠 case-precedent。
- **补法成本**：**低**。precedent 是自愈层**全自动增长**——slb/ssl 用例 compile→PASS→writeback 后先例自然积累。冷启动仅影响头几例(footprint 兜底)。无需人工填。

### 点3 · prompt 假设盘点（worker/attributor md，按 ⑥C 归属表分）✅ 大部分 agnostic

- **现状**：41 条规则中 **36 条 module-agnostic**(claim/期望值溯源/检索序/emit/交付语言/layer descent/quote/归因判层…),仅 **5 条 sdns-bound**：`W7`(分布类命中=采样)`W8`(读取通道分采样/成员)`W9`(持久化过期=运行时选择)`W10`(容量/存在=成员布局,sdns listener)`W14`(持久化清理,save-family)——全是 **h-in-λ DNS 轮转语义**。attributor 更 agnostic(layer=11 核心域无关,dig/rr 仅出现在例子)。
- **缺口**：5 条 sdns-bound 规则编码 DNS 轮转采样。**SSL** 无轮转采样(握手/证书确定性)→ 5 条 **inert 不 harmful**(N/A、不误导)。**SLB**(L4/L7 有调度 rr/wrr/lc)→ W7/W8 分布采样**概念可迁移**但观测通道不同(SLB stats vs dig)。
- **补法成本**：**低**。框架 36 条直接迁移;5 条 sdns-bound 对 slb/ssl 惰性无害。SLB 若需分布采样规则,按实证增补 slb-scheduling 类(h-in-λ 概念已在,换观测通道)——**不阻扩域,增补按需**。

### 点4 · 评审入口（test-list-review 基线）✅ SLB 已含 / ⚠ SSL 缺

- **现状**：description 域已列「APV load-balancer(**SLB** / SDNS / HTTP / IPv6)」+ Trigger keywords 含 SLB;评审结论逻辑(VERDICT/P 级/改进建议)domain-agnostic。`ssl=0`——SSL 不在评审域。
- **缺口**：SSL 未进评审基线域列表。
- **补法成本**：**极低**。description 域列表 + Trigger keywords 加 SSL(1 行 frontmatter),评审逻辑零改。

## 补法优先序（成本×阻塞度）

1. **文法层 slb/ssl statements**(中成本、**扩域前置**,worker 编 slb/ssl 无此则无对象锚)——优先,需 author 流程;
2. **评审入口 SSL**(极低,1 行)——顺手;
3. **prompt SLB 分布规则**(低,按实证增补)——非阻塞,首批实证后定;
4. **precedent slb/ssl**(零成本,自愈)——首批 cases 跑起自增长,footprint 兜底冷启动。

**风险清单**:①文法层缺口=最大前置风险(不填则 worker 编 slb/ssl 对象无锚、易盲猜)②precedent 冷启动=头几例质量波动(footprint 缓释)③5 条 sdns-bound 规则若被 worker 误套到 ssl(理论上 inert,但需首批观测确认不误导)。**试点建议**:先补文法层 slb 一个对象族(如 virtual service)+ 评审 SSL 一行,取 1-2 个 slb 简单用例试编,观测 footprint 检索命中率 + 有无盲猜,再决 ssl。

---

# Py-Eng 四面机械扫描（人工用例 / 模板函数 / CLI 手册 / footprint，2026-07-19）

> read-only,机械事实面。复用 #23（`team4_excel_function_gap.md` 框架方法闭集 + 人工用量）+ #43（105 卷语料产出面），叠 slb/ssl 透镜。**与上文 LLM-Eng 知识层就绪度互补**:LLM-Eng 评「能不能 KNOW 怎么写 slb/ssl（文法/手册/footprint 语法）」,本节评「编译器能不能 PRODUCE slb/ssl 所需的测试方法（execute/server/证书族）」——两层结论有落差,见 §P5 互对。

## P1. ① 人工金标准卷 slb/ssl 存量

`smoke_test/` 顶层域**只有 `sdns` + `snmpd`——无 slb/ssl 独立分区**。

| 域 | 金标准卷 | 结论 |
|---|---|---|
| sdns | 380 卷 / 58 子目录 | #23 C 面全量 |
| **slb（独立）** | **0** | ⚠ 零金标准卷,precedent 对 SLB 冷启动 |
| ssl（嵌 sdns） | 6 子目录（`dot`/`https_health_check`/`sdns_dc_default_ssl`/`sdns_health_check_https2`/`sdns_ssl_conn`/`sdns_support_slb`） | SSL 是 SDNS 加密/HC 特性,非独立 SLB |

## P2. ② 模板函数 × slb/ssl 未编译面（风险主源，本节核心）

框架方法闭集 vs **105 卷 f_sequence 实测直方图**（cmds_config 274/routera 235/cmd_config 204/found 191/sleep 90/not_found 89/abs_found 79/routerb 9——**编译器方法词汇仅 8 个,到此为止**）：

| 框架方法 | 人工用量(sdns 金标准) | 105 卷产出 | slb/ssl 必需度 | 风险 |
|---|---|---|---|---|
| **SSL 证书族 25 def**（mirror 实抽:importKey/Cert/RootCA/InterCA/CRLCA/csrVhost/eccCsrVhost/importSni×5/importMuti×2/importReal×2/activeCert/sm2×7） | 354 | **0** | SSL 必需（证书导入是前置） | 🔴 编译器零实弹 |
| **execute**（发流量/客户端动作） | 2208 | **0** | SLB 必需（负载均衡=流量分发） | 🔴 #23 真能力缺口 |
| **server 触发端**（server213/231/232） | 4322 | **0** | SLB 必需（验 real server UP/DOWN 须后端起停） | 🔴 #23 真能力缺口 |
| **I 列 format 注入** | 1426 行 | **0** | SLB/SSL 常用 | 🔴 #23 真能力缺口 |
| cmd_config/cmds_config/found/not_found/abs_found/routera | 主力 | 主力 | 通用 | 🟢 已实弹 |

**核心结论**:SLB/SSL 的核心测试能力（证书族 25 / execute / server / I 列）**编译器 105 卷零产出**。这是 #23 已坐实的"配置+dig+静态断言系统性降维"正面撞上 SLB(流量分发+后端健康)/SSL(证书链)的本质测试需求——**非知识缺口,是能力缺口**。

## P3. ③ CLI 手册覆盖（非瓶颈，与 LLM-Eng 一致）

product 手册总 1720 md;**slb 118 / ssl 104 / sdns 79**——slb/ssl 手册覆盖高于 sdns,语法知识充足非瓶颈。

## P4. ④ footprint 判例冷启动度（精化 LLM-Eng「footprint 富」）

| 域 | nodes(前缀 glob) | 含 device_verified 溯源 | known_issues | 证据源 |
|---|---|---|---|---|
| **slb** | 293 | **0** | **0** | 全 manual（1043/1） |
| **ssl** | 213 | **0** | **0** | 全 manual（525） |
| sdns | 282 | 1 | 2 | manual 939 + **other 124**（设备/编译派生） |

**计数口径对齐**:我 293/213 = 严格前缀 `slb*/ssl*`;LLM-Eng 349/261 = 文件名含 slb/ssl 任意位置(多出的在 `health.l2slb`/`segment.statistics.slb`/`statistic.slb` 等前缀下)——**两数皆对、口径不同,无冲突**。

**精化 LLM-Eng「footprint 富」**:节点数确多(语法富,LLM-Eng 对),但**证据源 100% manual_10.5 手册派生、device_verified=0、known_issues=0**——即 footprint 对 slb/ssl 只能返回"手册查得到的语法",**无设备验证的行为判例、无已知缺陷判例**(这些才是编译 PASS 写回积累的、真正 de-risk 的判例)。sdns 靠 105 卷编译攒了少量(other 124 + known_issues 2),slb/ssl 一条没有。**与 LLM-Eng point2「precedent 冷启动」同向,并扩展到 footprint 行为面亦冷**。

## P5. 两层结论互对（LLM-Eng 知识层 vs Py-Eng 能力层）

| 维度 | LLM-Eng（知识层） | Py-Eng（能力层） | 调和 |
|---|---|---|---|
| footprint | 富(349/261 节点) | 富但 device_verified=0(手册桩) | ✅ 互补:语法富、验证行为判例冷 |
| precedent | 冷启动(自愈) | slb 零金标准卷 + 105 卷零 slb/ssl 产出 | ✅ 同向 |
| 手册 | 富 | slb118/ssl104 非瓶颈 | ✅ 一致 |
| prompt | 36/41 agnostic | (未评,归 LLM-Eng) | — |
| **总判定** | **可行·风险中低**(主缺口=文法层,中成本 author) | **纯配置试点低危;SLB/SSL 本质行为层偏高**(execute/server/I列/证书族 105 卷零产出,需 #23 P0-1 blocks/引擎能力补) | ⚠ **落差=评估层不同** |

**落差调和(结论冲突先互对证据面,非谁对谁错)**:LLM-Eng 评"知识就绪度"(能不能查到怎么写)→中低;我评"编译器产出能力"(能不能产出所需方法)→本质行为层偏高。**两层都对、层不同**:知识层缺口(文法 statements)是**中成本 JSON author**(LLM-Eng 修法方向对);能力层缺口(execute/server/I列/证书族)是**#23 P0-1 坐实的 blocks 组合子/引擎缺口,改代码成本**,比 author JSON 高一档。**合成可行性受能力层门控**——纯配置类试点低危(两方共识),SLB 流量分发/健康检查 + SSL 证书链验证受能力缺口门控。

## P6. 综合风险清单 + 试点建议（机械证据;go/no-go 终裁交 leader/用户）

**风险(机械证据排序)**:R1 SLB/SSL 核心方法编译器零实弹(§P2,🔴)、R2 SLB 零金标准卷(§P1,🔴)、R3 footprint 行为判例冷启动(§P4,🔴)、R4 编译器降维撞 SLB/SSL 本质(#23 P0-1,🔴)、R5 负面测试范式缺失(#23 P0-2,🟡)、手册非瓶颈(🟢)。

**试点分层(低→高风险,合 LLM-Eng 补法优先序)**:
1. **探路层(撞 0 能力缺口)**:slb/ssl **纯配置存在性**用例(配虚服务/服务组/证书对象 → `show slb/ssl` 断言配上)——仅用已实弹 cmd_config+found/abs_found。**前置**:补 LLM-Eng §点1 文法层 slb 一个对象族 + §点4 评审 SSL 一行。先证"编译器在 slb/ssl 语法上不崩"。
2. **能力缺口单点突破(择一)**:建议 **SSL 证书导入族**(25 方法边界清晰、比 execute/server 环境依赖低),验 emit/blocks 能否表达证书步 + 上机走通=兑现 #23 P2-3。
3. **本质行为层(撞三大缺口,最高风险)**:SLB 流量分发/后端健康=execute+server+I 列,**需先补编译器能力(#23 P0-1:blocks 扩 execute kind + I 字段 / 或引导退 steps)**,不宜作首棒。

**一句话**:知识面够(手册富、文法可 author)、能力面缺(execute/server/I列/证书族 105 卷零产出)——扩域可行性**取决于是否先补这四条未实弹路径**。纯配置试点低危可先行,本质行为层待能力补齐。

---

## Leader 合成：风险总判与试点方案（2026-07-19，三线定稿）

### 总判：**分层可行——纯配置层可试点（低危），本质行为层当前不可行（能力层门控）**

三线证据合成（Theory 理论迁移性 + LLM-Eng 知识就绪 + Py-Eng 能力实弹面）：

| 层 | 判定 | 依据 |
|---|---|---|
| **纯配置存在性层**（对象增删改 + show 断言） | **可试点·低危** | 框架保护全迁移（op 分派模块无关、恒真门/form=f(op,H) 闭合）；手册充足（slb118/ssl104 页>sdns79）；缺口仅文法层 10-14 条 JSON（零代码） |
| **本质行为层**（SLB 流量分发/健康翻转、SSL 握手/证书链） | **当前不可行·高危** | 编译器 105 卷实际方法词汇仅 8 个（配置+dig+静态断言降维）；SLB/SSL 本质需求撞**四条零实弹路径**：execute（人工用 2208 次）/server 触发端（4322）/I 列（1426 行）/SSL 证书族（25 def）——编译器从未产出过任何一条 |

### 风险清单（严重度排序）

> 编号消歧（Design 审出，2026-07-19）：本节 R1-R6 复用 `team4_slb_ssl_risk_theory.md` §2 的 Theory 编号；**R0 为本合成新增**（Theory 侧无 R0，其内涵≈上方 §P6 的 R1+R4 提炼）。与 §P6 风险排序的 R1-R5（锚 §P1-P4/#23）是**另一套编号体系**，同名不同义，引用时注明出处节。

- **R0【最高·能力层门控】**编译器方法产出降维：能力补齐=引擎/blocks 工程（改代码，成本>author JSON），单独立项，不宜与扩域试点混批。
- **R1【高】**SSL 握手/证书链 CLI 可观测性=表达力边界候选（Theory，投影核普查前置——无 show 投影则必然欠定或假验证）。
- **R3【高】**τ 域扩张：证书文件=write file 保存族的 SSL 版；SLB virtual 占用已有 run11 实证；复位差集普查+证书纳入 δ(c) 前置。
- **【中】**文法层冷启动（statements/reference 全 sdns，slb/ssl 对象形态=0，需领域 author 10-14 条）；R2 健康翻转采样时序；R4 顺序敏感面。
- **【低】**判例双冷启动（precedent 全 sdns + footprint slb/ssl 节点 293-349/213-261 全为手册派生语法桩、device_verified=0——检索可用、行为判例靠自愈攒）；R5 覆盖不可判照旧观察级；R6 op 闭集大概率复用。

### 试点方案（三阶递进，go/no-go 各阶独立）

1. **阶段一（建议先行）**：补文法层 slb 对象条目（6-8 条）+ 评审入口 SSL 一行 → 取 **1-2 个纯配置类 slb 人工用例**校准编译（低危冒烟，观测检索命中率/盲猜率/门触发）；
2. **阶段二**：SSL 证书族单点突破（证书命令族纯配置面+τ/保存族普查落地，兑现 #23 P2-3 遗留）；
3. **阶段三（能力补批,单独立项）**：execute/server 触发/I 列产出能力工程化后，再开 SLB 流量/健康与 SSL 握手类本质行为用例。

**明确不建议**：直接拿 SLB 健康检查或 SSL 握手验证类用例当扩域首棒（撞 R0+R1 双高）。

### 前置动作清单（全数据层/文档层，零引擎代码）
①投影核普查（SSL 命令族 show 投影盘点，治 R1）②复位差集普查+证书纳入（治 R3）③op 闭集扫描确认（治 R6）④文法层 slb/ssl 条目 author ⑤评审入口 SSL 一行。

---

## #48 归因修订节（2026-07-19，用户令「不可行须归因到理论/设计哪层」·Theory §4 + Design 六探针交叉定谳）

### 归因定谳：R0 主体=需求侧未证 + 引导缺口，**非理论/设计结构性缺陷**

两线独立取证在枢纽点（门放行 vs reject）收敛，framework-capability-before-limitation 纪律双线命中：

**Theory 需求侧铁证**（§4，`team4_slb_ssl_risk_theory.md`）：105 交付卷 **I 列非空 0 次 vs 同族 H 列 73 次**（用了 H 没用 I=没需要，不是表达不了）；21 个未决案欠定原因全为可验性边界/测试床缺 host，案文「触发」全指 dig 客户端——**零案因动作表达不了而欠定**。K 的 form 域与 σ 结构容纳 execute 类动作；π 本就含客户端工具观测（routera=dig 235 次），加 TLS 客户端 host 属数据条目。

**Design 供给侧行级证据**（六探针）：①门 **accept** execute——structural_gate `_valid_fs_by_e`:95-108 + `_execute_returning_actions`:112-122 从 mirror ssh_server **动态解析**方法闭集，execute 解析出 **40 动作**（apv_action 32+client_action 8），非硬编码 8 方法；F=execute 放行 :559-567。②I 列 accept（:973-1004 仅校注入 format 安全）。③blocks 无 EXECUTE kind 但 steps 原生通道天然绕过——非硬阻断。④DESIGN 无「config+dig」scope 条款（沉默=未需求过，非排除）。**能力链（gate/parser/框架/设计契约）全通、零代码改动需求。**

### 真实缺口清单（按成本类）

| 缺口 | 层 | 成本 |
|---|---|---|
| worker references 零 execute/apv_action 指引（mirror 在盘可读但从未被指向） | prompt 数据 | prompt edit·小 |
| domain_grammar ssl 条目 ×0（sdns×3/slb×1） | 文法数据 | author JSON 10-14 条·零代码 |
| SSL 证书信任验证可观测性（投影核内外待普查） | 理论边界候选（R1） | 普查+既有 V_U 欠定呈报兜底·非新公式 |
| R2 健康翻转时序 | 理论小延伸（C6 采样二分的时序孪生） | 既有构件延伸·非新公式 |

### R0 图景拆分：G/V 两层（Design 洞察，Theory 已采纳三态精化）

- **G 层（命令供给）**：execute/server 触发/I 列——**无结构阻断**（行级证毕）；
- **V 层（断言可观测）**：execute 触发后效果能否投影断言——**真边界候选**＝Theory R1。Theory 终层精化（§4.1）：form=f(op,H) 覆盖 100%（条件于状态可观测），**V 瓶颈不在 form 判定而在 π 投影存在性**（观测面有没有）；V 层逐个盘初判——SSL 握手/协商/证书链呈现、SLB 健康翻转均**客户端工具可观测（V 通）**，唯 **SSL 证书信任验证**可能落投影核外（核外走既有 V_U 欠定呈报兜底，非新公式）。**R0 真实关口收敛为一件事：V 层投影核普查（前置动作①）。**
- 门三态纪律入档：accept / never-saw / reject——never-saw≠reject，归因默认需求侧；reject 须行级证据才升「机械门禁」。本轮全部为 accept 或 never-saw，零 reject。**对照锚（Design 补证）**：found_times 门 REJECT（structural_gate:419-427，框架只传 2 参、真做不到）vs execute ACCEPT（框架 ssh_server 40 动作、真有）——门的判据本就是**框架支持性**而非历史需求，故 execute 落 accept 是「框架有此能力」的阳性证据，非门恰好没拦。

### 判定修订（对本文件上节「Leader 合成」的更正）

- 本质行为层：「当前不可行·高危」→「**未实弹验证·中危偏高**」——能力链无结构阻断，缺口=引导数据+V 层普查+端到端零实弹（零证据≠负证据）。「不可行」一词高估，撤回。
- 阶段三成本：「引擎/blocks 工程（改代码，单独立项）」→「**prompt edit + author JSON + 试点实弹**」。**Py-Eng 已 CONCUR**（亲读独立核证，非转述）并扩展 Design 证据面：structural_gate:559-561 对 E=APV 设备 **F 校验整体跳过**（注：APV*/Seg* 方法集未全量取证故不设白名单）——**execute 与 SSL 证书族 25 方法同被放行**，其 #47 证书族顾虑一并落空；:772-775 execute 步已被排除出命令-echo 恒真门（引擎本就 execute-aware，crash-gate 不误伤）；:854 execute-only 无断言→always-fail 属断言正确性要求、非拒 execute；crash 必崩门子检查无 execute 专项拒。原判「需 #23 P0-1 改代码」订正为「**steps 原生通道已可表达，非改代码**」。
- 试点三阶结构不变，但阶段三性质从「等能力补批」变「enablement 后直接试点实证」。
- 诚实边界（Design 声明原样入档）：「gate 接受 execute 输入」≠「execute 用例端到端跑通产出正确断言」——后者只能试点实弹证明。
- **保留风险两条**（Py-Eng CONCUR 附带，独立轴、非代码/设计/理论缺口）：**(a) 经验冷启动**——零 device-verified 先例，门接受≠worker 首写即对，自愈层（compile→PASS→writeback）缓释，#47 R1/R3 维持不变；**(b) 环境就绪**——execute 需后端服务器起停/流量观测、SSL 证书族需床上证书文件与 CA 基础设施，属**测试床依赖第四轴**（正交于编译器/知识/理论三轴），试点阶段二/三前置增补**床能力核**（后端起停可控性+证书/CA 设施存在性）。

### 对用户问「哪里设计或理论有问题」的正式回答

**两边都没有结构性问题。** 问题实际在四处：①**引导数据层**——worker 从未被指向 execute 形态、文法零 ssl 条目（数据补齐，零代码）；②**验证空白**——四条路径 105 卷零实弹是「没需求过」的零证据，不是「做不到」的负证据，需试点实证补上；③**理论仅两处小延伸**——R1 投影核普查、R2 时序孪生，均既有构件延伸而非 K 重构；④**环境就绪轴**（Py-Eng 补）——execute/证书类试点依赖床能力（后端起停可控、证书/CA 设施），与前三轴正交，试点前床能力核前置。

**三方终态签收**：Theory §4/§4.1 落档（G/V 采纳+V 层逐个盘）、Design 六探针+对照锚全闭、Py-Eng CONCUR（独立核证+证书族扩展+两保留风险）——#48 关账，本节为 #47 报告的权威修订。

### #49 投影核普查定格（2026-07-19，Theory §5 census，`team4_slb_ssl_risk_theory.md`）

**R1 从「高·边界候选」定格降「低」**：11 项 SSL/SLB 本质行为逐项盘，**10 项 V 通、零纯核外项**——

- **show 投影铁证 6 项**（手册命令实证）：协商版本/套件 `show http xciphersuite`、证书 `show restapi ssl certificate`、CRL `show ssl crlstatus`、健康翻转/real UP-DOWN `show slb real health`/`show health up-down`、会话保持 `show statistics slb group`（SessionCount 极详细）、调度分布 `show statistics`；
- **客户端工具 V 通**（条件工具）：握手（openssl+footprint 已观测）、信任验证、SNI——**上节「证书信任验证可能核外」被普查改判：实为客户端语义（openssl verify 可观测，非设备端职责），无需 V_U 兜底**；openssl/curl 实装与否属床属性，诚实标 needs device probe（一次性）；
- **OCSP 定格＝needs device probe**（LLM-Eng 手册深挖定证：`SSL_Hostname_List.md:1` 权威表 OCSP 仅 config 面 `ssl settings ocsp`、**无 show 投影**——与 CRL 有 `show ssl crlstatus` 不对称；全手册 grep 零命中；间接候选 `show statistics ssl`/握手行为观测需上机证。诚实标注非猜测）。

**结论**：SSL/SLB **无结构性观测盲区**，V 层不构成扩域高风险关口。普查 **11/11 全定格＝风险清单零 undetermined 项**（10 V 通 + OCSP 1 项「需上机探」的有界闭合项——试点若含 OCSP 意图案，归探路层顺带 probe；OCSP config-有/show-无 的不对称本身可作产品观察候选）。残余前置＝床工具链一次性 probe（openssl/curl 实装确认，试点阶段一顺带）。
