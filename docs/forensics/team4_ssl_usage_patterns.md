# SSL 金标准用例真实调用模式（任务 #50 line B）

> 用户令 2026-07-19：数了 354 SSL 方法用量却没研究**怎么用**——本文挖真实调用模式。read-only。金标准源=`knowledge/framework/mirror/smoke_test/sdns/`。**卫生**:cert/key 在用例里是**文件路径**(`cert/epolicy_ssl/*`)非 inline PEM,故本文引路径+file:row、零私钥泄漏。**机制** cross-ref Py-Eng method cards(mirror 源,line B∥line 方法卡),标注见下。line C(Theory 产品特性)并行。

## 0. 一句话结论

**SSL 金标准用尽全部"编译器 105 卷零产出"的四能力**(cert 族 25 方法 / execute / server 触发端 / I 列 format inject)——#47/#23 判的能力缺口在真实用例里是**主力**,非边缘。SSL 测试 = 证书族配置 + 加密流量验证(抓包看 TLS record) + 健康检查(server 后端 + 目的 IP 断言)。

## 1. 全域扫描（45 卷,6 目录）

| 子目录 | 卷数 | 主题 |
|---|---|---|
| sdns_health_check_https2 | 23 | HTTPS2 健康检查(主力) |
| sdns_ssl_conn | 15 | SSL 加密通道(DC 间同步) |
| sdns_support_slb | 3 | SSL over SLB |
| dot | 2 | DoT(DNS over TLS)证书轮换 |
| https_health_check / sdns_dc_default_ssl | 各 1 | HTTPS 健检 / DC 默认 SSL |

**6 目录 F 列方法分布**(openpyxl 全扫):`found` 1017 · `cmd_config` 983 · `cmds_config` 664 · `sleep` 316 · **`server231` 264** · **`execute` 165** · `routera` 107 · **`importKey` 91** · **`importCert` 91** · **`csrVhost` 55** · **`importRootCA` 46** · `not_found` 17 · **`sm2ImportKey`/`sm2ImportCert` 各 16**(国密)· **`importInterCA` 5**。cert 族调用总 **320 行**。

## 2. 列语义（用例表头 r28）

`A=自动化ID · B=优先级 · C=语句类型(步骤号) · D=描述 · E=测试对象(APV_0/APV_1/check_point/time) · F=方法 · G=数据 · H=临时保存期望结果(寄存器) · I=输入变量(format inject)`。

## 3. 用法模式聚类（真实行,verbatim + file:row）

### 3.1 证书导入序列（cert-import,参数形态恒 `<vhost>, <file_path>`）

典型序(`sdns_ssl_conn_2.xlsx` r31-r35):
```
r31  E=APV_0 F=cmd_config    G=ssl host virtual vh1               # 建 ssl vhost
r32  E=APV_0 F=importKey      G=vh1, cert/epolicy_ssl/rsaca/1024rsa.key   # 导私钥(路径)
r33  E=APV_0 F=importCert     G=vh1, cert/epolicy_ssl/rsaca/1024rsa.crt   # 导证书(路径)
r34  E=APV_0 F=importRootCA   G=vh1, cert/epolicy_ssl/rsarootca.crt       # 导根CA(路径)
r35  E=APV_0 F=cmds_config    G=ssl activate certificate vh1 \n YES \n sdns ssl global vh1  # 激活+启用
```
**参数形态**:RSA 族 `importKey`/`importCert`/`importRootCA` **2 参** `<vhost_name>, <file_path>`,逗号分隔;**cert/key 永远是文件路径**(`cert/epolicy_ssl/rsaca/*.key|.crt`、`cert/epolicy_ssl/rsarootca.crt`),**从不 inline PEM**——证书文件预置于框架 `cert/` 树,用例只引相对路径。

⚠**国密 sm2 族 ≠ 同形态,是 3 参**(**订正 2026-07-19,审计痕迹保留、非静默重写**:原本文写"sm2 同形态、2 参"是**从 RSA 2 参的观察过度泛化**——sm2 只数了用量没读参数;经 **Py-Eng cross-check CC2** verbatim 实读 8 行金标准 + 源码 `sm2ImportKey(keyType,vhost,keyFile)` 逮到并纠):`sm2ImportKey(keyType, vhost, keyFile)`——**首参=密钥类型**,verbatim 如 `signkey, rh1, cert/sm2/newsm2/clientsign.key` / `enckey, rh1, …clientenc.key` / `signcertificate, rh1, …clientsign.crt`(金标准 8 次全 3 参)。因 **SM2 国密双证书体系**(签名证书 signkey/signcertificate + 加密证书 enckey/enccertificate,RSA 单证书无此首参);且 sm2 用 `rh1`(**real host**)+ client 证书 = **双向认证**语境(RSA 例多 virtual host 服务端证书)。**机制** cross-ref Py-Eng method cards §2.2(RSA:`vhost,path`→本地读文件→交互粘贴 `ssl import key/certificate {vhost} {index}`,`ssl_comm.py:89/:124`)+ §2.3(SM2 全 7 方法,`sm2ImportKey(keyType,…):572`)。

### 3.2 SSL 加密验证 = 抓包看 TLS record header

`sdns_ssl_conn_2.xlsx` r43-r45(验证 DC 间通信加密):
```
r43  E=APV_1 F=cmd_config  G=debug trace live tcp "port2" "-c 5 icmp -x"   # 抓包(-x=hex)
r44  E=check_point F=found G=172.16.34.70 > 172.16.34.71: ICMP             # 断言流向
r45  E=check_point F=found G=(1703 03)|(17 0303)                           # 断言 TLS record header
```
**`(1703 03)|(17 0303)` = TLS Application Data record 头字节**(17=ApplicationData, 03 03=TLS1.2)——**加密性验证的巧法**:抓包 hex dump 里出现 TLS record 头 ⇒ 流量确被加密。这是 SSL 测试的**标志性断言形态**(sdns_ssl_conn 多卷复用)。

### 3.3 HTTPS2 健康检查 = 配 monitor + 抓包目的 IP + show instance（用 I 列 inject）

`sdns_health_check_https2/https2_link_dst_addr.xlsx` r39-r44:
```
r39  E=APV_0 F=cmds_config G=sdns monitor https2 "h1" "HEAD / HTTP/2.0\r\n\r\n" "200" "up…"  # 配 https2 健检
r40  E=time  F=sleep       G=1
r41  E=APV_0 F=cmd_config  G=debug trace live tcp {} "-c 2 ip and port 443"  I=APV_0.port1   # 抓包 443,{}←I
r42  E=check_point F=found G=172.16.35.70.\d+ > 172.16.35.100.443            # 断言健检流向目的:443
r43  E=APV_0 F=cmd_config  G=show sdns monitor instance https2
r44  E=check_point F=found G=Address:\s+172.16.35.100                        # 断言 monitor 显示目的 IP
```
**I 列 format inject 实证**:`G="debug trace live tcp {} ..."` 里的 `{}` 由 `I=APV_0.port1` 运行时填(接口名注入)——这正是 #23 判"编译器 0 产出"的 I 列能力,金标准里**每个抓包步都用**。IPv6 变体(r51-r62)同型:`ip6 and port 443` + `3ffd::` 地址。

### 3.4 execute / server 触发端 交织（SSL 需真实流量+后端）

- **server231**(264 次):起真实后端(server IP .231),供健康检查探活/SSL 握手对端;
- **execute**(165 次):客户端动作/发流量,建立 SSL 连接;
- 交织形态:`server 起后端 → 配 ssl/monitor → execute 发流量 → sleep → 抓包/show → check_point`。
- **机制** cross-ref Py-Eng method cards:**execute** → §3(活体 `dic_operation.py:57`,**非** `ssh_server:151` 死代码;客户端动作词表 `apv_action:11-44` / client_action 注册表);**server231** → §4(`env.py:74` → SSH 到 config `env` 段主机起停后端,**副作用=IP 恢复** `ssh_server:95-100`——起后端会记账 IP、下一 case 恢复,与 framework-ip-restore 契约一致)。

## 4. 三个完整用例 end-to-end walkthrough

### 4.1 `sdns_ssl_conn/sdns_ssl_conn_2.xlsx` — SSL 通道加密同步

- **初始化**(step=1,r30-r38):两台 APV 各配 sdns + `ssl host virtual vh1` + importKey/Cert/RootCA(vh1,路径)+ `ssl activate certificate vh1/YES/sdns ssl global vh1` + `write mem` + `synconfig to p2`——**双端对称建 SSL vhost + 证书 + 启 sdns ssl 全局**。
- **case 171741758520730032**「通过 ssl 通道能同步健康检查状态」(r39-r45):APV_0 配 icmp monitor + service → sleep 5 → APV_1 `show sdns monitor instance` + found 目的 IP(验同步)→ `debug trace live tcp port2 icmp -x` 抓包 → found 流向 + found `(1703 03)|(17 0303)`(**验同步走加密通道**)。
- **case …083**「同步 SDNS 配置」(r46-r52):同型,`show sdns all` + found 配置项 + 抓包 TLS record。
- **验证点**:每 case 末尾 check_point found——功能面(配置/状态同步)+ 加密面(TLS record 头)双验。

### 4.2 `sdns_health_check_https2/https2_link_dst_addr.xlsx` — HTTPS2 健检目的地址

- 结构:每 case = 配 `sdns monitor https2`(HTTP/2 请求+期望 200)→ sleep → **`debug trace live tcp {} ... port 443` + I=APV_0.port1 抓包**(I 列注入接口)→ found 目的 IP:443(验探测流向)→ `show sdns monitor instance https2` + found `Address: <目的>`(验 monitor 记录)。
- IPv4(.100/.231)+ IPv6(3ffd::)全覆盖,同型重复。
- **验证点**:抓包目的 IP(链路面)+ show instance 地址(配置面)双验。

### 4.3 `dot/dot_1.xlsx` — DoT 证书轮换（cert-import 密集）

- 特征:**importKey/importCert 反复成对**(r34/35, r40/41, r52/53…每隔几行一对,`vhost,cert/epolicy_ssl/rsaca/2048rsa.key|crt`)——DoT(DNS over TLS)测试反复导入/切换证书验轮换。
- ⚠**open**:dot_1 的完整 case 边界与每对 import 后的断言我尚未逐行核(数据密集),walkthrough 待补细行;cert-import 反复成对的**语义**(轮换 vs 多 vhost)需 Py-Eng card + 逐 case D 列描述确认,**标 open 不猜**。

## 5. Open items（不可判、标记不猜）

1. **dot_1 完整逐行**:cert-import 反复成对的 case 边界+断言未逐行核(§4.3),待补。
2. **execute/server231 的确切动作语义**:F=execute/server231 的 G 参数(客户端动作词/后端配置)机制归 Py-Eng method card,本文只记"用了、在 SSL 流程哪一步",不猜其内部。
3. **I 列 `{}` 多占位/命名占位**:本次只见单 `{}`←`APV_0.port1`;是否有多占位/命名占位形态待全扫(§3.3 只证单占位)。
4. ~~**sm2(国密)证书族**~~ **已解决**(Py-Eng verbatim + 源码,2026-07-19):**3 参含 keyType**(非 rsa 2 参同形),SM2 双证书体系——见 §3.1 订正。
5. **cert 路径分支(Py-Eng CC3)**:金标准 cert 路径全 `.key/.crt` 结尾 → 走 importKey/Cert 的**本地文件内联分支**(读框架 `cert/` 树);TFTP/`172.16.35.215` 远程分支这些卷**不走**——即床就绪只需本地 `cert/` 树、无需 TFTP server。**给 #47**:SSL 试点床前置=本地 `cert/` 证书树,不涉 TFTP。

## 6. 给 #47 扩域的直接输入

- SSL 测试**四能力全需**(cert 族/execute/server/I 列)——#47 判"纯配置层可试点、本质行为层能力门控"由本文坐实:即便**纯 SSL 证书配置存在性**用例,也需 cert 族方法(编译器 0 产出);SSL **加密/健检**验证需抓包+I 列+server。故 SSL 试点**下限**=先补 cert 族 emit 表达(#23 P2-3 单点),否则连证书导入都编不出。
- 断言形态**可迁移**:TLS record header found、目的 IP found、show instance found——都是现有 found/not_found 算子(编译器已实弹),**卡点在前置的 cert/execute/server 步骤能否 emit**,非断言。
