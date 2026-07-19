# SSL / execute / server 触发端 模板方法 usage cards（任务 #50-A）

> 用户点破:我们**数**了 SSL 模板方法却从没**读**过——没人知道怎么用。本文=逐方法**深读 mirror 源码**产出的使用卡。
> 纪律:每条断言带 `文件:行号`,零记忆转述、零方法名推断;源码读不出的诚实标 **needs-device-probe**。
> **卫生**:绝不内联私钥/证书 PEM 内容,只引路径。
> 数据源:`knowledge/framework/mirror/lib/`(apv/ssl_comm.py 738 行 + dic_operation.py + apv/apv_action.py + client_action.py + env.py + ssh_server.py + test_xlsx.py 派发核)。生成 2026-07-19 · Py-Eng。

---

## 0. 五个关键机制发现（读出来才知道，数不出来）

1. **`ssh_server.execute`(:151) 是死代码**:`ssh_server.py:130` 的 `"""` 到 `:160` 的 `"""` 是一整个字符串块——`get_similar_function`(:132)与 `execute`(:151)**全在注释内、不可调用**。#48 里 Design 引的"ssh_server.py:151 def execute"指的是这块死代码;**活的 execute 在 `dic_operation.py:57`**(结论不变——execute 仍走 apv_action/client_action 注册表——但行号须订正,§3)。
2. **SSL import 全走"读本地文件→内联粘贴"或"TFTP 从 `172.16.35.215` 网络取"双分支**(如 `importKey:89-114`):文件名以 `.key/.crt/.pem` 结尾→本地 `open()` 读取、抽 `---BEGIN` 起的内容 `+"\n..."` 粘进 CLI;否则→拼 `... 172.16.35.215 {file}` 让设备去该 IP 取。**`172.16.35.215` 是硬编码的证书文件服务器**。
3. **文件读不到=静默失败**:`importKey:102-104` 等 `except FileNotFoundError: print(...)+return`——**不抛异常、不报错、import 没发生**,用例继续跑、断言在后面才 fail(假象是"断言错"非"文件缺")。风险主源之一。
4. **CSR 交互应答硬编码**:`csrVhost:19-33` 把国家/省/组织等 CSR 对话答案写死(US/CA/San Jose/clickarray/qa)——不参数化,worker 改不了 subject。
5. **部分 execute 动作自带断言**:`apv_action.func_3:62-66`/`func_4:68-70` 内部直接调 `check_point.abs_found/found`——execute 动作可以**自成验证**(不需另起 check_point 行),这是与"config步+check_point步分离"不同的范式。

---

## 1. 通用派发骨架（一切方法的 E/F/G/H/I 语义，`test_xlsx.py:280-336`）

| 列 | row 索引 | 语义 | 源码 |
|---|---|---|---|
| **E** | row[4] | 对象名——`value = locals().get(E)`,取实例(check_point / test_env / APV_0 / 直连槽) | :280-283 |
| **F** | row[5] | 方法名——`func = getattr(value, F)`(无默认,拼错→AttributeError 崩整卷) | :291 |
| **G** | row[6] | 参数串——`get_parameter(G)` 解析成 `(positional, kwargs)`(引号感知逗号切,`k=v`→kwargs 数字转 int);cmd_config 先拍平换行(:307-308) | :306-311 |
| **H** | row[7] | **device 步**:非空则 `locals()[H]=func(...)` 把**返回值存进 H 命名的寄存器**(:332-336);**check_point 步**:非空则期望值从 H 寄存器取(:296-299) | :293-305/:330-336 |
| **I** | row[8] | **device 步**:非空则 `parameters[0]=parameters[0].format(obj_value)`——把 I 命名的变量/`对象.属性`值 **format 注入 G 的首参**(G 首参须带 `{}` 占位)(:313-325);**check_point 步**:I 命名要搜索的结果缓冲(默认 `result` 上一步输出)(:300-304) | :313-325 |

**调用式**:`getattr(E_obj, F)(*positional, **kwargs)`,positional/kwargs 来自 G。SSL 方法/server 触发端/execute 全走此骨架。

---

## 2. SSL 证书族 usage cards（`apv/ssl_comm.py`；E=APV 设备，如 APV_0）

> `ssl_comm` 是 mixin:`cmd_config` 在此是 `pass`(:16-17),真身来自被混入的 APV 设备类(apv_ssh.py)经 SSH 发命令。所有方法**在 E=APV_0 上调**。

### 2.1 CSR 生成（4 个；无文件、纯交互对话）

| F 方法 | 签名(file:line) | G 参数 | 设备命令序列 | 返回 |
|---|---|---|---|---|
| `csrVhost` | `(vhost,len=2048,index=1)` :19 | `vhost[,len,index]` | `ssl csr {vhost} {len} {index}` + 11 步硬编码应答(YES/US/CA/San Jose/clickarray/qa×3/Y/邮箱/N/No):20-32 | 末步 result :33 |
| `csrRhost` | `(vhost,len=2048,index=1)` :35 | 同上 | 同 csrVhost(real host 变体):36-48 | :49 |
| `eccCsrVhost` | `(vhost,curve="prime256v1",index=1,signature=1,sni="")` :52 | `vhost[,curve,index,signature,sni]` | `ssl ecc csr {vhost} {curve} {index} {signature} {sni}` + 同款应答 :54-66 | 无(不 return) |
| `sm2CsrVhost` | `(vhost,curve="sm2",index=1,signature=1,yesNo="yes",passwd="click1")` :68 | 同上 | `ssl sm2 csr ...` + 应答;signature==2 时追加密码交互 :70-88 | 无 |

**值来源**:全部 literal(G)。CSR subject(US/CA/…)**硬编码不可改**(:22-28)。**输出窗口**:CSR 生成回显(PEM 请求块)——needs-probe 确认设备实际回显格式。**断言**:后跟 check_point 步搜 result。**错误**:无文件读→无 FileNotFoundError 面;param 数不符→AttributeError 崩卷。

### 2.2 服务器 key/cert 导入（importKey/importCert + _tftp）

| F 方法 | 签名(file:line) | G 参数 | 关键行为 |
|---|---|---|---|
| `importKey` | `(vhost,keyfile,passwd="",index=1)` :89 | `vhost,keyfile[,passwd,index]` | `.key` 结尾→本地读文件内联(:92-108);否则→`ssl import key {vhost} {index} 172.16.35.215 {keyfile}` TFTP(:110-113)。FileNotFoundError→print+return(:102-104)。返回 None(无末 return) |
| `importCert` | `(vhost,certfile,passwd="",index=1)` :124 | `vhost,certfile[,passwd,index]` | 同双分支;**额外自动 activate**:`ssl activate certificate {vhost} {index} "" all`+YES(:153-154)。返回 result1+result2(:155) |
| `importKey_tftp` | `(vhost,keyFile,passwd="",index=1)` :117 | 同 | 纯 TFTP 分支(:118-121),无本地读 |
| `importCert_tftp` | `(vhost,certFile,passwd="",index=1)` :158 | 同 | 纯 TFTP + 自动 activate(:163-164) |

**值来源**:`vhost`/`index`/`passwd`=literal(G);`keyfile`/`certfile`=**路径**(本地文件系统上 `.key/.crt` 文件,或 TFTP 服务器 `172.16.35.215` 上的文件名)。**设备实况**:本地分支把 PEM 内容逐行 send 进 `ssl import` 交互(prompt 'continue'→'import'→粘贴);TFTP 分支让设备去 .215 取。**断言**:activate 后跟 check_point 验 `show ssl ...`。**静默失败面**:文件缺→return None(:102-104),import 未发生。

### 2.3 多证书 / 真实服务器证书 / SNI / CA / SM2（签名+命令锚，同族机制）

| 族 | F 方法(file:line) | 签名要点 | 设备命令锚 | 特有点 |
|---|---|---|---|---|
| Multi | `importMutiKey`:166/`importMutiCert`:200(+_tftp:227/234) | `(vhost,id,keyfile/certfile,passwd)` | `ssl import key/certificate {vhost} {id}` | 加 `id`;非本地分支 regex 取 basename(:190-192) |
| Real | `importRealKey`:243/`importRealCert`:265 | `(rhost,keyfile/certfile)` | `ssl import key/certificate {rhost} 1` | rhost、index 固定 1;RealCert 自动 activate(:286) |
| SNI | `importSniKey`:290/`importSniCert`:319/`importSniRootca`:361/`importSniInterca`:398/`importSniCrlca`:425(+_tftp) | `(vhost,keyfile/certfile,domain,id=1[,passwd])` 或 `(vhost,domain,certfile)` | `ssl import key/certificate/rootca/interca/crlca {vhost} ... {domain}` | 加 `domain`(SNI 域) |
| CA | `importRootCA`:492/`importInterCA`:521/`importCRLCA`:547(+_tftp:516/541/567) | `(vhost,certfile[,sni])` | `ssl import rootca/interca/crlca {vhost}` | RootCA 错误用 `return -1`(:501)非 return None |
| SM2(国密) | `sm2ImportKey`:572/`sm2ImportCert`:599/`sm2ImportSniKey`:627/`sm2ImportSniCert`:657/`sm2ImportMutiCert`:684/`sm2ImportMutiKey`:715 | `(keyType/certType/method,vhost,keyFile/certFile[,domain][,id],index=1[,passwd])` | `ssl sm2 import/sm2 sni import {type} {vhost} ...` | 首参是**证书类型**(keyType/certType/method);Cert 类自动 activate(:622/:680),MutiCert/Key 的 activate 被**注释掉**(:712-713) |
| activate | `activeCert`:486 | `(vhost,index=1,sni='""',certType="all")` | `ssl activate certificate {vhost} {index} {sni} {certType}`+YES | 返回 result(:490) |

**共性值来源**:证书类型/vhost/id/domain/index=literal(G);key/certfile=路径(本地 or .215)。**共性错误面**:FileNotFoundError/OSError→print+`return`/`return -1`,静默(除 param 数不符→崩卷)。**共性断言**:import(+activate)后 check_point 验 `show ssl certificate/rootca/...`。

---

## 3. execute usage card（活体在 `dic_operation.py:57`，非死代码 ssh_server:151）

**机制**(`dic_operation.execute:57-80`):
1. `re.search(r'(.*)：', step)` 按**全角冒号 `：`** 切——`：` 前=动作名,`：` 后=参数(:58-62);
2. `get_same(动作名)`→在 `command_function_mapping` 精确匹配(空白无关、小写)或 synonyms 命中(:64,:17-25);
3. 命中→`func(step)`(**传完整 step 串**,func_N 自己 regex 抽 `：` 后参数)(:70);
4. 未命中→`get_similar_function` **模糊匹配 `SequenceMatcher ratio≥0.8`**(:72,:27-55)→func(step);
5. 全不中→`print(f"未找到相似函数for:{step}")`+返回 None(:79-80)——**静默失败**。

**动作注册表**(数据,按引用不内联全表):`apv/apv_action.py:11-44` 约 33 条中文动作名→func_N(如 `指定类型健康检查UP`→func_209:30、`提取发包间隔`→func_208:29、`配满16条sdns listener`→func_202:23);`client_action.py` 约 8 条=合计 ~40(与 #48 门解析数一致)。synonyms 从 `lib/apv/apv_synonyms` 文件加载(:45)。

**usage card**:
- **E**:APV 设备(apv_action,如 APV_0)/ 直连槽(client_action);**F**:`execute`;**G**:`<动作名>：<参数>` 全角冒号分隔(如 `配置白名单规则为：permit 1.1.1.1`);**H**:捕获返回(部分 func 有 return、部分 None);**I**:通常 N/A。
- **值来源**:动作名(`：`前)选 func;参数(`：`后)由 func_N 内部 regex 抽(如 `func_2:58` `re.search(r'：\s*(.*)', input_str)`)。
- **设备实况**:func_N 各异——`func_1:48-55` 循环 15× `show health server` 等 UP;`func_2:57-60` cmd_config `acl urlwhitelist rule`;**func_3:62-66/func_4:68-70 内部自带 `check_point.abs_found/found` 断言**。
- **错误/静默面**:①动作名不中→print+None(import 没发生);②**模糊匹配 ≥0.8 可能误派到相近动作**(静默走错 func,needs-probe 实证误派率);③func_N 各自的 cmd_config 失败不一定回传。

---

## 4. server 触发端 usage cards（`env.py`；E=test_env）

`server213`:66/`server231`:74/`server232`:82(及 routera/b、clientc/d/e、console)**全同模式**:
- 签名 `serverNNN(self, cmd, prompt="serverNNN#", timeout=10)`;懒初始化 `ssh_server(config,logger,"serverNNN")` 连接→`.cmd(cmd,prompt,timeout)` 返回输出(:74-80)。
- **连接**(`ssh_server.__init__:34-61`):SSH 到 `config.conf.get('env', name)` 解析的主机 IP、user=`test`/pass=`click1`、invoke_shell、`sudo su`(pass click1)切 root;prompt 默认 `{name}# `。
- **`.cmd`(:93-106)**:send `cmd+'\n'`→`read_until(prompt,timeout)` 返回窗口;**副作用**:`ip route add`/`addr add` 类命令记入 route_list/ip_list(:95-100),close 时自动 `delete`(:108-118 IP 恢复契约)。

**usage card**:E=`test_env`,F=`server231`,G=后端 shell 命令(如起停真实服务器 `systemctl stop nginx` 制造 real server DOWN),H=捕获输出,prompt/timeout 可作 kwargs。**值来源**:cmd=literal(G)。**设备实况**:SSH 到 config `env` 段命名主机跑 shell。**断言**:后跟 check_point 搜捕获窗口。**错误面**:主机不在 config `env`→`config.conf.get` 返回/连接失败(needs-probe 确认异常形态);read_until 超时返回**部分**输出(:91,非抛错)。

---

## 5. I 列 format 注入 + H 列捕获（`test_xlsx.py`）

- **I 列(:313-325)**:`parameters[0] = parameters[0].format(obj_value)`——G 首参写 `{}` 占位,I 填**变量名**或 `对象.属性`(如 `APV_0.port1`),运行时把该值注入。用途:把**上一步捕获值/设备属性**动态拼进本命令(人工用它抓设备接口名注入抓包命令,#23 范式 `dns_link_dst_addr.xlsx`)。**错误**:I 命名的对象/变量不存在→`NameError` 崩卷(:319/:324);G 首参 `{}` 结构坏(裸大括号/多占位)→`format` 抛 KeyError/IndexError 崩卷(#23 已知必崩门)。
- **H 列(:330-336)**:device 步 H 非空→`locals()[H]=func(...)` 存返回值;后续步 I=H 或 check_point H=H 引用它。**注意**:若 func 返回 None(如多数 SSL import),H 存的是 None,后续引用无意义。

---

## 6. 静默失败面 + 编译 enablement 风险汇总（供 worker 引导/grammar author）

| # | 静默失败面 | 源码 | 对编译的含义 |
|---|---|---|---|
| S1 | 证书/密钥文件缺→print+return,import 没发生但不报错 | ssl_comm:102-104 等 | worker 写 SSL 卷须确保床上文件在;断言 fail 时归因要分"文件缺"vs"证书错" |
| S2 | execute 动作名不中/模糊误派→print+None | dic_operation:79-80/:72 | 动作名须精确对齐注册表(apv_action:11-44),否则静默走错/不走 |
| S3 | server/read_until 超时→返回部分输出非抛错 | ssh_server:91 | 后端命令慢→断言搜到残缺窗口假 fail |
| S4 | 172.16.35.215 TFTP 源不可达/文件缺 | ssl_comm 各 _tftp | 环境依赖,床上须有该文件服务器+证书库 |
| S5 | H 存 None(SSL import 多数无 return)后续引用无意义 | test_xlsx:332-336 | H 捕获 SSL import 返回值多半拿到 None |
| C1 | param 数不符→AttributeError/TypeError 崩整卷 | test_xlsx:291 getattr | G 参数个数须严格对齐签名 |
| C2 | I 列变量缺/format 占位坏→NameError/KeyError 崩卷 | test_xlsx:319-325 | I 注入用法脆,须先捕获再引用 |

**enablement 结论**(呼应 #48):门不挡这些方法(结构门对 APV 设备 F 不设白名单,structural_gate:559-561),但**正确写出它们需要**:①动作名/命令语法从 apv_action 注册表+手册现查(不能盲写);②证书文件+TFTP 服务器+后端主机的**床就绪**(S1/S4);③worker 走 steps 原生通道表达(blocks 无 execute/SSL kind)。属 prompt+data+环境三面,非改引擎代码。

---

## 7. needs-device-probe 诚实清单（源码读不出、须上机确认）

1. **设备实际交互 prompt 文本**:方法 `cmd_config(x, 'continue'/'import'/':')` 的第二参是框架**等待的** prompt 正则,但设备**实际回显**的 CSR/import 对话文本源码看不到——须 probe 一次真实 SSL import 看窗口。
2. **172.16.35.215 在当前床是否存在+证书库内容**:硬编码文件服务器,`env` 拓扑是否含它、`serv_certs` 目录有哪些证书——probe/查 network_topology.json。
3. **execute 模糊匹配(≥0.8)实际误派率**:给定一个动作名会不会误命中相近 func——须构造样本实测。
4. **server213/231/232 主机在当前 config `env` 段是否配置**:后端服务器 SSH 可达性——probe 跳板机 config。
5. **本地文件分支的"内联粘贴"在长证书下是否被 CLI 截断**:PEM 逐行 send 的可靠性——probe 长证书导入。
6. **func_N 各动作的确切设备命令与返回**:apv_action 33 个 func_N 未逐个读全(本文读了 func_1/2/3/4 立范式);逐个精读是 #50 后续 line(execute 40 动作深读)可承接。

**门槛达成度**:SSL 25 方法 + execute 机制 + server 触发端 + I/H 列——**签名/派发/文件源/命令锚/静默面已从源码吃透**;设备实况面 6 项 needs-probe。建议试点前先 probe §7 的 1/2/4(床就绪),再动 grammar author。

---

## 8. F-area 标签映射（供 Theory 四方矩阵按 id 填，锚 `team4_slb_ssl_feature_model.md` F1-F7）

| 方法（本文 card） | F-area | 依据 |
|---|---|---|
| csrVhost/csrRhost(§2.1) | **F1** 证书生命周期 | `ssl csr` |
| eccCsrVhost(§2.1) | **F1+F2** | `ssl ecc csr`(ECC key type) |
| sm2CsrVhost(§2.1) | **F1+F2** | `ssl sm2 csr`(SM2 key type) |
| importKey/importCert(+_tftp)(§2.2) | **F1** | `ssl import key/certificate` |
| importMutiKey/importMutiCert(+_tftp)(§2.3) | **F1** | 多证书 `{vhost} {id}` |
| importRealKey/importRealCert(§2.3) | **F1+F3** | `{rhost}`(real host binding) |
| importSniKey/Cert/Rootca/Interca/Crlca(+_tftp)(§2.3) | **F4** SNI | `... {domain}` |
| importRootCA/importInterCA(+_tftp)(§2.3) | **F5** mutual auth | `ssl import rootca/interca`(CA 链) |
| importCRLCA(+_tftp)(§2.3) | **F6** CRL | `ssl import crlca` |
| sm2Import{Key,Cert,SniKey,SniCert,MutiKey,MutiCert}(§2.3) | **F2**(Sni 变体+F4) | `ssl sm2 import`(SM2 key type) |
| activeCert(§2.3) | **F1** | `ssl activate certificate` |
| execute(§3) | **跨切**(F-verification 支撑) | 非 config F-area;发流量/健检验证 |
| server 触发端(§4) | **跨切**(后端起停) | 非 config F-area;real server UP/DOWN 验证 |

**注**:F6′ OCSP / F7 protocol-cipher / F3 profiles(`ssl host`) 等**无专用模板方法**——走通用 `cmd_config`(`ssl settings ocsp/protocol/host ...`),不在本 SSL-方法族。故 SSL-方法族集中在 F1/F2/F4/F5/F6-CRL,F3/F7/OCSP 靠 cmd_config 承载(Theory 矩阵② framework-method 列对这些应标"通用 cmd_config,无专用方法")。

## 9. 金标准真实调用交叉核对（vs LLM-Eng line B `team4_ssl_usage_patterns.md`；openpyxl 实读，逐条源码↔观察对账）

> leader 令:分歧=finding 不抹平。以下用 `smoke_test/sdns/**/*.xlsx` verbatim G 列(openpyxl 实读)核对我 §2 源码分析。

| # | 核对项 | 源码(我 §2) | 金标准观察(verbatim G) | 裁定 |
|---|---|---|---|---|
| CC1 | importKey/importCert 参数数 | 2 必需(vhost,keyfile)+2 可选(passwd,index)默认 :89/:124 | `vhost,cert/epolicy_ssl/rsaca/2048rsa.key`(54 次全 2 参) | ✅ **一致**——golden 只传 2、靠默认 |
| CC2 | **sm2ImportKey/Cert 参数数** | **3 必需(keyType,vhost,keyFile)** :572/:599 | `signkey, rh1, cert/sm2/newsm2/clientsign.key` / `enckey, rh1, ...clientenc.key` / `signcertificate, rh1, ...clientsign.crt`(8 次全 3 参) | ⚠ **FINDING**:sm2 是 **3 参**,首参=密钥类型(sign/enc)。**我源码读对、LLM-Eng「国密同形态」泛化漏了 sm2 首参**——SM2 国密**双证书体系**(签名证书+加密证书),RSA 单证书无此首参。建议 LLM-Eng line B 订正 sm2 形态、Theory F2 矩阵按 3 参填 |
| CC3 | import 文件分支哪条被走 | 双分支:`.key/.crt/.pem`→本地内联 / 否则→TFTP `172.16.35.215` :92/:110 | golden 路径全 `.key/.crt` 结尾(`cert/epolicy_ssl/...`) | 🔧 **精化**:golden **全走本地文件内联分支**,TFTP/172.16.35.215 分支这些卷**不走**。→ 床就绪只需本地 `cert/` 证书树(非 .215 服务器);§0-2 的"双分支"应侧重本地为主路 |
| CC4 | sm2 用在何处(bonus) | sm2ImportKey 首参 keyType :572 | `rh1`(real host)+`clientsign/clientenc` | 📌 SM2 双证书用于 **real-host 客户端证书**(F5 mutual auth 语境),非 vhost 服务端 |

**cross-ref 回应 LLM-Eng 三锚**:① importKey/importCert 设备侧映射=本文 §2.2(`vhost,path`→本地读文件→`ssl import key/certificate {vhost} {index}` 交互粘贴,file:line :89/:124);② execute 客户端动作词表=§3(`dic_operation.py:57` 活体 + apv_action:11-44/client_action 注册表,**非** ssh_server:151 死代码);③ server231 后端起停契约=§4(`env.py:74`→SSH 到 config `env` 段主机跑 shell,IP 恢复副作用 ssh_server:95-100)。**sm2 族覆盖确认**:本文 §2.3 SM2 行覆盖全 7 sm2 方法(含金标准 16 次用的 sm2ImportKey/Cert),形态已按 3 参核正(CC2)。
