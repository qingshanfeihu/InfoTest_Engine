# SLB 金标准用例真实调用模式（任务 #51 line B）

> 用户令 2026-07-19：SLB+SSL 上线冲刺,SLB 用法挖掘对齐 #50-B 标准。read-only。金标准源=`knowledge/framework/mirror/smoke_test/`。**已知空白(#47 P1)**:smoke_test **无独立 slb 顶层分区**(顶层仅 `sdns`+`snmpd`),SLB-face 卷 embedded 在 sdns 子树 + snmpd/bug123456。**机制** cross-ref Py-Eng action cards(func_5-33 并行读,line B∥方法卡,分歧不抹平)。line C(Theory 产品特性)并行。

## 0. 一句话结论（launch-risk 发现）

**SLB 判例基座远薄于 SSL,本身即上线风险项**。全域 86 卷含 slb 命令,但 **79 卷是纯脚手架**(slb real/group 作 sdns 本地池,断言全是 DNS/sdns 面);**真 SLB-face 仅 7 卷**,其中真正 SLB-中心仅 **2 卷**(`sdns_support_slb_3` 健康翻转 + `snmpd/bug123456` VS+策略)。对比 SSL(45 卷、cert 族主力、6 目录)——**SLB 金标准调用形态单薄**。更关键:leader 点名的四模式里**两个零金标准**——**调度/分发验证=0**(rr 只作 config、无一卷发流量验分发到不同 real)、**会话持久=0**(唯 2 个 persist 命中是 sdns GSLB 持久非 SLB L4 粘)。**SLB 上线的 emit 文法可从 config 形态推,但"行为验证判例"几乎无先例可循——这是比 SSL 更硬的缺口**。

## 0.5 按 G-area 逐区 thinness 量化（喂 Theory 矩阵③,G-id 锚 feature_model §7）

> leader 协调令 2026-07-19:按 Theory 的 G1-G7 结构化。**thinness 二分**:config-face(emit 文法可推的定义用量)vs **behavior-face**(check_point 验的行为判例)——SLB 的硬缺口全在 behavior-face。

| G-id | 特性 | config-face 用量(金标准) | **behavior-face 判例** | thinness 判定 |
|---|---|---|---|---|
| **G1** | virtual service | `slb virtual` 549(define-shape 526,含 **167 IPv6**);type 闭集 http388/https78/tcps45/addrlists6/portlists6/tcp1/l2/ftplist | VS 可达 `found <vs名>`+`200 OK`(后端经 VS 响应)——**仅 1 卷**(bug123456,且 SLB+SSL+security 组合) | config 厚 / **behavior 薄(1 卷)** |
| **G2** | real+group binding | `slb real` 152 · `slb group member` 138 · `slb policy default` 164 | 无独立 real/group 行为断言——79/86 卷作 sdns 池脚手架;绑定正确性仅隐式(健康翻转间接验) | config 厚(**脚手架**) / **behavior 近零** |
| **G3** | scheduling/distribution | `slb group method` 128(**仅 rr**,无 wrr/lc/sh);hip/persistence 2(属 dot=sdns GSLB 非 SLB) | **0 分发断言**——无一卷发流量并验落到不同 real;rr 的**效果从未被验** | **最薄(近零先例)** |
| **G4** | health check | `slb virtual health on\|off` 8(VS-toggle)· real 好/坏 IP:port 驱动 | **`Health: UP/DOWN` 41 断言行**(最厚 SLB-face);walkthrough=§4.1 sdns_support_slb_3;观测经 `show statistics {sdns service ip\|slb virtual}` | **唯一充分(41 行+walkthrough)** |
| **G5** | L4 persistence | 0(金标准无 SLB 会话粘;唯 2 "persist" 是 dot 的 sdns GSLB hip/persistence) | **0**——SLB L4 session persistence 零金标准 | **零先例** |
| **G6** | policy-qos | `slb policy default` 164(默认绑定);qos/static/persistent 变体金标准近零(manual 有) | policy 命中数 `policy static\s+1` **3 行**(bug123456,且是 security service policy) | default 绑定薄 / **qos 变体零** |
| **G7** | stats/观测 | `show slb summary` 23 · `show statistics slb {virtual4\|group6\|policy3}`——共 **~36 观测调用** | G7 是 G1/G4 的**观测通道**(health/可达经它读),非独立被测面 | 观测面 ~36,支撑 G1/G4 |

**launch-risk 直读**(per-area):**G4 健康**是唯一可照判例编首批的区(41 断言行厚);**G1 可达/G6 default 绑定**各仅 1-3 卷薄先例(且绑 SSL/security);**G3 分发 / G5 持久 = 零 behavior 先例**(Theory 预判对),须**新造金标准或上机建 footprint** 才能测,首批**暂缓**。config-face(G1/G2 定义用量)全厚——emit 文法这层不缺料(已落 domain_grammar SLB 条目 #51-C)。

## 1. 全域扫描（诚实清点）

| 类别 | 卷数 | 说明 |
|---|---|---|
| 含 slb 命令(virtual/real/group/policy) | 86 | 全在 `sdns/`(85)+`snmpd/`(1)下,**无 slb 顶层分区** |
| ├ **SLB-SCAFFOLD** | 79 | slb 作 sdns 本地池脚手架;断言=DNS 解析/sdns 状态,**非 slb 行为** |
| └ **SLB-FACE**(断言/观测触及 slb 面) | 7 | 见下 |

**7 卷 SLB-FACE 明细**(检测器:观测 `show ... slb` 命令 **或** check_point 断言含 `Health:`/`policy static`/`https-vs`/VS 名):

| 卷 | SLB 面 | 语境 |
|---|---|---|
| `sdns/sdns_support_slb/sdns_support_slb_3.xlsx` | **健康翻转** UP/DOWN + `show statistics slb virtual` | sdns 集群内 SLB(最清 SLB-face) |
| `snmpd/bug123456/1234567891.xlsx` | **VS 可达+policy 命中数** + 200 OK | **SLB+SSL+security 三族组合**(见 §3.2) |
| `sdns/https_health_check/https_health_check_1.xlsx` | Health UP/DOWN | HTTPS 健检卷带 SLB 健康副断言 |
| `sdns/sdns_health_check_http2/http2_pool_relation.xlsx` | Health | 健检卷副断言 |
| `sdns/sdns_health_check_https2/https2_pool_relation.xlsx` | Health | 健检卷副断言 |
| `sdns/dot/dot_1.xlsx` · `dot_2.xlsx` | `show statistics slb policy dot` | **DoT**(DNS over TLS),slb 作 listener 脚手架;观测 slb policy 但语义是 sdns |

**SLB-face 断言实际验的行为**(7 卷去重计数):`Health: UP/DOWN`(健康翻转)**41 行** · `200 OK`(后端经 VS 响应)5 行 · `policy static N`(策略命中数)3 行 · VS 名可达 1 行。**没有一行验流量分发到不同 real**。

## 2. 列语义

同 SSL 文(`team4_ssl_usage_patterns.md` §2):`A=自动化ID · C=语句类型(步骤号) · E=测试对象(APV_0/APV_1/check_point/time) · F=方法 · G=数据 · H=寄存器 · I=format inject`。

## 3. 用法模式聚类（真实行,verbatim + file:row）

### 3.0 SLB 配置文法（86 卷全域用量,给 #52 emit 文法输入）

slb 子命令形态用量:`slb virtual` **549** · `slb group`(method/member)**270** · `slb policy` **219** · `slb real` **152** · `slb on` 1 · `slb directfwd` 1。
调度算法(`slb group method <grp> <algo>`):**`rr` 128** · `hip` 2 · `persistence` 2(后二者在 dot=sdns GSLB 非 SLB)——**实际只用 rr**,无 wrr/lc/sh 多样性。
SLB 观测命令:`show slb summary <vs>` 23 · `show statistics slb group <g>` 6 · `show statistics slb virtual <proto> <vs>` 4 · `show statistics slb policy <p>` 3。
典型配置栈(`snmpd/bug123456` r31-r41,verbatim):
```
r33 slb real http server213 172.16.35.213 80 1000 http 3    # slb real <proto> <name> <ip> <port> <maxconn> <hc-proto> <hc-...>
r34 slb real enable server213                                # 启用 real
r35 slb group method web-group rr                            # 组调度算法=rr
r36 slb group member web-group server213 1 0                 # 组成员 <grp> <real> <weight> <backup>
r37 slb virtual https https-vs 172.16.34.100 443 arp        # VS <proto> <name> <vip> <vport> <arp>
r41 slb policy default https-vs web-group                    # 策略绑 VS→组
```

### 3.1 SLB 健康翻转（唯一充分表达的 SLB-face 行为,41 断言行）

`sdns_support_slb_3.xlsx`(verbatim,健康翻转三态):
```
# 态① health off = 强制 UP(不做健检)
r37 E=APV_0  F=cmds_config G=slb virtual health off
r39 E=APV_1  F=cmd_config  G=show statistics sdns service ip "0_vs1"
r40 E=check_point F=found  G=Health:\s+UP

# 态② real 可达(好 IP:port 231:80) + health on → UP
r47 E=APV_0  F=cmds_config G=slb real http rs1 172.16.35.231 80 0 tcp 1 1 \n slb group ...
r48 E=APV_0  F=cmd_config  G=slb virtual health on
r51 E=check_point F=found  G=Health:\s+UP

# 态③ real 不可达(坏 port 666) + health on → DOWN
r58 E=APV_0  F=cmds_config G=slb real http rs1 172.16.35.213 666 0 tcp 1 1 \n slb group ...
r63 E=check_point F=found  G=DOWN               # show statistics slb virtual http vs1
r65 E=check_point F=found  G=Health:\s+DOWN
```
**机制**:改 real 的目标 IP:port(好/坏)驱动健康态翻转,`show statistics {sdns service ip|slb virtual}` 观测 `Health: UP/DOWN`。⚠**观测透镜**:主观测走 `show statistics sdns service ip "0_vs1"`(**经 sdns 服务面**,`0_vs1`=sdns 包装的 VS),辅以 `show statistics slb virtual http vs1`——即便这个"最纯 SLB-face"卷,健康态也主要经 **sdns 服务透镜**看,印证 SLB 在本语料恒 embedded 于 sdns。

### 3.2 SLB VS 可达 + policy 命中数（唯一 VS-face 卷,且为三族组合）

`snmpd/bug123456/1234567891.xlsx`(verbatim,r37-r47):
```
r37 slb virtual https https-vs 172.16.34.100 443 arp   # SLB VS(HTTPS)
r38 ssl host virtual vhost https-vs                     # SSL 卸载绑同名 vhost
r39 ssl activate certificate https-vs 1 "" all          # 激活证书
r40 ssl start vhost https-vs                            # 启 SSL
r41 slb policy default https-vs web-group               # 策略绑 VS→组
r44 E=check_point F=found G=https-vs                    # VS 名可达
r45 E=check_point F=found G=200 OK                      # 流量经 VS→real→后端 200
r46 E=APV_0 F=cmd_config  G=show statistics security service
r47 E=check_point F=found G=policy static\s+1           # security policy 命中计数=1
```
⚠**这是 SLB+SSL+security 三族组合案**(非纯 SLB):`slb virtual https` 提供 VS 入口 + `ssl host virtual/activate/start` 提供 HTTPS 卸载 + `show statistics security service`+`policy static 1` 是 **security 服务面**的策略命中(r31 `security real service r1 http …`)。**跨链 #50/#52**:本卷同时坐实 SSL cert 激活序(`ssl activate certificate <vh> <idx> "" all`/`ssl start vhost`)与 SLB VS 绑定——HTTPS-VS 场景 SSL 与 SLB 天然耦合。**给 #52**:若首批含 HTTPS-VS,emit 须同表达 slb virtual + ssl 卸载 + policy 三段。

### 3.3 execute 在 SLB 语境 ≠ SSL 式发流量（重要 cross-check）

SLB 子树的 `F=execute` G 值全是**中文动作短语**,verbatim:
- `进入ASF容器` / `退出ASF容器`(`sdns_asf_plugin_advanced`——ASF 插件容器进出)
- `指定Service健康检查DOWN：s1` / `指定类型健康检查UP：halftcp|all`(`pool_monitor_action`——**健康态注入**)

即 SLB 语境 execute = **健康态注入 / 容器进出**,**非** SSL 那种客户端发真流量。**机制** cross-ref Py-Eng execute card(§3,`dic_operation.py` 活体动作词表):这些中文动作词应在 `apv_action`/`client_action` 注册表里作独立词条——请核对健康态注入类动作词是否与流量发送类同 dispatch 还是分支。

### 3.4 零金标准的两模式（leader 点名四模式中的缺口）

- **调度/分发验证 = 0**:全域 `slb group method` 仅 `rr`(128 次,纯 config),**无一卷发流量并断言分发到不同 real**(分发断言检测器全域 0 命中)。rr 的**效果**从未被验证过。
- **会话持久 = 0**:`persist` 全域仅 2 命中(`dot_1`/`dot_2` 的 `slb group method … persistence`),但 dot=DoT,该 persistence 是 **sdns GSLB 客户端亲和**(hip/persistence 用于 DNS 解析黏),**非 SLB L4 会话粘**。SLB session persistence **零金标准**。

## 4. 完整用例 walkthrough（语料仅撑 2 个真 SLB-face）

### 4.1 `sdns_support_slb_3.xlsx` — SLB 健康翻转（sdns 集群内）

- **结构**:多 case 循环,每 case = 建 sdns 集群(n1 Local/n2 Remote Online)→ 配 `slb virtual http vs1` + `slb real`(好/坏 IP:port)+ `slb virtual health on/off` → sleep → `show statistics {sdns service ip "0_vs1"|slb virtual http vs1}` → found `Health: UP|DOWN`。
- **被测行为**:real 可达性驱动 VS 健康态;health off 强制 UP;好 real(231:80)→UP;坏 real(213:666)→DOWN。
- **验证点**:`Health: UP/DOWN` 断言(健康面,41 行主力)。**无分发验证**——只验单 real 的健康态,不验多 real 间流量分配。

### 4.2 `snmpd/bug123456/1234567891.xlsx` — HTTPS-VS(SLB+SSL+security 组合)

- **结构**:配 `security real service` → `slb real/group(rr)/virtual https/policy` → `ssl host virtual/activate cert/start` → save → sleep → found `https-vs` + `200 OK` + `policy static 1`;后段 `ssl stop/deactivate/import key` 做证书轮换重验。
- **被测行为**:HTTPS VS 端到端可达(流量经 VS→SSL 卸载→real 后端→200)+ security policy 命中计数。
- **验证点**:VS 名可达 + 200 OK(后端响应)+ policy static N(命中数)。**这是 SLB 行为最完整的一卷**,但深绑 SSL+security,非纯 SLB。

## 5. Open items（标记不猜）

1. **SLB-face 判例仅 2 真卷**:健康翻转(support_slb_3)+ HTTPS-VS 组合(bug123456);其余 5 卷 SLB 是健检/DoT 副断言。**分发验证、会话持久、纯 L4 流量发送**三类**零金标准**,#52/#54 若要覆盖须**新造判例**(无先例可迁移),这是硬缺口。
2. **健康态观测透镜**:主观测 `show statistics sdns service ip`(sdns 面),辅 `show statistics slb virtual`(slb 面);纯 SLB 部署(无 sdns)的观测形态本语料无先例——待 Theory line C 产品特性补 / 上机 probe 确认。
3. **execute 动作词分类**:SLB 语境 execute=健康态注入/容器进出,与 SSL 流量发送是否同 dispatch 归 Py-Eng card 核(§3.3)。
4. **调度算法多样性**:金标准仅 rr;wrr/lc/sh/hash 等其它算法的 config 形态与验证法本语料无——若产品支持,#52 emit 文法须从 CLI 手册(非金标准)取。

## 6. 给 #47/#52 扩域的直接输入

- **emit 文法可推**:slb virtual/real/group/policy 四子命令形态清晰(§3.0),从 config 用量可直接建 #52 emit 表达——这一层不缺料。
- **行为判例几乎为空(launch-risk)**:与 SSL 不同(SSL 有 cert 序 + TLS record + 目的 IP 抓包等成熟断言可迁移),**SLB 只有"健康翻转"一类断言有充分先例**(`Health: UP/DOWN` via `show statistics`)。VS 可达/policy 命中仅 1 卷、且绑 SSL+security。**分发/持久零先例**。故 #52/#54 SLB 首批**下限**=先做**健康翻转**类(判例最厚)+ **VS 可达 200 OK**类(判例 1 卷),**分发/会话持久暂缓**(无判例、须先造金标准或上机实证建 footprint)。
- **SLB 恒 embedded 于 sdns**:本语料所有 SLB 观测都经 sdns 服务面或在 sdns 集群语境;**纯 SLB(脱离 sdns)的部署与观测形态无金标准**——#53 床 probe 宜确认设备是否支持纯 slb 观测(`show statistics slb virtual` 独立可用),否则 SLB 试点须连 sdns 一起搭。
- **HTTPS-VS = SSL∩SLB 交点**(§3.2):HTTPS 负载均衡场景 SSL 卸载与 SLB VS 天然耦合,#52 若含此场景须两族 emit 联动(slb virtual https + ssl 卸载序 + policy)。

## 7. 给 Py-Eng action cards 的 cross-check 钩子（分歧不抹平）

1. **execute 动作词**(§3.3):SLB 语境 `进入ASF容器`/`指定Service健康检查DOWN：s1` 等中文动作词,是否在 `apv_action`/`client_action` 注册表、与 SSL 流量发送类 execute 同/异 dispatch？
2. **server/real 后端**:`slb real … 172.16.35.231 80` 的后端起停是否复用 `server231`(env.py:74 SSH 到 config host)机制、含 IP 恢复副作用？（对齐 SSL 文 §3.4）
3. **slb 观测命令 dispatch**:`show statistics slb {virtual|group|policy}` / `show slb summary` 是否走通用 cmd_config 通道、有无专用 checker？（对齐 §3.0 观测命令清单）
