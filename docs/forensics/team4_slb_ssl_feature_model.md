# SLB/SSL Product Feature Model + 四面映射矩阵（#50 line C）

> 2026-07-19，Theory line C。用户令：pilot 前**完全消化 product + automation**——用户怀疑「我们从没真读 SSL 模板函数」审计为 **TRUE**，故本文**真读手册建 feature model**（非凭想象）。
> 主干原料：`product/SSL_Hostname_List.md`（权威 SSL CLI 全表：config+show 命令全集）+ CLI 闭集 grep（`ssl import certificate` 118 / `ssl activate` 108 / `ssl csr` 92 …）+ feature spec 文件（按引用，不复制）。
> **不与 A/B 重复**：framework method 引 Py-Eng line-A cards（by id）、manual usage 引 LLM-Eng line-B patterns（by id）、observation 引 #49 census（`team4_slb_ssl_risk_theory.md` §5）。
> **诚实标准**：每 cell 带 provenance 或明确 **EMPTY**——**empty cells 是 punchline**（框架碰不到的 feature / 无手册先例的 method / 无 observation 的 operation）。

## §1 Product SSL Feature Model（7 area，真读 SSL_Hostname_List.md 提取）

| # | feature area | config 命令（provenance: SSL_Hostname_List.md 权威表 + CLI 闭集频度） | show 投影 |
|---|---|---|---|
| F1 | **证书生命周期** | `ssl csr <host> [key_len]`(92) / `ssl import certificate <host> [idx][tftp][file]`(118) / `ssl activate certificate`(108) / `ssl import key`(68) / `ssl export key` / `ssl backup/restore certificate <host> <file> <pwd>` / `no ssl certificate` | `show ssl csr` / `show ssl certificate <host> [mode][idx]` / `show ssl backup certificate` |
| F2 | **key types (RSA/ECC/SM2)** | `ssl import key`(68) + key_length 参数 / `ssl settings minimum <host> <key_size>` ; ECC/SM2 走独立 spec | `show ssl certificate`（含 key 信息，display_mode）；ECC/SM2 细节 spec |
| F3 | **profiles / bindings** | `[no] ssl host {real|virtual} <host> <slb_service>`(432) / `ssl start`/`ssl stop`/`clear ssl host` | `show ssl host` / `show ssl status` |
| F4 | **SNI / servername** | `ssl settings servername <host> <ssl_server_common_name>` / `ssl settings certfilter <host> <subject_filter>` | `show ssl settings <host>`（含 servername） |
| F5 | **mutual auth (双向认证)** | `ssl settings clientauth <host>`(61) / `ssl settings authmandatory`(35) / `ssl import clientkey`/`clientcert` / `ssl globals verifycert {on\|off}` / `ssl settings certfilter` / `ssl import rootca`(64)/`interca`(37) | `show ssl settings`（含 clientauth/authmandatory）/ `show ssl rootca` / `show ssl interca` |
| F6 | **CRL / OCSP** | **CRL**: `ssl import crlca`(25) / `[no] ssl settings crl online\|offline <host> <crldp> <url>`(53) / `ssl globals crl cdp\|host` / `ssl globals fastcrl` / `ssl import crlfilter` / `ssl load crl` ; **OCSP**: `ssl settings ocsp <host> <ocsp_server>` / `no ssl settings ocsp` | **CRL**: `show ssl crlca` / **`show ssl crlstatus <host> [cdp]`** ✓ ; **OCSP**: ⚠ **无 show ocsp**（config-only，#49 铁证） |
| F7 | **协议 / cipher / session / reneg** | `ssl settings protocol <host> <version>`(166) / `ssl settings ciphersuite <host> <cipher>`(110) / `[no] ssl settings reneg` / `ssl globals renegotiation` / `ssl settings reuse` / `ssl globals sessiontimeout` / `ssl globals ignore\|sendclosenotify` | `show ssl settings`（含 protocol/cipher/reuse） / `show statistics ssl [host]`（握手/CPS 统计，BUG126746/159356 spec） |

**feature spec 引用（细节按引用，不复制）**：F2 key→`ECC_SSL_Func_Spec.md`/`SSL_support_SM2_SW_Func_Spec.md`/`SSL support to backuprestore SM2 certificates spec.md`；F5 mutual→`APV_SSL_1-way_to_2-way_Auth_spec.md`；F6→`ssl_rhost_per_host_verifycert_ctl_Spec.md`/`[中国银行SSL]不支持CRL手动导入.md`；F7 reneg→`APV_SSL_Renegotiation_Extension_spec.md`、handshake stats→`BUG126746_SSL_HANDSHAKE_STATS_SPEC`。

## §2 四面映射矩阵（product ↔ framework ↔ manual ↔ observation）

> ① product = §1（我已填）；④ observation = #49 census + §1 show 列（我已填）；② framework method = 待 Py-Eng line-A cards；③ manual usage = 待 LLM-Eng line-B patterns。**未落地列标 EMPTY(待A)/(待B)**。

| feature | ① product(config) | ② framework method (A, line A card by id) | ③ manual usage (B) | ④ observation (三通道) | 四面终 verdict |
|---|---|---|---|---|---|
| F1 证书生命周期 | ✓ CLI 全 | ✓ **DEDICATED 方法族**:csrVhost(ssl_comm:19)/importKey(:89)/importCert(:124,含自动 activate)/activeCert(:486)/importReal*(:243/265)+_tftp 变体 | ✓ line B §3.1 导入序列 + §4.3 DoT | ✓ show ssl certificate/csr | **fully**（四面齐）;⚠ CSR subject 硬编码(A:22-28)worker 不可变 |
| F2 key types | ✓ import key+minimum | ✓ **DEDICATED per type**:importKey(RSA:89)/eccCsrVhost(ECC:52)/**sm2ImportKey·Cert(SM2:572/599,3-arg `keyType,vhost,keyFile`=国密双证书系统,CC2 修正 LLM-Eng 原 2-param)** | ◐ line B §1 sm2 各 16 | ◐ show ssl certificate 含 key | **with-gaps**:sm2 MutiCert/Key activate 被注释(A:712)、show 呈现区分度待 probe |
| F3 profiles/bindings | ✓ ssl host real/virtual + slb | ✓ **generic cmds_config**（无专用方法——**预判此格对**） | ◐ line B 隐含 | ✓ show ssl host/status | **fully**（config object） |
| F4 SNI/servername | ✓ settings servername/certfilter | ✓ **DEDICATED**:importSni{Key/Cert/Rootca/Interca/Crlca}(A:290/319/361/398/425) | **(待B)** | ✓ show ssl settings | **fully**（A 证 SNI **有专用方法**——修正预判）;manual 待 B |
| F5 mutual auth | ✓ clientauth/authmandatory/clientcert | ✓ **DEDICATED CA**:importRootCA/InterCA(A:492/521) + generic cmds_config(clientauth settings) | ◐ line B clientcert 导入 | ✓ show ssl settings + openssl verify(#49 SSL-4) | **fully** |
| F6 CRL | ✓ crlca/crl online-offline/crlstatus | ✓ **DEDICATED**:importCRLCA(A:547)/importSniCrlca(:425) | ◐ line B importCRLCA | ✓ **show ssl crlstatus**(#49 SSL-6) | **fully** |
| F6′ **OCSP** | ✓ settings ocsp (config-only) | ✓ **generic cmds_config**（无专用 import、settings 类） | **(待B)**（line B 无 OCSP 用例） | ✓ **indirect projection CONFIRMED（#53 on-device）**:show statistics ssl(handshake failure rate/peer/count) + session + crlstatus 三间接通道;show ssl 16 subcmd **无 ocsp**（config-has/show-lacks asymmetry device-confirmed） | **fully（obs indirect-confirmed）——SSL last obs gap closes** |
| F7 **加密验证/协议/cipher** | ✓ protocol/ciphersuite/reneg/reuse | ✓ **generic cmds_config**(settings) + **execute**(dic_operation:57) + **execute 自验**(func_3/4 内嵌 check_point,A:62-70) | ✓ line B §3.2 packet-capture | ✓ **packet-capture hex**(`debug trace live tcp {} -x`+found TLS record,I 列 inject) + show statistics ssl | **fully**,packet-capture=gold-standard + execute 可自成验证 |

## §3 Per-Area Verdict + Empty-Cell Punchline

**product+observation 双侧（我这半）verdict**（framework/manual 待 A/B 落地后合成终 verdict）：
- **fully-modeled (product+obs)**：F1 证书生命周期 / F3 bindings / F4 SNI / F5 mutual auth / F6 CRL / F7 协议-cipher-session——**config CLI 全 + show 投影全**（观测 V 通）。
- **modeled-with-obs-gap**：F2 key types（config 全，但 RSA/ECC/SM2 在 show ssl certificate 的**呈现区分度待 device probe**）。
- ~~**obs-EMPTY（punchline①）**：F6′ OCSP~~ **→ #53 device-probe 已闭合**：OCSP config 有(`ssl settings ocsp`)、观测经 **indirect projection CONFIRMED**（show statistics ssl handshake stats + session + crlstatus 三间接通道，on-device 实证 show ssl 16 subcmd 无 ocsp）——**不再是 empty cell,SSL 零 kernel-outside**。

**Empty-cell punchline（deliverable 的重点，待 A/B 填后完整）**：
1. ~~**无 observation 的 operation**：OCSP~~ **→ #53 闭合**：OCSP 观测 **indirect projection CONFIRMED**（show statistics ssl handshake stats/session/crlstatus 三间接通道，on-device）——**SSL 全 feature 现 direct-or-indirect 可观测,零 kernel-outside**。
2. **framework method 列（②）预判——待 Py-Eng line-A 证实/证伪**：framework 8 方法闭集（cmds_config/cmd_config/routera/routerb/found/not_found/abs_found/sleep，#43 语料）**无 SSL 专用 method**——SSL config 预期靠通用 `cmds_config`/`cmd_config` 承载 SSL CLI、SSL 观测靠 `routera` 跑 openssl + 设备 `cmd`(show ssl *)。**若 line-A 证实=framework 无 SSL 专用方法但通用方法可承载（数据层 grammar 扩，非 method 缺）；若某 SSL 操作通用方法也够不着=真 framework 空格**。此列 punchline 归 Py-Eng line-A。
3. **无手册先例的 method 列（③）**：待 LLM-Eng line-B——105 卷 sdns 语料零 SSL（#48 probe5），SSL 人工用例模式在 SLB/SSL Test List md（`Test List_*SLB*`/`SSL Multi-card test proposal`），**worker 编 SSL 用例无 #43 先例可循**=先例空格（走手册直读，非判例检索）。

**总（product 侧）**：SSL product feature **CLI 层完整可建模**（7 area 全，SSL_Hostname_List.md 权威表实证）、**观测层仅 OCSP 单点 EMPTY**（其余 show 投影全）。用户「没真读模板函数」的疑虑——**本 model 逐 area config+show 带 provenance 即真读实证**；真正的 empty cells 集中在 ② framework method（待 A）+ ③ manual 先例（line B 已填大部）。matrix ② 列待 A docs 落地即填，leader 合成消化报告。

---

## §4 line B 消费 + 观测通道 taxonomy 修正（consume `team4_ssl_usage_patterns.md`）

**① 观测通道两值 → 三值（诚实：#49 census 漏一通道）**：我 #49 census 只枚举 **show projection / client-tool** 两值——line B 从人工金标准挖出**我漏的第三通道**：
- **packet-capture hex**（SSL 加密验证 gold-standard）：`debug trace live tcp {} "-x"`（hex 抓包，I 列注入接口 `APV_0.port1`）+ `found (1703 03)|(17 0303)`（匹配 TLS Application Data record 头字节:17=AppData/03 03=TLS1.2）⇒ 流量确被加密（line B §3.2/§4.1 verbatim）。**不是 show、不是客户端工具**，是设备端抓包+hex 断言。
- **影响**：#49 SSL-1 handshake 现有**第二条 manual-precedented 硬路径**（packet-capture，比 openssl 条件工具更实）；F7 加密验证从"待证"升为 **V 通有金标准先例**。**taxonomy 修正 = show / client-tool / packet-capture 三值**。

**② 环境轴定格（line B 坐实 leader heads-up）**：cert params **恒 `<vhost>,<file_path>`**（`cert/epolicy_ssl/*`）、**never inline PEM**（line B §3.1 卫生红线）——**bed 必须携 cert file trees**（试点环境前置）。

**③ I 列印证 #48 归因（line B §3.3 实证）**：SSL 金标准**每抓包步都用 I 列 inject**（`{}`←`APV_0.port1`）——**印证 #48「I 列=需求侧未证、非 K 表达不了」**：I 列 sdns 语料零用（#48 probe5 I 非空=0）、SSL 金标准大量用。sdns 没用 ≠ 框架/门做不到。

**④ SSL 试点下限（line B §6，接 #47/#48）**：SSL 测试**四能力全需**（cert 族/execute/server/I 列）——纯证书配置存在性也需 cert 族方法（编译器现 0 产出）。**SSL 试点下限=先补 cert 族 emit 表达（#23 P2-3 grammar 数据层）**。**断言形态可迁移**（TLS record found / 目的 IP found 都是现有 found/not_found 算子）——**印证 C1（form 框架级迁移）;卡点在前置 cert/execute/server 步骤 emit，非断言**。

**回应用户疑虑的核心**：#47-49 做的是签名计数/门放行/观测盘点——**#49 观测盘点确实漏了 packet-capture 这个 SSL gold-standard 验证形态**，正是"没真读用法"的实证。line B 逐用例 walkthrough 补上。

---

## §5 line A 消费 + ② framework 列填充（consume `team4_ssl_method_cards.md`）

**① 我 ② 列预判被 line A 证伪（诚实，同 #49 漏 packet-capture）**：我预判「8 方法无 SSL 专用、靠 generic cmds_config 承载」——**对 cert 操作错了**。line A 证实 cert 有 **DEDICATED method family**（apv/ssl_comm.py，25 方法）:csrVhost/importKey/importCert/importSni*/importCRLCA/sm2Import*/activeCert——**F 列直接是这些专用方法名**。预判只对 config-object subset（F3/F7 settings）成立。**② 列三分**:cert lifecycle(F1/F2/F4/F5CA/F6)=dedicated / config objects(F3/F7settings)=generic cmds_config / verification=execute+capture+routera。

**② execute anchor 更正（line A §0.1）**：#48 引的 `ssh_server.py:151 def execute` 是**死代码**（注释块 :130-160 内）;**活体在 `dic_operation.py:57`**——**#48 结论不变**（execute 走 apv_action/client_action 注册表 ~40 动作，G 层 accept execute 成立），仅 anchor 订正。

**③ 环境轴（line A 双分支 + CC3 修正）**：SSL import 双分支——本地 `.key/.crt/.pem`→读文件内联 / 否则→TFTP 硬编码 `172.16.35.215`(ssl_comm:110-113)。**CC3 实证:金标准 cert paths 全走 LOCAL inline 分支**(`.key/.crt` 结尾)——**bed 只需 local `cert/` tree(`cert/epolicy_ssl/*`)、不需硬编码 TFTP 服务器**（TFTP 分支代码有、金标准不用，降级为可选路径）。**bed 必需依赖(修正)**:① **local cert file tree(`cert/epolicy_ssl/*`，金标准必需)** ② server213/231/232 后端 config env 可达。（**TFTP .215 = 潜在代码分支、金标准 unexercised**（A:169/CC3、B:97）——作 code fact 记录,**bed 不需 .215、不列入必需依赖**。）
**#53 device-probe GREEN**：两 cell on-device 实证——① local cert trees present（`cert/epolicy_ssl` rsaca/eccca/rootca + `cert/sm2` 双证书，CC3 依赖真床满足）② server213/231/232 全可达。**SSL 试点床就绪**（cert tree + server 齐）;routerA 工具链 PARTIAL（凭证从 framework config 取中）。

**④ silent-failure surface footnote（V-layer-adjacent，line A §6）**：断言 fail 假象="断言错"非真因——**S1 cert 文件缺→print+return，import 没发生**(ssl_comm:102-104，最主风险，归因须分"文件缺"vs"证书错") / **S2 execute 动作名不中/模糊≥0.8 误派→None**(dic_operation:72) / S3 server 超时部分输出 / S4 TFTP 不可达 / S5 H 存 None。**V 层邻接假 fail 面**，归因需对号 S1-S5。

**⑤ execute 自验=观测面第四形态（line A §0.5）**：部分 execute(func_3/4)**内嵌 check_point.abs_found/found**——execute 可**自成验证**（config+断言合一），非 show/client-tool/packet-capture 之外的第四形态。

**⑥ 7 needs-probe（line A §7，床就绪）**：① import 交互 prompt 实际文本 ② 172.16.35.215 床存在+证书库 ③ execute 模糊误派率 ④ server 主机 config env 可达 ⑤ 长证书内联截断 ⑥ func_N 33 动作未逐个读全(读了 func_1/2/3/4 立范式)。

## §6 四面终 verdict 汇总

- **fully-understood**（四面齐）：**F1 证书生命周期 / F3 bindings / F4 SNI / F5 mutual auth / F6 CRL / F7 加密验证-协议**——product+method(dedicated/generic)+manual+observation(含 packet-capture)对上。
- **understood-with-gaps**：**F2 key types**(sm2 MutiCert/Key activate 被注释 A:712、show 区分度待 probe)。**（F6′ OCSP 原 with-gaps，#53 device-probe 后 obs indirect-confirmed → 升 fully，SSL 零 kernel-outside。）**
- **not-yet-understood**：**无**——func_N 33 动作细节 + 6 needs-probe 是**床就绪面、非理解 gap**。

**Empty-cell 终清单（punchline）**：① **OCSP observation**（无 show、候选待 probe） ② **F4 SNI manual**（line B 无 SNI 用例，待补 B / accept config 显然） ③ **F2 sm2 activate 注释**（line A 发现被注释，需确认设计意图 vs bug）。**framework method 列无 empty**——推翻我"无 SSL 专用方法"初判。

**总结（回应用户"没真读"）**：三线合璧=真吃透——A 逐方法读源码(25 方法 signature/双分支/静默面 file:line) + B 逐用例读用法(354 调用/packet-capture gold-standard/3 walkthrough) + C 产品特性+CLI 全表+observation 三通道。**两个初判被实证修正**（#49 漏 packet-capture、② 预判无专用方法）——正印证用户疑虑:光数/盘不够,读出来才知道。**SSL 理解层=吃透;试点前置=补 cert 族 emit(#23 P2-3) + 床就绪 probe(6 项)**，非理论/引擎缺陷。

---

# 第二部分：SLB Feature Model + 四面矩阵（#51-C，真读 slb 118 手册）

> #51-C：SLB 版对齐 #50-C 标准。真读 slb CLI 手册（不靠 #47 counts）。observation 用**四形态 taxonomy**（show / client-tool / packet-capture / execute-self-assert，#50 补齐）。manual corpus 预期 **THIN**（无独立 slb partition，SLB 用例散在 sdns/ssl 卷）——thin cells 是 findings。

## §7 Product SLB Feature Model（7 area，SLB CLI 闭集 grep 提取）

| G | feature area | config 命令(闭集频度, provenance) | show 投影 |
|---|---|---|---|
| **G1** | virtual service | `slb virtual service`(1181)/`virtual http`(171)/`virtual tcp`(121)/`virtual settings`(94)/`virtual application`(70)/`virtual tuxedo`(83) | `show slb virtual`(90) / `show statistics slb virtual`(77) |
| **G2** | real service + group | `slb real http`(296)/`real tcp`(186)/`real tuxedo`(119)/`real l`(73)/`real tcps`(71) + `slb group member`(808)/`group option`(164) | `show slb real`(77) / `show slb group`(94) / `show statistics slb real`(155) |
| **G3** | scheduling algorithms | `slb group method`(850) — rr/wrr/lc/sh/… (`SLB methods introduction.md`) | `show slb group`(含 method) |
| **G4** | health check | `slb real health`(131) + health checker(#49 footprint) | `show health server`(33)/`health group`(23)/`health passive`(21) + `show slb real health`(#49) |
| **G5** | session persistence | `slb group persistence`(241)/`persistence timeout`(132)/`policy persistent`(71) | `show slb persistence`(23) / `show statistics slb group`(SessionCount，#50 line B walkthrough) |
| **G6** | policy-rules | `slb policy default`(380)/`policy qos`(314)/`policy static`(99)/`policy persistent`(71) | `show slb policy`(126) / `show statistics slb policy`(109) |
| **G7** | stats-observability | （纯观测面，非 config） | `show statistics slb`{all(97)/global(31)/summary(30)/real(155)/virtual(77)/policy(109)/group(29)} + `show slb connection`(393) |

## §8 四面矩阵 SLB edition（product ↔ framework ↔ manual ↔ observation-四形态）

> ① product + ④ observation 我已填；② framework=待 Py-Eng SLB action cards（并行，预判 **generic cmds_config**——SLB 无 dedicated method，待 A 证/证伪）；③ manual=待 LLM-Eng SLB mining（**预期 THIN**）。

| G | ① product | ② framework (A, **CONFIRMED generic**) | ③ manual (B, 预期 THIN) | ④ observation (四形态) | verdict |
|---|---|---|---|---|---|
| G1 virtual service | ✓ slb virtual service/http/tcp | ✓ generic + client func_1 curl | ◐ **VS-reachability 1 vol**（HTTPS-VS triple=SSL∩SLB 交集） | ✓ show slb virtual（**existence/traffic standalone confirmed #53 item5**） | **first-batch**(1 先例) |
| G2 real+group | ✓ slb real/group member | ✓ generic + apv func_5/6(A:72/79) | ◐ scaffolding(slb 对象作 sdns local pool) | ✓ show slb real/group（pending probe） | with-gaps(manual 薄) |
| G3 scheduling | ✓ slb group method(rr/wrr…) | ✓ generic + client func_1 curl | ⚠ **ZERO**（rr 配 128× 但**无 volume 按流量验分布**） | ✓ show slb group + client-tool(curl 采样)+ capture（pending probe） | **DEFERRED**(无先例=novel,higher risk) |
| G4 health check | ✓ slb real health | ✓ execute func_1/209-213(A:48/257-337)+ self-assert(func_3/4/8/203) | ✓ **THICK 41 assertion lines**（good/bad real IP:port driven） | ✓ **per-entity health 走 sdns face** `show statistics sdns service ip`（#54 case002:`show statistics slb virtual` 无 Health 行）+ execute-self-assert | **first-batch**(厚先例) |
| G5 session persistence | ✓ slb group persistence/timeout | ✓ generic + execute func_219(A:409) | ⚠ **ZERO L4**（唯一命中=sdns GSLB affinity=不同物） | ✓ show statistics slb group + client-tool（pending probe） | **DEFERRED**(无先例=novel) |
| G6 policy-rules | ✓ slb policy default/qos/static | ✓ generic cmd_config | ◐ scaffolding | ✓ show slb policy（pending probe） | with-gaps(manual 薄) |
| G7 stats-observability | （观测面本身） | N/A(纯 show) | ◐ scaffolding embedded | ✓ show statistics slb 全 + show slb connection（**traffic/connection standalone confirmed #53 item5**;**health 维走 sdns face 见 G4**） | 观测最全、三维独立 confirmed(health 例外) |

## §9 SLB Per-Area Verdict + SLB vs SSL 对比

**product+observation 双侧 verdict**（framework/manual 待 A/B 合成终判）：
- **fully(product+obs)**：G1/G2/G6/G7——config 全 + show 投影全（SLB 观测**主力 show projection**，比 SSL 少 packet-capture 依赖:SLB 不加密、状态直接 show 可观测）。
- **fully+多形态**：G3 scheduling（show + client-tool curl 采样 + capture 流量分布）;G4 health（show + **execute-self-assert** func_1）;G5 persistence（show statistics SessionCount + client-tool，**manual 有 line B walkthrough**）。
- **manual THIN 是 finding**：G1/G2/G4/G6 manual 待 B——**无独立 slb partition,SLB 用例散在 sdns/ssl 卷**（如 #50 line B 的 HTTPS2 健检=sdns_health_check 卷）。thin ≠ 缺陷,是"SLB 从未作独立测试域"的实证。

**SLB vs SSL 关键差异（观测/方法两轴）**：
- **framework method 轴**：SSL cert 有 **dedicated method family**（importKey/csr…）;SLB **预判 generic cmds_config**（slb virtual/real/group 是通用配置命令、无专用 method）——**待 A 证**。若证实 → **SLB 编译 enablement 比 SSL 简单**（通用 cmds_config 够，无需 dedicated method 表达;SSL 卡在 cert 族 emit，SLB 无此卡点）。
- **observation 轴**：SSL 加密验证**需 packet-capture**（gold-standard TLS record hex）;SLB 状态**主力 show projection**（连接/健康/会话/统计设备端直接 show）——SLB observation 更实、更全（G7 stats 层丰富）。

**总（SLB product 侧）**：SLB **CLI 层完整可建模**（7 area 全，闭集实证）、**观测层最全**（show 主力 + G7 stats + 三辅助形态）、**无 observation EMPTY**（对比 SSL 的 OCSP 缺）。

**② framework CONFIRMED（line A landed）**：**slb_comm.py 空文件(0 行)——SLB 无 dedicated method，全 generic cmd_config + execute(func_1 curl/func_5-6 后端/func_209-213 健检轮询/func_219 会话保持)+ server**。**我 ② 预判这次对了**——对比 #50 SSL 预判「无 dedicated」被证伪（两个相反结论都以实证为准，预判 #50 错、#51 对，**证据说话不看运气**）。

**server contract（environment 轴，line A fact）**：config env 是 **logical-name→IP table**——bed 换=**config edit not case edit**（portability:用例引 server231/routera 逻辑名，床换只改 env 表、卷面不动）。

**NEW launch-risk row（line A §4，交 #56 gate）**：**fuzzy-dispatch semantic inversion**——execute 模糊匹配 ≥0.8 在 40 动作名上有 **9 collision pairs / 5 inverted**（健检 UP⇄DOWN、绑定⇄检查、用户⇄数据，offline-simulated）:动作名写不精确→静默派错 func→**语义反转**。正由 **A 层新 emit 门(#56，exact registry membership、§21-derived)** 关闭——我对该门的 consistency review 待 Py-Eng diff landed。

**★ SLB-first launch sequencing（两腿 confirmed，B 数据 SCOPED）**：**SLB 比 SSL 简单——但"先上 SLB"须 SCOPED**（#51-B per-G 先例厚薄 refine）:
- **first-batch（有先例、可试点）**：pure-config existence + **G4 health-flip**（B THICK 41 assertion lines,good/bad real IP:port）+ **G1 VS-reachability**（B 1 vol,还是 HTTPS-VS triple=SSL∩SLB 交集）。
- **DEFERRED（essential behavior、无先例、novel authoring 高风险、押 footprint-building 后）**：**G3 scheduling-distribution**（rr 配 128× 却**从无 volume 按流量验分布**=零先例）+ **G5 L4 persistence**（唯一命中是 sdns GSLB affinity=不同物,零 L4 先例）。
- 两腿 confirmed 仍成立（无 cert 瓶颈 + obs 更全）→ SLB-first,但**首批 SCOPED 到有先例的 G4/G1+纯配置**,G3/G5 押 footprint-building 后（无先例可仿=novel、风险高）。

**manual THIN 坐实（B 数据）**：86 卷 mention slb、**79 纯 scaffolding**（slb 对象作 sdns local pool、DNS-face 断言）、true SLB-face 仅 **7**、SLB-centric **2**——**SLB 从未作独立测试域**（§9 finding 被 B 数字实证）。

**④ observation（B fold + #53 item5 PASS + #54 case002 calibration refine）**：金标准 SLB observation 历史上 sdns-embedded——#53 item5 上机证实**对 existence/traffic/connection 三维 = CONVENTION 非 device limitation**:`show statistics slb ?` 10 独立子命令、`show statistics slb global` 零 sdns 上下文结构化输出(conn/sec、current conn、throughput、聚合 Real UP/DOWN counts、client/server 维)、`show slb connection current` 结构化连接表——**这三维 pure-SLB 编译案可 standalone 观测**。
**⚠ HEALTH 维度例外（#54 case002 device 铁证,refine #53 item5）**:`show statistics slb virtual tcp <vs>` **无 `Health:` 行、仅流量计数器**;**per-entity health UP/DOWN 状态必走 sdns service face** `show statistics sdns service ip`（global 的聚合 UP/DOWN counts ≠ per-VS/per-real 状态,health-flip 断言要 per-entity）——**health 的 sdns-embedded 是 device limitation、非 convention**（corroborates line B §3.1:health cases sdns-embedded 有实证原因,是 observation-surface fact 非习惯）。故 ④ **分维度**:existence/traffic/connection **confirmed standalone**、**health routes through sdns face**。
**data-prerequisite footnote**:per-VS stats(`show statistics slb all`)VS 配置前为空——case-structure fact(config before observe)、非 gap。matrix 除 routerA 工具链(◐ 凭证取中)全 settled。**#54 case002 归因=mindmap observation-lens 选择(Test-Eng authoring)reflow 修,非 engine/framework 缺陷**——校准赢:paper 说 pure-SLB 全维 standalone,device 说 health 是例外。

matrix 四面齐（① product + ② confirmed generic + ③ B per-G thinness + ④ pending probe）。SLB 理解层就绪,line C 收口。
