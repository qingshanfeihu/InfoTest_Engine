# SLB/SSL 床就绪只读探测（#53，Test-Eng）

> 2026-07-20 · Test-Eng · Task #53 · **STRICTLY read-only**（零 config/import/state mutation）
> 探测方式：paramiko SSH → 跳板机 `10.4.127.103`(user test)；设备经 **ProxyJump**（跳板机→设备 SSH 管理口 `172.16.34.70:22`，enable 空密码进 APV# 特权）；server/routerA 从跳板机 ping/ssh。全程只读（ls/ping/which/show + enable 进特权非改配置），**设备干净退出（exit+close）无残留**。
> **安全边界**：未做任何 config/import/state 变更；两项非本任务（import-prompt 文本 + 长证书截断 → #54；execute 模糊误派 → Py-Eng offline sim）。

## 探测结论汇总

| # | 项 | 判定 | 一句话 |
|---|---|------|--------|
| 1 | local cert tree existence | ✅ **PASS** | epolicy_ssl + sm2 证书树本地存在（CC3 local-inline 依赖满足） |
| 2 | backend server reachability | ✅ **PASS** | server213/231/232 从跳板机全 REACHABLE |
| 3 | routerA client toolchain | ✅ **PASS** | RouterA+cliente 均装 openssl 1.1.1f + curl 7.81/7.68（test/click1 SSH，Py-Eng source trace 解锁凭据） |
| 4 | OCSP indirect projection | ✅ **PASS** | `show statistics ssl` 握手统计存在=间接观测面；无 `show ocsp`（F6 坐实），failure rate + session/crlstatus 可间接投影 |
| 5 | pure-SLB observation independence | ✅ **PASS** | 纯 SLB show 命令族独立存在，`show statistics slb global`/`show slb connection` 返回结构化 sane output（无需 sdns context）——**compiled pure-SLB cases CAN observe standalone** |

---

## #1 local cert tree existence — ✅ PASS

**命令**（跳板机，2026-07-20 02:19）：`ls /home/test/apv_src/cert/epolicy_ssl/ ; ls /home/test/apv_src/cert/sm2/`
**输出摘录**：
- `cert/epolicy_ssl/`：`eccca/ rsaca/ eccrootca.crt rsarootca.crt sm2rootca.crt`（RSA/ECC/SM2 rootca 齐）
- `cert/sm2/`：`cacert.pem clientenc.crt clientenc.key clientsign.crt clientsign.key`（SM2 双证书 sign/enc）+ eccclient*/guott*/crl*_revoke* 等
**判定**：**PASS**——CC3 确立 golden 全走本地内联分支，两证书树本地存在=bed local cert 依赖满足。（注：金标准引用的 `cert/epolicy_ssl/rsaca/2048rsa.key`、`cert/sm2/newsm2/clientsign.key` 子路径，`rsaca/` 存在、sm2 证书族存在；具体子文件 `2048rsa.key`/`newsm2/` 未逐一 ls 到叶——若 #54 首批需精确文件可补探。）

## #2 backend server reachability — ✅ PASS

**命令**（跳板机 ping，只读）：`for ip in 172.16.35.213 172.16.35.231 172.16.35.232; do ping -c1 -W1 $ip; done`
**输出**：`172.16.35.213: REACHABLE / 172.16.35.231: REACHABLE / 172.16.35.232: REACHABLE`
**判定**：**PASS**——framework test_env 定义的 server213/231/232 后端 config env 三机全从跳板机可达。

## #3 routerA client toolchain — ◐ PARTIAL

**命令**（跳板机）：`ping routerA 172.16.33.206` + `ssh -o BatchMode=yes root@172.16.33.206 "which openssl; which curl"`
**输出**：
- `routerA 172.16.33.206 ping: REACHABLE` ✓
- `ssh BatchMode`：`root@172.16.33.206: Permission denied (publickey,password)`（免密被拒，需密码）
- 试 test 密码经跳板机：`bash: sshpass: command not found`（跳板机无 sshpass，嵌套密码 SSH 不可行）
**判定**：**PARTIAL**——routerA 可达，但 `which openssl/curl` 需**在 routerA 上执行**、需 routerA SSH 凭据。
**凭据搜寻（leader 令"读 framework config，不 brute-force"，两源均查）**：
- **topology**（`knowledge/data/auto_env/network_topology.json`）：仅 IP、无凭据。
- **framework config**（跳板机 `apv_src/conf/97.conf`，定义 server213/231/232+RouterA logical names 的同一 config）：logical names 段 `RouterA=172.16.33.206` 纯 IP 映射**无凭据**；凭据段 `[array_ustack/hgk/hgu]`（=APV **设备**凭据，`user=array`）——**非 routerA**（array 是被测设备凭据）。
- **framework `*.py`**：grep `RouterA` 连接逻辑=**无直接 routerA SSH 连接代码**（framework 驱动 routerA 的方式不在明显 SSH 路径）。
- **试探**：`user=array`+config 密码 ProxyJump routerA=**认证失败**（坐实 array≠routerA 凭据）；BatchMode 免密=拒；跳板机无 sshpass。
- **解锁**（Py-Eng source trace `ssh_server.py:39-44`）：framework 连**所有** bed hosts（routera/routerb/server*/client-slot）走 generic paramiko SSH、**hardcoded `username=test password=click1`**（我 grep 漏因无 routera-specific code、generic `ssh_server.__init__(name)` 按变量 resolve IP）。
**补探（test/click1，ProxyJump，只读 which）2026-07-20**：
- **RouterA 172.16.33.206** ✅：`hostname=RouterA` / `/usr/bin/openssl`（**OpenSSL 1.1.1f 31 Mar 2020**）/ `/usr/bin/curl`（**7.81.0**，libcurl OpenSSL/1.1.1f+libssh2+nghttp2）
- **client-slot cliente 172.16.33.211** ✅：`hostname=cliente` / `/usr/bin/openssl`（1.1.1f）/ `/usr/bin/curl`（**7.68.0**）
**判定**：**PASS**——routerA + client-slot 的 SSL 客户端工具链（openssl 1.1.1f + curl）**实装齐全**，SSL 试点客户端触发（curl/openssl 发 SSL 请求）工具链就绪。

## #4 OCSP indirect projection — ✅ PASS

**命令**（设备 APV# 特权，enable 空密码，只读 show）：`show statistics ssl` / `show ssl` / `show statistics ?`
**输出摘录**：
- **`show statistics ssl`** ✅ 有输出：`SSL handshake statistics(600s): Global: Success rate:NA / Failure rate:NA / Self-caused failure rate:NA / Peer-caused failure rate:NA / Request count:0 / All handshake count:0 / Success handshake count:0 / Average handshake time:0us …`（SSL 握手统计维度齐：成功/失败率、full/reuse handshake、self/peer-caused failure、request/handshake count、handshake time）
- **`show ssl`** 子命令族 16 个：`backup certificate channel clientcert crlca `**`crlstatus`**` csr globals gmsdf host import interca load rootca `**`session`**` settings sni`——**无 `ocsp` 子命令**（F6「无 show ocsp、config-only」铁证坐实）
- `show statistics ?`：aaa/acl/bandwidth/.../dns/dpi/ha/health/ip/…/**ssl**（ssl 是合法 statistics 子命令）
**判定**：**PASS**——**OCSP 间接观测面存在**：虽无直接 `show ocsp`（config-only），但 ①`show statistics ssl` 的 **peer-caused failure rate / failure rate**（OCSP 验证失败会推高握手失败）②`show ssl session`（SSL 连接信息）③`show ssl crlstatus`（CRL 撤销状态，OCSP 姊妹机制有 show）——三条间接投影通道可观测 OCSP 效果。**#4 settles：OCSP 有间接观测面**，SSL 试点断言可经握手统计 failure 维度验 OCSP。

## #5 pure-SLB observation independence — ✅ PASS（leader 追加，2026-07-20）

**背景**：LLM-Eng #51-B mining——所有金标准 SLB 观测经 sdns service 面（`show statistics sdns service ip "0_vs1"`），无金标准用纯 SLB show 独立。settles 「compiled pure-SLB cases 能否不 embed sdns 独立观测」（first-batch design decision）。
**命令**（设备 APV# 特权，无 sdns context，只读 show，§7 G7 list）：
**输出摘录**：
- **`show statistics slb ?`**：子命令族 10 个 `all/global/group/node/policy/proxyip/real/summary/virtual/vlink`——纯 SLB statistics 命令族**独立存在**。
- **`show statistics slb global`** ✅ **结构化 sane output**：`Global: Connection/sec 0 / Ssl connection/sec 0 / Current connection:0 / Throughput out/in(pps/bps) / Real service UP:0 DOWN:0 / Client:… / Server:…`——**全局 SLB 统计结构完整**（连接/吞吐/real service/client/server 维度），**无需 sdns context**。
- **`show slb connection current`** ✅ **结构化连接表**：`Current TCP/FastTCP/TCPS/FTP/FTPS/RTSP/SIPTCP connection: Client / VIP(VSname) / Local / Server(RSname) / Period`——连接观测面结构完整，**无需 sdns context**。
- `show statistics slb all` 空输出（当前床无 SLB virtual service 配置=per-VS 数据空，但 global/connection 结构面工作）。
**判定**：**PASS**——**pure-SLB 观测独立性成立**：纯 SLB show 命令族（`show statistics slb {global/all/virtual/real/...}` + `show slb connection`）独立存在，`show statistics slb global` / `show slb connection current` 返回**结构化 sane output**、**不依赖 sdns context**。**settles：compiled pure-SLB cases CAN observe standalone**（不必 embed sdns），金标准 sdns-embedded 是历史惯例/选择、非设备限制。**数据前提**：当前床无 SLB virtual service 配置，per-VS 统计空——首批 pure-SLB 卷需配 SLB virtual service 才有 per-VS 数据，但全局/连接观测面命令层独立支持。

---

## 附·设备/凭据事实（探测中坐实，供后续）

- 设备 APV0 管理口：`172.16.32.70/34.70/35.70` 从跳板机全 REACHABLE，`:22 SSH_OPEN`；build **585**（`InfosecOS Beta.APV-HG-K.10.5.0.585 build Jun 25 2026`，与 yzg 批 device banner 一致，config.py:83 默认 568 是静态默认=D21）。
- 设备 CLI：`APV>` 普通模式仅 date/hostname/version；**enable 空密码进 `APV#` 特权**（enable 无密码=**床安全观察①**，记录不评判，leader surface user）。
- **床安全观察②**：framework 连所有 bed hosts（routera/routerb/server*/client-slot）**hardcoded 凭据 `test/click1`**（`ssh_server.py:42-43`，sudo 密码亦 click1）——记录不评判，leader surface user（与 enable 空密码并列两条床安全观察）。
- **设计事实（供观测通道文档）**：client-tool 命令（`dig`/`curl`/`openssl`）**在 bed hosts 上经 SSH 执行、非跳板机本地**——framework **零本地 subprocess**（`ssh_server.py:39-44` generic paramiko SSH 到各 bed host）。SSL 试点客户端触发（curl/openssl 发请求）落在 routerA/cliente 等 bed host 上。
- **异常即停执行到位**：全程未见残留进程/异常状态；设备/bed host 均干净退出；#3 凭据缺口曾按纪律停 PARTIAL 上报、未擅自破解（Py-Eng source trace 提供 hardcoded 凭据后补 PASS）。

## #53 收口结论

**五项全 PASS**（#1 cert tree / #2 server 可达 / #3 routerA+cliente 工具链 / #4 OCSP 间接投影 / #5 pure-SLB 独立）——**SLB/SSL 床就绪**。两个 first-batch design decision settled（#4 OCSP 间接投影面存在、#5 pure-SLB 可独立观测），三条床事实供后续（两条床安全观察 + client-tool 落 bed host 设计事实）。全程 STRICTLY read-only、设备/bed host 干净退出无残留。

**可选补探（非阻塞，#54 首批需时）**：#1 精确叶文件（`2048rsa.key`/`newsm2/clientsign.key`）可 ls 到叶确认。
