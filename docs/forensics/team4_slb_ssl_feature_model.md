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
| F6′ **OCSP** | ✓ settings ocsp (config-only) | ✓ **generic cmds_config**（无专用 import、settings 类） | **(待B)**（line B 无 OCSP 用例） | ⚠ 无 show ocsp;packet-capture 候选待 probe | **with-gaps**（obs 缺，punchline①） |
| F7 **加密验证/协议/cipher** | ✓ protocol/ciphersuite/reneg/reuse | ✓ **generic cmds_config**(settings) + **execute**(dic_operation:57) + **execute 自验**(func_3/4 内嵌 check_point,A:62-70) | ✓ line B §3.2 packet-capture | ✓ **packet-capture hex**(`debug trace live tcp {} -x`+found TLS record,I 列 inject) + show statistics ssl | **fully**,packet-capture=gold-standard + execute 可自成验证 |

## §3 Per-Area Verdict + Empty-Cell Punchline

**product+observation 双侧（我这半）verdict**（framework/manual 待 A/B 落地后合成终 verdict）：
- **fully-modeled (product+obs)**：F1 证书生命周期 / F3 bindings / F4 SNI / F5 mutual auth / F6 CRL / F7 协议-cipher-session——**config CLI 全 + show 投影全**（观测 V 通）。
- **modeled-with-obs-gap**：F2 key types（config 全，但 RSA/ECC/SM2 在 show ssl certificate 的**呈现区分度待 device probe**）。
- **obs-EMPTY（punchline①）**：**F6′ OCSP**——config 有(`ssl settings ocsp`)、**观测 EMPTY**（无 show ocsp，#49 needs device probe）。这是「有 operation、无 observation」的 empty cell。

**Empty-cell punchline（deliverable 的重点，待 A/B 填后完整）**：
1. **无 observation 的 operation**：**OCSP**（config 可下发、无 show 投影核实）——已定格 #49 needs device probe。
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

**④ silent-failure surface footnote（V-layer-adjacent，line A §6）**：断言 fail 假象="断言错"非真因——**S1 cert 文件缺→print+return，import 没发生**(ssl_comm:102-104，最主风险，归因须分"文件缺"vs"证书错") / **S2 execute 动作名不中/模糊≥0.8 误派→None**(dic_operation:72) / S3 server 超时部分输出 / S4 TFTP 不可达 / S5 H 存 None。**V 层邻接假 fail 面**，归因需对号 S1-S5。

**⑤ execute 自验=观测面第四形态（line A §0.5）**：部分 execute(func_3/4)**内嵌 check_point.abs_found/found**——execute 可**自成验证**（config+断言合一），非 show/client-tool/packet-capture 之外的第四形态。

**⑥ 7 needs-probe（line A §7，床就绪）**：① import 交互 prompt 实际文本 ② 172.16.35.215 床存在+证书库 ③ execute 模糊误派率 ④ server 主机 config env 可达 ⑤ 长证书内联截断 ⑥ func_N 33 动作未逐个读全(读了 func_1/2/3/4 立范式)。

## §6 四面终 verdict 汇总

- **fully-understood**（四面齐）：**F1 证书生命周期 / F3 bindings / F4 SNI / F5 mutual auth / F6 CRL / F7 加密验证-协议**——product+method(dedicated/generic)+manual+observation(含 packet-capture)对上。
- **understood-with-gaps**：**F2 key types**(sm2 MutiCert/Key activate 被注释 A:712、show 区分度待 probe);**F6′ OCSP**(obs 无 show、packet-capture 候选待 probe，punchline①)。
- **not-yet-understood**：**无**——func_N 33 动作细节 + 6 needs-probe 是**床就绪面、非理解 gap**。

**Empty-cell 终清单（punchline）**：① **OCSP observation**（无 show、候选待 probe） ② **F4 SNI manual**（line B 无 SNI 用例，待补 B / accept config 显然） ③ **F2 sm2 activate 注释**（line A 发现被注释，需确认设计意图 vs bug）。**framework method 列无 empty**——推翻我"无 SSL 专用方法"初判。

**总结（回应用户"没真读"）**：三线合璧=真吃透——A 逐方法读源码(25 方法 signature/双分支/静默面 file:line) + B 逐用例读用法(354 调用/packet-capture gold-standard/3 walkthrough) + C 产品特性+CLI 全表+observation 三通道。**两个初判被实证修正**（#49 漏 packet-capture、② 预判无专用方法）——正印证用户疑虑:光数/盘不够,读出来才知道。**SSL 理解层=吃透;试点前置=补 cert 族 emit(#23 P2-3) + 床就绪 probe(6 项)**，非理论/引擎缺陷。
