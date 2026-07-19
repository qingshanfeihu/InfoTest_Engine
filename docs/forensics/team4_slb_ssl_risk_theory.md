# SLB/SSL 扩域风险·理论侧条目（#47，风险先行）

> 2026-07-19，Theory。用户令风险先行——SLB/SSL 扩域前的理论侧风险评估。
> 方法：按 #43 六轴发现判**迁移性**（框架级=受保护 / 模块级=新风险），每条锚 K/S 节 +
> 现有 slb/ssl 文法（`domain_grammar.json`）/footprint 证据。**理论先行**，Py-Eng（文法/mirror 扫描）
> + LLM-Eng（用例数据）并行，R1/R3 量化待数据校准。
> **证据边界**：已实证证据标「实证」，理论推断标「推断·待普查」——不混。

## §1 框架级应迁移（受保护、扩域低风险）

这些**闭合于框架版本、与模块无关**，slb/ssl 用例直接受保护，无需扩域动作：

| 机制 | 锚 | 迁移性证据 |
|---|---|---|
| **form=f(op,H) 机制闭合** | K §18.14 C1(:704) | check_point op 闭集 `{found/not_found/abs_found/found_times}` **走 generic 2 参分派、通用不分模块**（structural_gate:408、emit_xlsx_tool:991）——实证 |
| 恒真断言族六门 | K §18.14 | 闭合框架窗口语义（re.DOTALL 无 MULTILINE） |
| found/not_found 窗口语义 | K §18.14 | send+read_until 窗口，框架级 |
| INV-7 闭环 / 门族⟨f,c,m⟩ / broken 三态 | K C7(:685)/C9/(44) | 引擎机制，模块无关 |

## §2 新风险条目（逐条：风险面 / 理论依据[锚] / 严重度 / 缓解方向）

### R1【高】SSL 握手 / 证书链验证的可观测性 = 表达力边界候选
- **理论依据**：轴⑤ verification_path_absent（K §4.2 / C6:739）+ S §投影核外。SSL 握手是**协议级交互**，
  CLI 回显（show ssl / dig）对「握手成功 / 证书链有效」的**断言级 show 投影可能不存在**（类比轴⑤实证的 HA FIP 单机不可模拟、CNAME 池无 IP 替代）。若验证目标在投影核外 → **min_requests=null 表达力边界（不可证伪→改预期）**。
- **证据**：footprint 已有 `ddos.ssl.handshake` / `handshake.timeout` / `renegotiation`——SSL 握手行为**有观察记录**（实证）；但「握手成功 / cert chain valid」是否有**断言级** show 投影 **待普查**（推断）。
- **严重度 高**：若大量 SSL 用例的验证目标落在投影核外 → 系统性欠定，或被迫写恒真断言（假验证，撞 §18.14 恒真族门）。
- **缓解**：扩域前做 **SSL/证书行为的投影核普查**（枚举哪些 ssl 行为有 show 投影、哪些核外）；投影核外类走欠定呈报（compile_check_verifiability），**不硬编恒真断言**。

### R2【中】SLB 健康检查翻转 / 权重分布 = 采样边界 + 时序边界候选
- **理论依据**：轴⑤ 采样边界（C6 min_requests）。**权重分布（wrr）≈ sdns 分布**，`compile_check_verifiability` 的分布可证伪性数学（算法+n_requests+n_pools）**大概率直接适用**；**健康检查翻转（up→down→up）是时序主张**，min_requests 判据需扩到「时序观测窗口」（类比 persistence TTL 时序——zhaiyq 曾暴露 TTL 域时序翻转盲区）。
- **证据**：domain_grammar `health checker`(:1129，有 `clear health checker` per-case 清理，实证)。
- **严重度 中**：权重分布判据可复用；健康翻转时序需**新判据面**（现有 min_requests 是采样数、非时序窗口）。
- **缓解**：slb 权重分布复用 C6 采样边界判据；健康翻转类扩「时序可观测性」判据（接 persistence 时序域）。

### R3【高】SLB/SSL 配置对象持久面 + 证书文件资产 = τ 域扩张 / 保存族新形态
- **理论依据**：轴② τ 分工（S §τ:116）+ (32) 复位差集 + 保存族反例。SLB/SSL 配置对象（vip/pool/cert/ssl-profile）持久面**比 sdns 大**；**证书文件类资产（cert/key）是盘上文件 = δ(c) 持久写（跨案存活）= write file 保存族的 SSL 版**，per-case clear 可能清不掉。
- **证据**（多为实证，风险有据）：
  ① `clear slb` 是**功能域清理、不含 L2/L3 interface/vlan/route**（domain_grammar:307，实证）——功能对象覆盖、系统层不覆盖；
  ② **SLB virtual service 占用已实证**（"IP/port pair may already be occupied by an SLB virtual service"，run11 668030，domain_grammar:317）——SLB virtual 持久面/占用语义**已在 sdns 域碰到过**；
  ③ `http xclientcert dnencoding` 等**证书命令存在**（domain_grammar:1564，实证）——证书文件资产的持久性 **待普查**（推断）。
- **严重度 高**：证书文件若 per-case clear 覆盖不到 = **保存族反例新形态**（cert 跨案残留污染后继），是 run12 τ 缺元教训 + yzg write file 保存族的 SLB/SSL 版；创建型写占比（vip/pool/cert 创建）若高，τ 责任集显著大于 sdns。
- **缓解**：扩域前做 **SLB/SSL 复位差集普查**（枚举哪些对象 per-case clear 覆盖 / 哪些持久面-文件资产需案级 τ）；**证书文件类资产明确纳入 δ(c) 保存族闭集**（`persistence_channels` 加 pattern，零代码）；配对恢复门 inverse_forms 覆盖 slb/ssl 逆元（no vip / no cert）。

### R4【中】顺序敏感面
- **理论依据**：轴⑤ ordering_sensitive（needs_decision）。SLB 健康检查翻转、SSL 会话保持有强顺序语义。
- **证据**：轴⑤ 已有 ordering_sensitive 6 案（顺序判据在场，实证）。
- **严重度 中**：判据可复用（slb 会话保持类比 sdns persistence 已有域），需验证覆盖。
- **缓解**：复用 needs_decision ordering_sensitive 锚；slb 会话保持接 sdns persistence 域。

### R5【低·非新】C8 覆盖满射不可判照旧适用（观察级）
- **理论依据**：C8 三粒度一致不可判 → INV-breadth 观察级(K:186)。SLB/SSL 脑图→用例覆盖满射同样机械不可判（该编判定需语义）。
- **严重度 低**：照旧适用、**非新风险**；观察级不 gate，扩域不改变。
- **缓解**：无需新动作。

### R6【低】op 闭集是否因 SSL 扩张（form=f(op,H) 迁移前提）
- **理论依据**：C1 form=f(op,H) 闭合于 check_point op 闭集。
- **证据**：check_point 走 generic 2 参分派、**通用不分模块**（structural_gate:408、emit_xlsx_tool:991，实证）——大概率 slb/ssl 复用现有 op 闭集。
- **严重度 低**：若复用则 C1 直接迁移；**若 ssl 验证引入新断言算子（如证书链专用）则需重核 form 判定机制闭合**。
- **缓解**：扫 slb/ssl mirror check_point 有无新 op。

## §3 严重度排序 + 扩域前置理论动作

| 严重度 | 条目 |
|---|---|
| **高** | R1(SSL 可观测性/投影核)、R3(τ/证书保存族) |
| **中** | R2(健康翻转/权重)、R4(顺序敏感) |
| **低** | R5(覆盖不可判照旧)、R6(op 闭集) |

**三普查（扩域前置理论动作，治高中风险）**：
1. **投影核普查**（治 R1）：枚举 SSL/SLB 行为哪些有 show 投影、哪些核外——核外走欠定呈报、不硬编恒真。
2. **复位差集普查**（治 R3）：枚举 SLB/SSL 配置对象 per-case clear 覆盖度 + **证书文件类资产纳入 δ(c) 保存族闭集**。
3. **op 闭集扫描**（治 R6）：slb/ssl mirror check_point 有无新算子。

**待数据校准**：R1（投影核外行为比例）、R3（证书文件持久性 + 创建型写占比）需 Py-Eng（文法/mirror/footprint 扫描）+ LLM-Eng（现有 slb/ssl 用例数据）量化。理论侧已锚定风险面与依据，数据到即校准严重度与缓解优先级。

**总判**：扩域**主体框架受保护**（§1，form/门/窗口/op 闭集框架级）；**新风险集中在两处**——SSL 协议交互的**可观测性（投影核）** + SLB/SSL 持久面的**τ 域扩张（尤证书文件保存族）**。二者都有既有理论构件承接（投影核 / τ 复位差集 / 保存族闭集），**缓解=数据层普查扩条目、非新公式**（符合自愈合四层：判例/文法层扩，零代码）。

---

## §4 R0 归因（#48：infeasible 是理论 gap 还是需求侧未用）

**破混淆**：105 delivered + 21 unfinished **全 sdns/dns 域**。R0（8 方法零 execute/server-trigger/I列/SSL）归因前先排需求侧（framework-capability-before-limitation 纪律）。

**Probe 5 需求侧铁证（强支持 demand-side (a)）**：
- f_sequence **8 方法闭集、零 execute/server-trigger**（语料 105 卷）；
- **I 列非空=0 / H 非空=73**——同族 H 用了、I 没用（**未用到，非表达不了**）；
- 21 unfinished 欠定原因=**可验性边界（采样/表达力）+ 测试床 host 能力缺失（IPv6 客户端缺）**；"触发"均指 **dig 客户端触发（routera/routerb）非 server-trigger**；**零案因"动作表达不了"欠定**；
- claim_kinds 全 sdns 域可验性类型（absolute_position/relation_diff/verification_path_absent…），零 execute/动作类。
→ **zero production = 需求侧 (a)：四脑图 sdns 域没需要，8 方法对该域充分。不是 K 供给侧缺陷。**

**归因表**：

| gap | 归因层 | 证据（file:line / 语料） | 最小理论变更 |
|---|---|---|---|
| **execute 动作** | **需求侧未证** | f_sequence 8 方法零 execute（语料）；form=f(op,H) 域=check_point 断言 op（emit:991），execute=执行动作（emit:1660 deferred-execution）**范畴正交**、execute 类断言仍走 op 闭集、form 照样适用 | **无**（范畴正交；execute 能否 emit=Design 机械侧核门放行） |
| **I 列注入** | **需求侧未证** | I 非空 0 / H 非空 73（同族 H 用 I 没用）；σ 容纳 I 注入（执行元素） | **无**（σ 容纳、未用） |
| **server-trigger** | **需求侧未证** | 语料零 server-trigger；unfinished "触发"=dig 客户端非 server；σ 通用执行序容纳（S:89） | **无**（σ 容纳、未用） |
| **SSL 握手/协商/证书链呈现·观测** | **数据层(host 方法表)非理论** | π **实含客户端工具观测**（routera/routerb=dig 235+9，语料）；unfinished 欠定因 host 缺 IPv6 客户端=数据层同型；SSL 客户端 TLS 工具与 dig 同型 | **注记显式化**：π 客户端工具观测面已存在（routera 实证），文档 S:266 偏设备 show 未显式命名；加 TLS 客户端 host=数据层；**非理论能力扩展** |
| **SSL 证书信任验证语义** | **可能投影核(理论边界)·待普查** | S 投影核 :266（61 顶层 55 有 show 投影 / 6 核外）+ 跨设备盲区 :329；信任链某语义或无客户端工具观测投影 | **待普查**；若真核外→V_U 欠定呈报（既有 S:735）**非新公式** |
| **R2 健康翻转时序** | **理论扩展(采样→时序孪生)** | C6 采样二分=采样数（min_requests）非时序窗口；健康翻转 up→down→up 是时序主张 | **C6 时序孪生**（采样边界→时序边界）接 persistence 时序域；类比 breadth/depth 孪生；**既有构件延伸非全新公式** |

**总归因**：R0 "infeasible" **主体 = 需求侧未证（execute/I列/server-trigger）+ 数据层未扩（SSL 握手观测=host 方法表）**，**非 K 理论结构缺陷**。framework-capability-before-limitation **成立**：form 域正交动作（execute 类断言走 op）、σ 通用执行序容纳（server-trigger/I 注入）、π 已含客户端工具观测（routera=dig 实证、SSL 工具同型）。**真理论边界仅两小点**，均既有构件延伸、非新公式：① SSL 证书信任验证（可能投影核，待普查，走既有 V_U 欠定呈报）② R2 健康翻转时序（C6 采样二分的时序孪生）。

**理论侧 go/no-go**：扩域**理论上可行**——主体框架受保护、R0 gap 主体归需求/数据层。前置=三普查（§3）+ 两处既有构件延伸。**不是 K 重构，是数据层扩条目 + 两处延伸。**

**Design 交叉核对项（门三态纪律，采纳 Design：never-saw ≠ reject）**：execute/server-trigger/I 列的**动作能否 emit 出卷** = Design 机械侧探针①。我判理论侧「form/σ 结构容纳」（form 域=断言 op、execute=执行动作，**范畴正交**：execute 类断言仍走 op 闭集、form 照样适用）。门三态分账：
- **accept**（门收）或 **never-saw**（门没见过此输入，105 卷全 sdns/dns 没喂过）→ 归 **需求侧未证**（默认）；
- **reject**（行级 REJECT 证据）→ 归 **机械侧门禁**（扩域要改门）。
- **别把「门没见过」当「拒绝」**——零产出默认 demand-side-unproven，除非 Design 取到行级 REJECT 才升 supply-side。

### §4.1 G/V 分层图景（2026-07-19，Design 交叉核对采纳）

R0「词汇=8」应拆 **G 层（execute 命令/动作步供给）∧ V 层（触发后可观测性）**——两层不同关口：
- **G 层通（Design 证）**：gate（structural_gate `_valid_fs_by_e`:95 从 mirror 动态解析 + `_execute_returning_actions`:112 **解析 40 execute 动作、非硬编码 8**）**accept execute**；框架有 execute/server；DESIGN 沉默不排除。**供给侧 G 层无结构性阻断**（缺口仅 prompt 引导 + slb/ssl grammar JSON，低成本数据层）。
- **V 层是真瓶颈候选（Theory R1）**：**form=f(op,H) 覆盖度 = 100%（条件于状态可观测）**——它是「给定 op+H 判 form」的机制闭合、假设状态已可观测，**不是 V 层瓶颈；瓶颈在 π 投影（观测面是否存在），非 form 判定**（form 与「可不可观测」正交）。V 层逐个盘触发后状态观测投影：SSL 握手/协商/证书链呈现 → 客户端 TLS 工具可观测（同 dig，host 数据层）=**V 通**；SSL 证书信任验证（CA 根信任）→ 可能投影核外 =**V 卡（走 V_U 欠定呈报，既有机制）**；SLB 健康翻转/权重 → 客户端 dig 可观测（routera 已有）=**V 通**。
- **合取**：execute 用例可行 ⟺ **G 层命令供给通（Design=通）∧ V 层断言可观测通（Theory R1=逐个盘）**。**R0 真实关口 = V 层投影核普查（§3 普查①），非 G 层供给、非 form 判定、非需求侧全空**——修正 #47 把 R0 当单一门控（8 方法词汇）的图景。

Design gate 证据已到，execute 那格交叉核对闭合：**G 层 accept（无阻断）→ execute 归 demand-side-unproven（G 层）+ V 层可观测性候选边界（逐个盘）**，非机械侧门禁。

**门三态判据（Design 行级核，2026-07-19）= 框架支持性（从 mirror 解析），非「想不想要」**：execute/I列/server-trigger **全 ACCEPT**——execute:structural_gate `_valid_fs_by_e`:95-108 从 mirror 动态解析 40 execute 动作（ssh_server.py:151 `def execute`）、放行:559-567、有处理分支:278/284/1077；I列:structural_gate:973-1004 只校验 format 安全（非拒本身）、emit_xlsx_tool:150 认；server-trigger:mirror test_xlsx.py:185-188 server 槽位适用。对照 **found_times → REJECT**（框架 dispatch 只传 2 参、found_times 需 3 参→TypeError，structural_gate:419-427 门主动拒）。∴ **门 accept/reject 是框架能力的机械投影**（同「机械闭集从 mirror 源码解析、非硬编码词表」纪律）——execute 连 never-saw 都不是、是**明确 accept（有处理分支），比 never-saw 更强地归需求侧未证**。found_times=reject 是既有框架「exactly N times」限制、与 SLB/SSL 扩域无关，不进 R0 归因。

---

## §5 V 层投影核普查（#49：R1 从 boundary-candidate 钉到 per-item verdict）

**方法**：逐项枚举 SSL/SLB 本质行为,判观测投影通道（设备端 show / 客户端工具 / kernel-outside）+ provenance（手册 file:line / mirror / footprint）。read-only、无 device。
**mirror host 面**：`ssh_server.py` 是通用 SSH 会话（cmd/execute/read_until,非专用工具）,host 槽位 routera（客户端）/server231/232/213/**http_server_231**（`test_xlsx.py`:184-188）——**routera 客户端能跑任意工具命令（dig/openssl/curl）,通用客户端工具观测面存在**；但 **routera 实装何工具=床属性,mirror/手册定不了 → client-tool 项理论面 V 通、实际工具可用 needs device probe**（诚实标,非猜"一定有"）。

| # | 本质行为 | 观测通道 | verdict | provenance |
|---|---|---|---|---|
| SSL-1 | handshake success/failure | 客户端 openssl + footprint 已观测 | **V 通**（footprint+client-tool） | footprint `ddos.ssl.handshake.json` |
| SSL-2 | negotiated version/suite | 设备端 `show http xciphersuite`/`show ssl settings` | **V 通（show）** | apv cli md:1683/2172 |
| SSL-3 | cert-chain presentation | `show restapi ssl certificate`/19222 CLI 查证书 + openssl -showcerts | **V 通（show）** | apv cli md:1833 + 手册「19222 CLI 查 vs 证书」 |
| SSL-4 | cert trust-verification result | 客户端 openssl verify（信任=客户端语义,设备不判） | **V 通（client-tool,条件工具）** | 通用 cmd+openssl；设备端无信任结果 show |
| SSL-5 | SNI hit | 客户端 openssl -servername + HTTPS vs 关联 | **V 通（client-tool+可能 show）** | openssl -servername + HTTPS vs 配置 |
| SSL-6 | CRL behavior | **`show ssl crlstatus`** | **V 通（show）** | apv cli md:2153 |
| SSL-6b | OCSP behavior | 设备端**无 show 投影**（OCSP 仅 config、无 show）；间接候选 `show statistics ssl` / OCSP stapling openssl -status 未证 | **needs device probe（明确定格）** | LLM-Eng:`SSL_Hostname_List.md`:1（OCSP 仅 `ssl settings ocsp` config、无 show ssl ocsp;与 CRL `show ssl crlstatus` 不对称）+ grep 全 1720 md 零 show-ocsp |
| SLB-1 | scheduling distribution | `show statistics slb group`（Hits/分布）+ 客户端 curl 采样 | **V 通（show+client）** | Unit_Test_Report_Bug_32166 |
| SLB-2 | health flip | `show slb real health`/`show health server up/down` | **V 通（show）** | Test List_LDAP HC md:22/36-37 + footprint `health.checker` |
| SLB-3 | real-server UP/DOWN | `show slb real health` | **V 通（show）** | Test List_LDAP HC md:36-37 |
| SLB-4 | session persistence hit | `show statistics slb group`（SessionCount/Lookups/Hits 极详细） | **V 通（show 铁证）** | Unit_Test_Report_Bug_32166:79 |

**R1 verdict（钉死,#49 完成）**：11 项本质行为**逐项定格、零未判**——**10 项 V 通**（设备端 show 投影丰富 + 客户端工具面 + footprint 已观测）+ **1 项 OCSP = needs device probe（明确定格,非模糊未判：手册证设备端无 show 投影,间接候选 `show statistics ssl` / OCSP stapling openssl -status 需一次 probe 定）**。**R1 从「高风险 boundary-candidate」降为「低风险：多数 V 通、单项一次性 probe 可定」**。

**分档诚实边界**：
- **show 铁证 V 通**（version/suite、cert、CRL、health flip、real UP/DOWN、session persistence、scheduling-statistics）：手册 show 命令实证,设备端观测确定。
- **client-tool V 通（条件工具可用）**（handshake、trust-verify、SNI）：routera 通用客户端能跑 openssl/curl,理论观测面存在；但 **routera 实装 openssl/curl 与否=床属性,mirror/手册定不了 → 此档实际可用 needs device probe**（诚实标,非猜"一定有"）。
- **待细化**（OCSP）：手册无 show ocsp,LLM-Eng 深挖 ssl 104 md / 否则 device probe。

**kernel-outside / V_U 注**：本普查**未发现纯 kernel-outside 项**——cert trust-verification 曾疑核外,实为客户端语义（openssl verify 可观测,非设备端职责）；OCSP 设备端无 show 但有间接候选（stats/stapling）,一次 probe 定:**若间接投影成立=V 通;若全无=该单项走 V_U 欠定呈报（既有机制,非新公式）**。∴ SSL/SLB **最坏情形仅 OCSP 单项可能走 V_U,其余无需兜底**。

**结论**：R1（V 层可观测性）**不是 R0 扩域的高风险关口**——多数行为设备端 show 投影丰富、少数客户端工具可观测（条件工具）、仅 OCSP 待细化。扩域 V 层**无结构性观测盲区**,前置=① client-tool 档确认 routera 工具链（一次性 device probe）② OCSP 深挖。**非 K 重构、非新公式。**
