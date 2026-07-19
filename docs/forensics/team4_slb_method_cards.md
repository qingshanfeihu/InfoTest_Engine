# SLB / execute 全动作 / server 触发端 模板方法 usage cards（任务 #51-A）

> 承 #50-A(`team4_ssl_method_cards.md`) 同标准:逐方法读 mirror 源码、每条带 `文件:行号`、零记忆转述、读不出标 **needs-device-probe**。
> 本文 = SLB 侧 digest + **execute 40 动作全读**(#50-A 只立 func_1-4 范式) + **模糊碰撞离线仿真**(#53 拆出)。cross-ref SSL cards by §id。
> 数据源:`knowledge/framework/mirror/lib/`。生成 2026-07-19 · Py-Eng。

---

## 0. 关键发现（读出来的）

1. **`slb_comm.py` 是空文件(0 行)**——**SLB 无专用模板方法**。SLB 配置全走通用 `cmd_config`(`slb virtual/real service`、`ssl host {real|virtual} <host> <slb_service>` 等),与 SSL 的 F3 profiles/F7 protocol 同构(#50-A §8 注:无专用方法、cmd_config 承载)。**SLB 的"模板方法"实为 execute 动作 + client curl**。
2. **execute 才是 SLB 的能力核心**:client_action `func_1(访问)`=`curl -kv {url}`(发流量到 VIP)、apv_action `func_5/6`=RS 内容/header(HTTP POST 到后端 .231:12345)、`func_1/209/210/212/213`=健康检查等待、`func_219`=`show slb per se`(会话保持表)。SLB 流量/健检**全靠 execute + server 触发端**,非专用方法。
3. **模糊匹配 ≥0.8 有真碰撞**(§4):9 对,含**语义反转危险对**(健检 UP⇄DOWN、绑定⇄检查、用户⇄数据)——动作名写不精确会静默派错 func。
4. **execute 动作大量内嵌 `show`+循环重试**(func_1/101/209… `for i in range(10~20): cmd_config('show ...'); if 命中 break; sleep`)——execute 动作**自带轮询等待语义**,非单发命令。
5. **部分 execute 动作自带断言**(#50-A 已立):func_3/4/8/203 内部调 `check_point.found/abs_found`——可自成验证。

---

## 1. execute 40 动作注册表 cards（apv_action 32 + client_action 8，全读）

**派发**(#50-A §3):`dic_operation.execute:57` 按全角 `：` 切→`get_same` 精确/synonym→`get_similar_function` 模糊≥0.8→`func_N(step)`。func_N 从 step `：` 后 regex 抽参。**E=APV 设备走 apv_action、E=直连槽走 client_action**。

### 1.1 apv_action（E=APV_0 等；`apv/apv_action.py`）

| 动作名(G 的`：`前) | func | 设备命令(cmd_config/cmd) | 参数(`：`后) | 返回/自带断言 | SLB 相关 |
|---|---|---|---|---|---|
| 等待健康检查up | func_1:48 | `show health server`×15 轮询等 UP | 无 | None;无断言 | ✅ SLB 健检 |
| 配置白名单规则为 | func_2:57 | `acl urlwhitelist rule "{rule}" "{vs.name}"` | rule | result | ◐ L7 |
| 检查白名单里有 | func_3:62 | `show acl urlwhitelist rule` | rule | **自带 abs_found** | ◐ L7 |
| 检查白名单permit一次 | func_4:68 | `show statistics acl urlwhitelist {vs.name}` | 无 | **自带 found `permit:\s+1`** | ◐ L7 |
| rs 响应内容为 | func_5:72 | **HTTP POST** `172.16.35.231:12345/add_page` | content | response | ✅ RS 后端 |
| rs 添加header | func_6:79 | **HTTP POST** `.../add_header` | content | response | ✅ RS 后端 |
| 批量绑定30个常见的错误码 | func_7:86 | `http errpage apply v123456 {code} page.html`×30 | 无 | result | ◐ L7 |
| 批量检查绑定的30个常见的错误码 | func_8:96 | `show http errpage apply v123456 0` | 无 | **自带 abs_found×30** | ◐ L7 |
| 等待ha link状态up | func_101:107 | `show ha status link`×10 等 `UP UP` | 无 | None | ◐ HA |
| 等待ha domain状态up | func_102:117 | `show ha status domain`×10 | 无 | None | ◐ HA |
| 获取数据库备份包名 | func_201:128 | `show database backup package`+regex | 包名前缀 | 匹配名/None | — |
| 配满16条sdns listener | func_202:138 | `sdns listener 172.16.34.70 {1..16}` | 无 | result | SDNS |
| 检查16条sdns listener配置结果 | func_203:145 | `show sdns listener` | 无 | **自带 found×16** | SDNS |
| 获取PID | func_204:152 | `cmd` shell `ps -ef\|grep {name}` | 进程名 | PID | — |
| 进入/退出ASF插件 | func_205:158/func_206:169 | `cmd` nerdctl exec 进容器 | 无 | result | 容器 |
| 配置DNSSEC | func_207:174 | `sdns dnssec keygen/keypub/zonesig` | 域名 | result | SDNS |
| 提取发包间隔 | func_208:208 | **纯解析** input_str 里 tcpdump 时间戳算差 | 抓包文本[\|filter] | 秒差字符串 | ◐ 抓包 |
| 指定类型健康检查UP | func_209:257 | `show sdns monitor instance {type}`×15 等 UP | type[\|all] | None | ✅ 健检 |
| 指定类型健康检查DOWN | func_210:281 | 同上等 DOWN | type[\|all] | None | ✅ 健检 |
| 提取PTR自动生成名称 | func_211:304 | **纯解析** input_str 抽 autoptr 名 | 文本\|keyword | ptrname/None | SDNS |
| 指定Service健康检查DOWN | func_212:319 | `show sdns service status`×15 等 DOWN(子集) | 服务名（`，`分隔） | None | ✅ 健检 |
| 指定Service健康检查UP | func_213:337 | 同上等 UP | 同 | None | ✅ 健检 |
| 检查区域传输AXFR/IXFR同步成功 | func_214:355/func_215:366 | `show sdns record` 轮询(soa/变化) | 无 | None | SDNS |
| 检查STUB区域传输AXFR/IXFR | func_216:378/func_217:388 | `cmd` `cat .../zone/...rev` 轮询 | zone名 | None | SDNS |
| 检查HA初始化成功 | func_218:400 | `show ha status`×15 等非 Init | 无 | None | ◐ HA |
| 检查备机同步会话保持表是否成功 | func_219:409 | `show slb per se`+归一化比对 | 期望表文本 | Success/Failed | ✅ **SLB 会话保持** |
| 提取日志告警最小时间间隔 | func_220:437 | **纯解析** input_str Threshold 行时间戳 | 日志文本 | 秒差 | — |
| 检查CRL下载是否完成 | func_221:486 | `show ssl crlstatus [vhost]`×20 等非 Downloading | [vhost] | None | SSL-F6 |
| 获取接口的MAC地址 | func_300:501 | **纯解析** input_str 抽 ether MAC | show interface 文本 | MAC/None | — |

### 1.2 client_action（E=直连槽/客户端；`client_action.py`）

| 动作名 | func | 命令 | 参数 | 返回 | SLB 相关 |
|---|---|---|---|---|---|
| 访问 | func_1:17 | `curl -kv {url}` | url | curl 输出 | ✅ **SLB 流量核心**(发请求到 VIP) |
| dnsperf访问域名解析 | func_201:24 | `cmd {command}`+可选 regex 抽值 | 命令[，抽取键] | 值/'0' | SDNS 压测 |
| 登录/退出Mysql | func_202:46/func_203:66 | `mysql -u{user} -p`→密码;DROP/exit | 用户，口令[，库] | result | DB 后端 |
| 创建Mysql数据库用户 | func_204:88 | `CREATE USER/GRANT` | 用户，口令，源IP | None | DB 后端 |
| 创建Mysql数据库数据 | func_205:104 | `CREATE DATABASE/表/插入` | 库，建表，插数据 | None | DB 后端 |
| ssh登录 | func_206:122 | `ssh {user}@{ip}`+可选 en/cli | user[:pw]@ip[\|新密码][&cli] | result | 后端 |
| 获取SSLsessionid | func_300:180 | **纯解析** input_str 抽 `Session-ID:` | 含 SessionID 文本 | sessionid | ✅ SSL 会话复用 |

**值来源**:动作参数全来自 step 文本(`：`后,func_N 内 regex 抽);多参用**全角逗号 `，`** 或 `\|`/`&` 分隔(各 func 约定不同,见行号)。**默认测试凭证**:mysql/ssh 缺省 root/click1(框架床默认,func_202/206)。

---

## 2. server 触发端深读（`env.py` + `ssh_server.py`；E=test_env）

**契约**(env.py:66-98 `server213/231/232`,routera/b、clientc/d/e、console 同):
- 签名 `serverNNN(cmd, prompt="serverNNN#", timeout=10)`;懒初始化 `ssh_server(config,logger,"serverNNN")`→`.cmd(cmd,prompt,timeout)`。
- **"config env" 含义**(ssh_server.__init__:39-44):SSH 连 `config.conf.get('env', name)` 解析出的**主机 IP**(env 段是"逻辑名→IP"表),user=`test`/pass=`click1`,invoke_shell→`sudo su`(pass click1)切 root。**主机名是逻辑名,IP 来自 config `env` 段**(换床改 config 不改用例)。
- **后端跑什么命令**:G 列即 shell 命令,`cmd`(:93-106) send+`read_until(prompt)`。SLB 语境典型:`systemctl start/stop <svc>`/`ifconfig` 起停真实服务器造 real server UP/DOWN,供 SLB 健检探活。
- **IP 恢复副作用**(LLM-Eng B 线标,ssh_server:95-100):`cmd` 对 `ip route/-6 route add`、`addr add` **自动记入 route_list/ip_list**,`close()`(:120-124)时 `delete_route/delete_ip` 逆放(add→delete)——**框架 IP 恢复契约**(见记忆 [[framework-ip-restore-contract]]):用例自己 `addr add` 的地址会在 case 尾被框架自动删,**用例不要自行 del**(双删崩卷)。
- **read_until 超时**(:74-91):`timeout`(默认 10)内正则不中→返回**部分**输出,不抛错(慢后端→断言搜残缺窗口假 fail)。

---

## 3. SLB 专用模板方法（part 3 结论:无）

`slb_comm.py` **空文件(0 行)**——无 SLB 专用方法。SLB 配置=通用 `cmd_config`(`slb real/virtual service`、`slb group`、`ssl host {real|virtual}` 等,语法从手册 cli_10.5_Chapter8 + footprint 现查);SLB 行为验证=execute 动作(§1 标 ✅ 者)+ server 触发端(§2)+ client curl。**含义**:SLB emit **不需要专用方法支持**——纯配置用 cmd_config(编译器已实弹)、流量/健检用 execute+server(编译器 0 产出=真空白面,同 #47 R1)。

---

## 4. execute 模糊匹配碰撞离线仿真（part 4 / #53 拆出）

**方法**:真跑 `dic_operation.get_similar_function` 同款 `SequenceMatcher(None, norm(a), norm(b)).ratio()`(norm=去空白+小写,同 :28)对 40 动作名两两算,阈值 `≥0.8`(同 :42)。**前提**:模糊匹配仅在**精确匹配 `get_same` 先失败**时触发(execute:64→72)——即动作名**写不精确**(错字/改述)才走模糊,精确名零风险。

**碰撞对(registry 内,9 对)**:

| ratio | 动作 A | 动作 B | func 对 | 危险级 |
|---|---|---|---|---|
| **0.944** | 检查STUB区域传输AXFR同步成功 | 检查STUB区域传输IXFR同步成功 | 216⇄217 | 🔴 AXFR/IXFR 反转 |
| **0.929** | 检查区域传输AXFR同步成功 | 检查区域传输IXFR同步成功 | 214⇄215 | 🔴 AXFR/IXFR 反转 |
| **0.897** | 批量绑定30个常见的错误码 | 批量检查绑定的30个常见的错误码 | 7⇄8 | 🔴 **绑定/检查反转**(配置 vs 断言) |
| 0.875 | 检查区域传输AXFR同步成功 | 检查STUB区域传输AXFR同步成功 | 214⇄216 | 🟡 域/STUB 混 |
| 0.875 | 检查区域传输IXFR同步成功 | 检查STUB区域传输IXFR同步成功 | 215⇄217 | 🟡 |
| **0.833** | 创建Mysql数据库用户 | 创建Mysql数据库数据 | c204⇄c205 | 🔴 **用户/数据反转** |
| **0.812** | 指定Service健康检查DOWN | 指定Service健康检查UP | 212⇄213 | 🔴 **UP/DOWN 语义反转**(健检对立) |
| 0.812 | 检查区域传输AXFR同步成功 | 检查STUB区域传输IXFR同步成功 | 214⇄217 | 🟡 |
| 0.812 | 检查区域传输IXFR同步成功 | 检查STUB区域传输AXFR同步成功 | 215⇄216 | 🟡 |

**misdispatch 风险量化**:9 对 ≥0.8(apv 8 + client 1)。**5 对是语义反转/对立**(🔴):UP⇄DOWN 健检(212/213)、绑定⇄检查(7/8)、用户⇄数据(c204/c205)、AXFR⇄IXFR(214/215、216/217)——一旦动作名写不精确落在两者间,模糊取最高 ratio 那个,**可能静默派到语义相反的 func**(健检等 UP 变等 DOWN)。**闭合机制**:fuzzy 取**单个最高 ratio**(:38-52),非全部≥0.8——真实误派需输入到 B 比到 A 更近;但 UP/DOWN 这种只差一字的对,一个改述极易翻。**对编译的含义**:worker 生成 execute 动作名**必须逐字对齐注册表**(apv_action:11-44/client_action mapping),**不能改述**——这是比 cmd 命令更硬的约束(cmd 错→设备 `^` 拒可见;动作名模糊错→静默派错 func 不可见)。建议 worker 引导:execute 动作名从注册表**复制**,禁改述;或 emit 门加"execute 动作名 ∈ 注册表精确集"校验(needs Design 裁是否值得)。

---

## 5. G-area 标签（Theory SLB 特性模型 §7 已定案：G1-G7）

Theory G1 virtual service / G2 real+group / G3 scheduling / G4 health / G5 persistence / G6 policy-qos / G7 stats-observability。SLB 相关 execute 动作按 G 面标(供 Theory 四方矩阵按 id 填):

| execute 动作 | func | G-area |
|---|---|---|
| 健康检查up / 类型健检UP·DOWN / Service健检UP·DOWN | func_1/209/210/212/213 | **G4** health |
| 访问(curl 流量) | client func_1:17 | 跨切(**G3** 调度验证 + **G4** 健检触发流量) |
| rs 响应内容 / rs 添加header | func_5/6 | **G2** real service(RS 建服) |
| 检查备机会话保持表(`show slb per se`) | func_219 | **G5** persistence |
| 获取SSLsessionid | client func_300 | **G5** persistence(会话复用) |
| 白名单规则/检查/permit | func_2/3/4 | **G6** policy |
| errpage 绑定/检查 | func_7/8 | **G6** policy |
| statistics acl / 发包间隔 / 日志告警间隔 | func_4/208/220 | **G7** stats |
| HA link/domain/init | func_101/102/218 | 跨切(HA,常伴 SLB 非独立 G) |

**G1 virtual service / G2 group 绑定 / G3 调度算法本体 = 纯 `cmd_config` 配置**(无对应 execute 动作)——见 §5.1。server 触发端(§2)=跨切支撑(后端起停供 G4 健检)。SSL cards §8 已定 F1-F6;SLB 侧无 config F-area 专用方法(§5.1)。

### 5.1 Theory ② 预测核验（"SLB=通用 cmds_config,无专用方法族"）——CONFIRMED

**Theory ② 预测**:SLB = generic cmds_config,NO dedicated method family(不同于 SSL cert 族)。
**从 dispatch surface 读证 → 确认(fill from read,非以预测为锚)**:
- `slb_comm.py` **空文件(0 行)**(§3 实读)——无 SLB 专用方法族,与 `ssl_comm.py` 的 25 cert + 12 tftp 方法形成鲜明对照。
- SLB 配置(G1 vs / G2 rs+group / G3 调度算法)**全走通用 `cmd_config`**(`slb virtual/real service`、`slb group`、algorithm 行等,语法从手册 Chapter8 + footprint 现查),编译器**已实弹**(105 卷主力就是 cmd_config)。
- SLB 唯一的"方法"是 execute 动作(§1)+ server 触发端(§2)+ client curl——均非"专用配置方法族"。

**对 launch sequencing 的含义(Theory 点的,坐实)**:**SLB enablement 跳过 cert-emit 瓶颈**——SSL 有 25 cert 方法需教 emit/blocks 表达(#23 P2-3、#50-A 瓶颈),SLB **无任何专用方法需教**,纯配置直接 cmd_config。故 **SLB 方法-族轴是非问题**,SLB enablement 比 SSL **少一个前置瓶颈**:SLB 只需 ①流量/健检的 execute 引导(+§4 动作名精确护栏)②床就绪,**无 cert-emit 单点**。→ **建议 launch 排序:SLB 纯配置层(G1/G2/G3 存在性)可比 SSL 更早试点**(少 cert-emit 前置);SLB 本质行为层(G3 调度分发/G4 健检)与 SSL 加密/健检同受 execute+server 空白面门控。

---

## 6. needs-device-probe + SLB enablement 门槛

**needs-device-probe**(源码读不出):
1. server213/231/232 主机在当前 config `env` 段是否配置 + 后端服务(nginx/httpd)可起停——SLB 健检前置(§2)。
2. 后端 HTTP API `172.16.35.231:12345/add_page` 是否在床上运行(func_5/6 依赖)。
3. execute 模糊匹配的**真实误派率**:构造 SLB 动作改述样本喂 dic_operation 实测(§4 是名-名碰撞,未测真实输入落点)。
4. `show slb per se` / SLB 健检输出的实际窗口格式(func_219 归一化假设待验)。
5. client curl 到 VIP 的连通性 + SLB 调度可观测面(#49 已定 R1,SLB 触发后观测)。

**SLB enablement 门槛**(呼应 #47/#48/#50-A):
- SLB 纯配置(slb real/virtual service + show 断言)=cmd_config,**编译器已实弹**,门不挡(structural_gate 对 APV 设备 F 不设白名单,#48)。
- SLB 流量/健检=execute(curl/健检等待)+server(后端起停)——**编译器 0 产出的真空白面**;门不挡、但需 ①worker 引导走 steps + execute 动作名精确(§4 碰撞风险)②床就绪(§6 needs-probe 1/2)③无专用方法故全靠动作注册表现查。
- **非改引擎代码**(#48 结论不变),是 prompt+data+床三面 + **一个新风险(§4 动作名模糊误派)worker 引导须显式护栏**。
