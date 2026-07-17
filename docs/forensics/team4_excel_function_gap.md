# Excel 函数/方法四面对比审计（任务 #23）

> 只读分析，零改动。机械事实面（A/C/C-md/D + 矩阵）= Py-Eng；语义定性面（B-vs-A / C-vs-B / D-vs-C / 分级短板）= LLM-Eng 追加于文末。
> 数据源与解析口径：框架格式卷用引擎权威解析器 `precedent_tools._load_case_rows` 同口径（第 29 行起、A 列 999999 哨兵停、抽 E/F/G/H/I），read_only 加速；中间统计落 `docs/forensics/_excel_stats.json` + `_excel_matrix.json`（临时件，报告定稿后可清）。
> 生成：2026-07-17 · Py-Eng。

## 0. 数据源辨明（关键前置——纠正「orgin=C 面 F 列源」的直觉）

四面的**真实数据源**经实测确定，与任务初始描述有一处必须纠正：

| 面 | 数据源 | 卷数 | 性质 |
|---|---|---|---|
| **A 框架** | `knowledge/framework/mirror/lib/`（test_xlsx.py 分发 + apv/*.py 设备类 + check_point.py + env.py + ssh_server.py） | 源码 | F 列方法/算子的**定义闭集** |
| **C-人工框架卷** | `mirror/smoke_test/sdns/**/*.xlsx` | **380** | **人工编写的框架格式金标准卷**（真正的「人工 F 列用法」源） |
| **C-需求列表** | `knowledge/data/orgin/*.xlsx` | 37 | **需求列表格式**（Item/Test Types/Description/Expected/Priority）——**不含 F 列方法**，是 worker 理解「要测什么」的需求源，经 C-md 保真检查，**不参与 F/算子矩阵** |
| **D-引擎写回** | `mirror/verified_<autoid>.xlsx` | 123 | 引擎 `compile_writeback` 落盘的已验证先例（半自动，归我们侧） |
| **D-批1/2产出** | `workspace/outputs/<autoid>/case.xlsx`（排 _pytest/__sub） | 49 | 本轮 dongkl 等 SDNS 用例产物（**批 2 滚动中，读 07-17 快照**） |
| **D-历史备份** | `runtime/backups/pre_team4_20260717/outputs/**/case.xlsx`（排 pytest 前缀） | 112 | dongkl/yzg/zhaiyq 历史交付卷 |

**纠正**：orgin 的 xlsx 是**需求列表**（人类测试点，列头 Item/Test Types/…），实测零 F 列方法——真正的「人工写的框架格式用例」在 `mirror/smoke_test/`（380 卷）。矩阵的 C 面用后者；orgin 归 C-md 保真节。

**诚实边界（矩阵解读必读）**：D-批1/2（49 卷）是 **SDNS DNS 健康检查子集**（dig+routera 为主）；C-人工（380 卷）跨 **SDNS 全功能**（含 SSL 连接/证书/多协议 HC/多触发端）。故下方矩阵中 execute/import/server* 的「D 零使用」**部分**可归用例类型差异，**不能全判能力缺口**——但 C-人工内含大量**同型** `sdns_health_check_dns` 卷也用了 execute/多触发端，故「能力缺口 vs 用例差异」的分离需**同类子集对比**（语义活，交 LLM-Eng）。

---

## A 面：框架能力机械闭集（源码，带行号）

### A.1 check_point 算子全集（`lib/check_point.py`）

| 算子 | 行号 | 语义 | 判定 |
|---|---|---|---|
| `found` | :22 | `re.compile(expect, re.DOTALL).search(result)` 命中→success | 正则匹配（DOTALL 无 MULTILINE） |
| `not_found` | :55 | 同 found 但命中→fail、未命中→success | 正则**反向** |
| `abs_found` | :38 | `re.compile(re.escape(expect)).search(result)` 命中→success | **字面**匹配（escape，无 DOTALL） |
| `found_times` | :68 | `len(re.findall(expect,result))==times`→success | 计数匹配，**须 3 参**（times） |
| `close` | :83 | 收口判定：`fail>0`→FAIL、`success==0`→FAIL、否则 PASS；`debug>1` 时 core-dump 检测（:97-115） | 零检查点恒 FAIL |
| `xlsx_begin` | :139 | 每 case 前重置 pass/fail 计数 | — |

**found_times 幽灵能力确认**：`check_point.py:68` 定义 `found_times(self, expect, result, times)` 需 3 参，但框架分发 `test_xlsx.py:330-336` 对 check_point 只传 2 参（`func(except_value, result)`）→ found_times 上机 `times=<缺>` 必 TypeError → 该能力**框架定义在、分发通道不可达**。EXCEL_FUNCTIONS.md 标「禁用」与 emit 门拒 found_times 均正确（LLM-Eng B-vs-A 可引此为「幽灵能力正确标注」样本）。

### A.2 F 列方法闭集（按对象类，`getattr(对象, F列值)` 分发，test_xlsx.py:291/271）

| 对象类（E 列值） | 源码 | F 列可用方法（闭集） |
|---|---|---|
| **check_point** | check_point.py | found / not_found / abs_found / found_times（见 A.1） |
| **APV_0/APV_1/Seg*_tmp**（设备） | apv/apv_ssh.py + apv_ccypher.py + ssl_comm.py | cmd_config(:125) / cmds_config(:167) / cmd(:155) / cmd_enable(:111) / array_config(:173) / execute / clear(:210) / **SSL 证书族 40+**：importKey/importCert/importRootCA/importInterCA/importCRLCA/csrVhost/csrRhost/eccCsrVhost/importMutiCert/importSni*(Cert/Key/Rootca/Interca/Crlca)/activeCert/sm2ImportKey/sm2ImportCert + 各 `_tftp` 变体 |
| **test_env**（触发端入口，`Env` 类） | env.py | routera(:50) / routerb / server213(:66) / server231(:74) / server232(:82) / console(:91) / clientc …（每方法签名 `(cmd, prompt, timeout)`，直接在该主机发命令） |
| **主机对象**（routera/server232 等，locals 实例） | ssh_server.py | execute(:151)（发一个动作 step） |
| **time** | 内置 | sleep |

**execute 两执行器注册表**（LLM-Eng 问的对接点）：`ssh_server.py:151 def execute(self, step)` 与 `dic_operation.py:57 def execute(self, step)`——execute 方法接受 step（动作名），合法动作词表在 `knowledge/data/auto_env/execute_actions.json`。这是**发流量/客户端动作**通道（区别于 cmd_config 发设备命令）。

### A.3 参数解析机制（`test_xlsx.py::get_parameter`, :49-85）

- 引号外逗号切段；含 `=`（key 无空格）→ **kwargs**（value 纯数字转 int，如 `timeout=5`/`prompt=YES`）；否则 → positional。
- 含 `\n` 的整串作**单参数**（多行命令原样传，:53-55）。
- `cmd_config` 专门拍平换行（:307-308 `replace('\n','')`）——单行执行。

### A.4 H/I 列双语义（test_xlsx.py 分发, :294-336）

| 列 | 索引 | 机制 | 源码 |
|---|---|---|---|
| **H**（第 8 列） | row[7] | check_point 的**期望值变量引用**（`except_value=locals()[H]`，:296-299）/ 普通步的**结果保存寄存器**（`locals()[H]=func(...)`，:333-335） | :294-299/:333-335 |
| **I**（第 9 列） | row[8] | 结果**格式化注入**（`parameters[0]=parameters[0].format(obj_value)`，obj 从 locals/globals 取，支持 `对象.属性`，:316-329） | :313-329 |

---

## C 面：人工框架卷用法全集+频次（smoke_test 380 卷 / 51007 行）

| 维度 | 计数 | 说明 |
|---|---|---|
| **算子** found / not_found / abs_found / found_times | 15842 / 1641 / **12** / **0** | found 主力（90%）；abs_found 罕用（0.07%）；found_times **零** |
| **设备方法** cmd_config / cmds_config / cmd / execute | 8550 / 7249 / 249 / **2208** | 命令族主力；**execute 2208（大量用）** |
| **SSL 证书族** import*/csr*/Cert/Key | **354** | 人工用证书导入 |
| **触发端** routera / server231 / server232 / server213 / console / routerb / clientc | 6873 / 4179 / 120 / 23 / 301 / 117 / 26 | **7 种触发端全用** |
| **H 列**（寄存器/期望引用） | 605 行 | 捕获+比较关系断言 |
| **I 列**（格式化注入/found_times 次数） | **1426 行** | 大量用 |
| **特殊写法** 多行命令 / format 占位 / 掩码形态 | 6767 / 1720 / 1105 行 | — |

## C-md 保真抽样（orgin 需求列表 xlsx → markdown/qa/*.md）

转换器 `main/xlsx_to_markdown.py` 机械核验：
- **换行正确转义**（:29 `\n`→`<br>`）+ **管道符转义**（`|`→`\|`）——GFM 表格**不撕裂**；实测 Cache_HTTP2 md 293 处换行单元格全部 `<br>` 化，保真 ✓。
- **全 sheet 覆盖**：抽样 3 份，多 sheet（Cache 2 sheet / HTTP2 1 sheet）名全部在 md 出现 ✓。
- **轻度信号**（非破坏）：① 合并单元格非左上角转空（`|  |  |`）——GFM 固有限制，信息稀释、人可从上下文推断；② `APV_network_ClickTCP_TCPOption_unit_test`（报告类 xlsx，87 合并单元格）的 `Unit Test Report` sheet 未在 md 出现（疑转换退化，**边缘案例**：报告类非 test list）。
- **影响面定位**：qa md 是 worker 理解**需求意图**的辅助知识（检索用），**非 F 列方法学习源**（后者来自 precedent/footprint）——保真问题影响面**低**；严重性交 LLM-Eng。

---

## D 面：编译产出用法分布（写回 123 / 批1-2 49 / 历史 112 卷）

| 维度 | D-写回 | D-批1/2 | D-历史 | D 合计 |
|---|---|---|---|---|
| found / not_found / abs_found | 202/99/92 | 222/39/32 | 319/177/159 | 743/315/**283** |
| found_times | 0 | 0 | 0 | **0** |
| cmd_config / cmds_config | 195/315 | 142/190 | 337/441 | 674/946 |
| **execute** | 0 | 0 | 0 | **0** |
| **SSL 证书族** | 0 | 0 | 0 | **0** |
| routera / server* / console / clientc / routerb | 362/0/0/0/25 | 84/0/0/2/3 | 602/0/0/0/52 | 1048 / **0** / **0** / 2 / 80 |
| **H 列** | 228 | 2 | 438 | 668 |
| **I 列** | 0 | 0 | 0 | **0** |

---

## 矩阵：A × C × D 四列交叉（不一致行=问题候选）

「✓」=有/用；数字=频次；**粗体**=四列不一致的问题候选行。

| 方法/算子 | A 框架有? | C 人工用(380卷) | D 我们用(合计) | 判定（机械，语义交 LLM-Eng） |
|---|---|---|---|---|
| check_point.found | ✓ :22 | 15842 | 743 | 一致（主力算子） |
| check_point.not_found | ✓ :55 | 1641 | 315 | 一致 |
| **check_point.abs_found** | ✓ :38 | **12（0.07%）** | **283（≈27%）** | ⚠ **我们 abs_found 占比远高于人工**——人工几乎全 found（正则），我们大量 abs_found（字面）。候选成因：emit 门 found→abs_found 自动转（H 引用时转字面）/worker 偏好。语义定性 |
| **check_point.found_times** | ✓ :68（幽灵） | **0** | **0** | 框架定义在但分发不可达（只传 2 参）；人工+我们都不用；emit 拒——**一致的正确规避**，非短板 |
| APV.cmd_config / cmds_config | ✓ :125/:167 | 8550/7249 | 674/946 | 一致（命令族主力） |
| APV.cmd（单命令） | ✓ :155 | 249 | ≈0 | 人工用、我们几乎不用（cmds_config 覆盖，低危） |
| **APV/routera.execute** | ✓ ssh_server:151 | **2208** | **0** | ⚠ **我们完全不用 execute**（发流量/客户端动作通道）；含用例类型混杂（DNS 类少发流量），但同型 sdns HC 人工卷大量用——同类子集对比定性 |
| **APV.SSL 证书族**（40+） | ✓ | **354** | **0** | ⚠ **我们完全不用证书导入方法**；本批无 SSL 用例（用例类型），能力覆盖度未经检验——语义定性是否短板 |
| test_env.routera | ✓ env:50 | 6873 | 1048 | 一致（主力触发端） |
| test_env.routerb | ✓ | 117 | 80 | 一致 |
| **test_env.server231/232/213** | ✓ env:74/82/66 | **4322** | **0** | ⚠ **我们不用 server 触发端**（后端服务器侧发起）；含用例混杂，同类对比定性 |
| **test_env.console** | ✓ env:91 | **301** | **0** | ⚠ **我们不用 console 触发端** |
| test_env.clientc | ✓ | 26 | 2 | 人工用、我们几乎不用 |
| **H 列（寄存器/期望引用）** | ✓ :294-335 | 605 行 | 668 行 | 总量一致，但**批1/2 仅 2 行/49 卷**（历史+写回撑起 668）——本批几乎不捕获，用例类型 or 缺口？语义定性 |
| **I 列（格式化/found_times 次数）** | ✓ :313-329 | **1426 行** | **0** | ⚠ **我们完全不用 I 列机制**（结果格式化注入/found_times 次数引用）——全域零使用，最强能力缺口候选 |

**六个机械不一致候选**（P 分级交 LLM-Eng 语义定性）：
1. **I 列全域零使用**（我们 0 vs 人工 1426 行）——机制完全未触及，缺口嫌疑最强；
2. **execute 全域零使用**（0 vs 2208）——发流量/客户端动作通道未用；
3. **SSL 证书族全域零使用**（0 vs 354）——本批无 SSL 用例，覆盖度未检验；
4. **server*/console 触发端零使用**（0 vs 4623）——多触发端能力未用；
5. **abs_found 占比倒挂**（我们 27% vs 人工 0.07%）——字面 vs 正则偏好差异；
6. **批1/2 H 列近零**（2 行/49 卷）——本批几乎不做捕获比较断言。

**混杂因子声明**：候选 2/3/4/6 均含「D-批1/2 是 DNS 健康检查子集」的用例类型混杂——见下节同型子集对比已机械分离。

## 同型子集对比（分离能力缺口 vs 用例差异；卷级使用率）

用**卷级使用率**（用了该能力的卷÷总卷，剥离 380 vs 49 绝对数不可比问题）+ **DNS 解析同型子集**（卷面 G 含 `dig` ∧ 非 SSL，机械筛）对齐用例类型：

| 能力 | C-人工·DNS子集(134卷) | D-批1/2·DNS子集(22卷) | D-历史·DNS子集(93卷) | 机械分离结论 |
|---|---|---|---|---|
| **execute** | **21%** | **0%** | **0%** | ⚠ **真能力缺口**——同型 DNS 下人工 21% 用（发查询/流量），我们全 0；用例混杂已剥离 |
| **I 列** | **9%** | **0%** | **0%** | ⚠ **真能力缺口**——同型下人工 9% 用格式化注入，我们全 0（全域零使用的同型确认） |
| **server 触发端** | **24%** | **0%** | **0%** | ⚠ **真能力缺口**——同型 DNS 下人工 24% 用后端服务器侧验证，我们全 0 |
| import（SSL 证书） | 4% | 0% | 0% | **用例差异非缺口**——同型 DNS 下人工也仅 4%（DNS 类本就少证书） |
| console 触发端 | 0% | 0% | 0% | **用例差异非缺口**——DNS 子集下人工也 0%（console 属非 DNS 的 CLI 直连类用例） |
| abs_found | 2% | 9% | **46%** | **偏好差异**——我们（尤其历史）DNS 类 abs_found 用得多于人工（字面 vs 正则偏好，跨用例全域） |
| H 列 | 7% | 4% | **47%** | **本批特性非系统缺口**——历史 DNS 47% 用 H，批1/2 本批仅 4%（本批用例少捕获比较，非能力缺失） |

**精化后的候选分级（机械依据，P 级+根因交 LLM-Eng）**：
- **真能力缺口（同型子集确认，缺口嫌疑最强）**：`execute`（21%→0）/ `I 列`（9%→0）/ `server 触发端`（24%→0）——DNS 同型下人工明确使用而我们完全不用；
- **用例差异（非缺口）**：`import` SSL 证书族（DNS 类人工也少用）/ `console`（DNS 类人工也不用）；
- **偏好/本批特性**：`abs_found` 倒挂（跨用例全域偏好，可能 emit 门 found→abs_found 转换或 worker 倾向）/ `H 列近零`（见下节目录分型修正）。

### 目录精细分型交叉验证（leader 派活；比 dig 内容筛更同型，修正 H 列判断）

批1/2 内容特征实测：**pool=54 主导**（cname/ipo/rpz/view/health 均低，dig=12）——批1/2 是 **SDNS pool 解析调度类**，最同型的 C 子集是**解析调度类**（view/rpz_record/rcodeconvert/epolicy/static_domain/stub_zone/edns），**不是 health_check 类**。按 smoke_test 目录名精细分型的卷级使用率：

| 能力 | C-解析调度类(69卷) | C-health_check(202卷) | D-批1/2(49卷) | 精化判定 |
|---|---|---|---|---|
| **execute** | **17%** | 84% | 0% | **真缺口**（最同型解析类人工也 17%，我们 0） |
| **server 触发端** | **21%** | 75% | 0% | **真缺口**（同型 21%→0） |
| **I 列** | **5%** | 35% | 0% | **真缺口**（同型 5%→0，虽小但同型人工用、我们 0） |
| import(SSL) | 0% | 11% | 0% | 用例差异（解析类人工也 0%） |
| **H 列** | **0%** | 23% | 2% | ⚠ **修正为用例差异非缺口**——与批1/2 最同型的解析调度类**人工也 0% 用 H**（H 捕获比较是 health_check 类特性）；先前「dig 内容筛人工 7%」把 health_check 的 dig 卷混入致偏高 |
| abs_found | 0% | 0% | 12% | **偏好倒挂更尖锐**——同型解析类人工 **0%** 用 abs_found，我们 12% 净多出（emit found→abs_found 转换根因嫌疑坐实价值更高） |

**两个筛法（dig 内容筛 / 目录分型）结论主体一致**（execute/server/I 真缺口、import 用例差异、abs_found 偏好倒挂），**唯一修正 = H 列**：目录分型更同型，解析调度类人工 H 使用率 0%，故 **H 列判为用例类型差异（解析类不做捕获比较断言），非能力缺口**。

**收敛后的最终三分（喂 #24，无需等批 3/4）**：
- **真能力缺口 ×3**：`execute`（发流量/客户端动作）、`server 触发端`（后端服务器侧验证）、`I 列`（结果格式化注入）——同型子集双筛法确认，与 044538 负面用例同型（文档漏载致 worker 不会用某能力）；
- **用例差异 ×3（非缺口）**：`import` SSL 证书族、`console` 触发端、`H 列`——最同型人工子集也不用；
- **偏好倒挂 ×1**：`abs_found`（同型人工 0% vs 我们 12%）——根因待 LLM-Eng 坐实 emit 转换逻辑。

---

<!-- ============================================================ -->
<!-- 以下由 LLM-Eng 追加：B 面（EXCEL_FUNCTIONS.md 等参考文档）语义面 -->
<!-- B-vs-A 文档漂移/漏载表 · C-vs-B 人工用法文档短板 · D-vs-C 分布解读 · P0-P2 分级短板清单 -->
<!-- ============================================================ -->

## B 面语义对照（LLM-Eng · 2026-07-17）

> 基准：`knowledge/data/compile_ref/EXCEL_FUNCTIONS.md`（266 行，worker 编写时读的唯一参考文档）逐条对照 Py-Eng 的 A 面源码闭集；C-vs-B / D-vs-C 用 Py-Eng 的 C-人工(380)/D(184) 机械统计 + 我抽的**同型子集实测**分离「能力缺口 vs 用例差异」。

### B-vs-A：文档 vs 框架源码（漂移/漏载/幽灵）

| 文档条目 | 源码事实 | 判定 |
|---|---|---|
| found/not_found（DOTALL 无 MULTILINE、`^`/`$` 只锚串首尾、窗口=回显+数据+提示符） | check_point.py:22/55 一致 | ✅ 准确（含恒真恒假机理，B 面讲得比源码注释还清楚） |
| abs_found「和 found 一样找，但当纯字面」 | :38 `re.compile(re.escape(expect))`——**无 DOTALL** | ⚠ 微漂移：escape 后无正则元字符，DOTALL(仅影响 `.` 跨行)对纯字面无行为差；文档"和 found 一样"在跨行匹配上不精确，**实际零影响**，不修 |
| found_times「禁用，check_point 只传 2 参，第 3 参必 TypeError」 | :68 方法存在需 3 参；test_xlsx.py:293-304 分发只传 2 参 | ✅ **幽灵能力正确标注**——方法定义在、分发通道不可达，文档标禁用 + emit 拒 + 修正旧"次数写 I 格"谬误，三处都对 |
| E 闭集（APV_0/1/2、Seg*_tmp、test_env、routera、server213/231/232、http_server_231） | test_xlsx.py:176-189 devices 12 键一致 | ✅ 准确（含"存在但当前用不到"的诚实标注） |
| test_env F 方法闭集（clientc/d/e、routera/b、server213/231/232、console） | env.py 实测恰 9 方法 | ✅ 准确 |
| H/I 双语义（check_point 步 H=期望变量/I=被比较变量；普通步 H=存返回值/I=format 注入） | test_xlsx.py:294-336 一致 | ✅ 准确（这是全文最易错的机制，文档拿捏住了） |
| cmd_config 换行拍平 | :307-308 `replace('\n','')` 一致 | ✅ 准确 |
| execute 两注册表「是数据，不复制进文档，编写前现查源码」 | apv_action.py/client_action.py（func_N 命名 + 同义词表） | ✅ 按引用指路，**非漏载**（符合"参考文档只写机制、数据按引用"红线） |
| — | check_point.py:97-115 `close()` 的 **core-dump 检测**（debug>1 时 apv0/apv1 新 core 文件→fail+1） | ❌ **B 面漏载**：worker 不知"用例可因设备 core dump 判 fail"——不影响编写（框架自动行为），但**影响归因**（attributor 可能把 core-dump fail 误归为断言问题）。P2，建议 attributor 知识或 EXCEL_FUNCTIONS.md 补一句 |
| — | cmd_config（apv_ssh.py:125-152）**本身不判命令成败**，被拒回显原样返回 | ❌ **B 面未言明**：直接牵出下面的负面测试盲区 |

**B-vs-A 小结**：EXCEL_FUNCTIONS.md 对**已覆盖的机制**准确度极高（机理级正确、幽灵能力正确标注、按引用指路合规），无一处误导性漂移。问题**不在文档写错，而在文档没写**——见下负面测试盲区与 C-vs-B。

### 负面测试盲区专项（B-vs-A 漏载的活样本 + 同类扩展）

**活样本**（run_log:110，autoid …044538，连续两轮 broken）：脑图意图「ga 不能配置相同优先级」（负面测试），worker 照字面用 `cmd_config` 直发被拒命令 + `found "already used this priority"`。

- **A 面事实（证据边界分级）**：① **firsthand 坐实**——cmd_config **本身不判成败**（apv_ssh.py:125-152 我读过,返回错误回显),故负面测试在**框架层可表达**（found 错误消息能 pass）。② **推断（未核 digest/reconcile 代码）**——"判 broken 的是引擎 digest 层"系据 run_log 现象 + 架构模型推断,**我未读赋 broken verdict 的那段代码**;结论方向大概率成立(框架层已排除,broken 只能来自上层判定),但归属层待 grep 坐实(处置见 leader,#24/#15)。
- **B 面事实**：EXCEL_FUNCTIONS.md 通篇 266 行**无一处**负面测试范式——CONFIG/cmd_config 描述全预设"命令应成功"；worker 无从知道"意图是验证设备拒绝"该怎么写。
- **框架有无现成"允许失败"方法**：无。execute 动作是 func_N 具体业务封装（func_7/8=HTTP errpage），非通用"期望拒绝"原语。
- **正解**（两条，与 run_log 修法方向一致）：①改正向观测——配置后 `show` 验证约束真生效（如"只有一个成员持有该优先级"），绕开 digest broken 判定；②若必须直验拒绝——需引擎 digest 区分「意图内拒绝(负面测试合法)vs 意图外失败(编译缺陷)」，这是更深的引擎能力缺口。

**同类扩展**（查还有没有同型——有，整整一类）：负面/异常路径测试家族在 B 面全缺范式：期望配置被拒（本例）、期望请求返回错误码、期望容量上限拒绝新增、期望非法输入设备报错、期望故障后降级。这类的共同特征是**主动制造"设备说不"的场景**，与文档的"配置成功→观测正常→断言命中"正向骨架正交。

### C-vs-B：人工用而文档/我们体系缺的方法论（同型子集实测坐实）

Py-Eng 的六个机械候选中，2/3/4/6 带「D-批1/2 是 DNS 子集」的用例类型混杂声明。**两条独立口径的同型对比互为印证**——Py-Eng 上节（137 行）用**卷级使用率**（DNS 解析子集 134 卷）、我用**步频次**（`sdns_health_check_dns` 目录 26 卷 2099 步）；不同子集、不同度量，execute/I/server 的「同型人工用、我们全 0」结论完全一致（双盲交叉验证）。我的步频视角：

| 方法 | 同型人工卷(26) | D-批1/2(49) | 混杂消除后判定 |
|---|---|---|---|
| **execute** | **223**（动作："指定类型健康检查UP/DOWN"=故障注入、"提取发包间隔"=动态提取） | **0** | ❌ **坐实能力缺口**——同型也大量用，非用例差异 |
| **server231**（后端服务器侧操作） | **341** | **0** | ❌ **坐实能力缺口**——健康检查测试要在后端起停服务触发 DOWN/UP |
| **I 列 format 注入** | **212** | **0** | ❌ **坐实能力缺口**——设备属性/抽取值注入命令 |
| **H 存动态值** | 41 | 2 | ❌ 同型也用，我们近零 |

**范式样本对照**（`sdns_health_check_dns/dns_link_dst_addr.xlsx`，人工怎么测健康检查）：
```
APV_0  cmds_config  sdns monitor dns "dns_v4" ...        ← 配探测器
APV_0  cmd_config   debug trace live tcp {} "-c 4 ... port 53"  I=APV_0.port1  ← I 注入接口名，抓设备主动发的探测报文
check  found        172.16.35.70.\d+ > 172.16.35.213.53  ← 断言"设备真的从.70向后端.213:53发了DNS探测"
```
人工验证的是**机制真实行为**（健康检查探测报文真的按配置发出、后端 DOWN 真的被摘除）；用 `debug trace live` 抓设备主动流量 + I 列注入接口属性 + execute 注入健康状态。

**我们批次的降维**：同样标称"DNS 健康检查"，我们只会「配置 + dig + 看成员在不在」（静态 member 存在性断言）。**测的不是同一层行为**——人工测"健康检查机制真的工作"，我们测"健康检查配置真的配上了"。这是测试深度的系统性降维。

**该补文档 vs 该忽略**（逐候选）：
- execute/server 端/I 列/debug-trace 抓包 → **该补，且是能力层不止文档层**（见 D-vs-C 根因）。
- SSL 证书族（Py-Eng 候选3，0 vs 354）→ 本批无 SSL 用例，**用例差异**，覆盖度待专门 SSL 批检验，非当前短板但列覆盖盲区。
- clientc/cmd 单命令（低频）→ cmds_config 已覆盖，**可忽略**。
- found_times → 幽灵能力，人工+我们都 0、emit 拒，**一致的正确规避**，非短板。

### D-vs-C：分布差异解读

| 现象 | 数据 | 解读 |
|---|---|---|
| **过度集中于"配置+dig+静态断言"** | D 的 found/cmd_config/routera 占绝对主力，execute/server/I/debug-trace **全 0** | 我们只会一招：配好→dig→member 匹配。方法论单一 |
| **abs_found 倒挂** | 人工 0.07% vs 我们 27% | **非跑偏，是工具机制**（源码坐实见 P2-2）：主来源 member 组合子展开成 abs_found（precedent_tools.py:388）；H 引用自动转（emit_xlsx_tool.py:158）本批 H 近零贡献小。字面匹配对静态 IP/域名比手写转义正则**更不易错**，合理机制不列短板 |
| **I 列零使用** | 历史/写回/批 全 0 | 真能力缺口（同型历史也 0）——从不做动态值传递（H 存抽取值→I 注入下一命令） |
| **H 列近零仅限本批** | 批1/2 H=2，但历史卷 47% 用 H（Py-Eng 137 节） | **本批用例特性，非系统缺口**——我们历史会做捕获比较断言，只是本批 DNS 静态验证类少用；勿与 I 列缺口混判 |

**我们用而人工不用的**：无跑偏项。abs_found 偏好是合理的安全选择（见上）。

### 分级短板清单（P0 能力缺口 / P1 文档或组合子层 / P2 观察）

**P0-1｜健康检查动态行为/故障注入整类用例编不出**（能力缺口，同型对比坐实）
- 现象：worker 表达不了「后端 DOWN→验摘除→UP→验恢复」「抓设备主动探测报文」「注入动态值」。
- 证据：同型 sdns_health_check_dns 人工 execute 223/server231 341/I 212，D-批1/2 全 0；范式样本 dns_link_dst_addr.xlsx。
- 后果：标称健康检查的用例被降维成"配置存在性验证"，**不覆盖被测机制的真实行为**（假覆盖的一种系统形态）。
- **缺口层级分辨**（Py-Eng 机械校准 + 我核 blocks.py 复证——对修复成本有实际差别）：
  - **server 触发端 = 文档/prompt 层，非组合子缺口**（零代码可补）：blocks.py:64-69 `_observe_step` 的 host 字段填非 DUT 主机名即生成 `test_env.<host>`（含 server231/232），case_ir `VALID_TEST_ENV_HOSTS` + structural_gate 全栈已认。worker 只是**不知道**该用 server host 做后端侧验证（后端 DOWN/UP 从 server 侧观测）。补 prompt/范式即可。
  - **execute + I 列 = 真组合子层缺口**（要么改代码要么引导退 steps）：blocks 5 kind 无 execute 类（OBSERVE 只生成 `test_env.host(cmd)`，不生成 `host.execute`）、无 I 字段；steps 五列表能表达，但 worker md:190「首选 blocks」使 worker 不走 steps → 实际写不出。
- 修法方向（记录不动手，按层分）：① server 端 → 文档层补 prompt（最低成本）；② execute/I → 组合子层：blocks 扩 execute kind + I 字段，或文档明确"这类退 steps 手写"并给 worker 范式；③ worker/文法层补"故障注入+主动报文抓取"方法论知识（跨两层）。

**P0-2｜负面测试范式缺失**（能力缺口，与 P0-1 同根：都是"主动改变被测对象状态"）
- 现象：期望"设备拒绝/失败/降级"的用例，worker 直发被拒命令 → 引擎 digest 判 broken。文档无范式、框架无"允许失败"方法、组合子无"期望失败"形态。
- 证据：…044538 连续两轮 broken。
- 修法方向：①文档补负面测试正解（改正向观测约束生效）；②引擎 digest 区分意图内拒绝 vs 意图外失败。

**P1-1｜EXCEL_FUNCTIONS.md 漏载三类范式**（文档层，worker 该学会）
- 负面测试范式（P0-2）、健康检查故障注入范式（P0-1）、`debug trace live` 抓设备主动报文范式。三者人工高频、文档零覆盖。
- 注：这是"文档没写"而非"文档写错"——B-vs-A 已确认已覆盖部分零漂移。

**P1-2｜blocks 组合子层能力边界未在文档说明**（组合子层，仅 execute/I——server 已剔除见 P0-1 层级分辨）
- EXCEL_FUNCTIONS.md 第47行只说"组合子表达不了的退 steps 五列表手写"，但**没说清哪些表达不了**（execute 动作步 / I 列 format 注入就在其中；server 端 blocks 本就支持，不在此列）。worker 不知道何时该退 steps，于是把该用 execute 的用例硬塞进 dig+found → 降维。
- 修法：文档明列 blocks 不覆盖的形态清单（execute/I）+ 各自的 steps 手写范式指针。

**P2-1｜close() core-dump 检测漏载**（归因面）：debug>1 时设备 core dump 计入 fail，attributor 不知则可能误归。建议 attributor 知识补一句。

**P2-2｜abs_found 分布倒挂**（非短板，源码坐实，回应 Py-Eng 根因求证）：found→abs_found 自动转**仅在 check_point 引用 H 寄存器作期望值时**触发（emit_xlsx_tool.py:158-159——捕获值含 IP 的 `.`/`@` 等正则元字符，`re.search(v1,v1)` 连自匹配都 fail、须字面匹配），本批 H 近零故此路**贡献小**；**主来源是 member 组合子展开成 abs_found**（precedent_tools.py:388「membership via abs_found」，静态成员 IP 集合用字面避免 `.` 通配误配 `172.16.35.226`→`…2264`）。二者皆**工具确定性机制/安全默认**，与 blocks「悬空断言/字面反斜杠写不出来」同一 correct-by-construction 哲学，比人工手写 `\b1\.1\.1\.1\b` 转义正则**更不易错**——**非过度转换、非假验证风险**，勿整改。（假验证风险另有独立的必崩门族防守：恒真恒假断言在 structural_gate.py:790 拦，与 abs_found 偏好无关。）

**P2-3｜SSL 证书族/多协议 HC 覆盖盲区**（用例差异，非当前短板）：本批无 SSL 用例，能力覆盖度未经检验，建议后续专门 SSL 批验证 emit 是否支持证书导入方法族。

---

**执笔说明**：本节语义定性由 LLM-Eng 追加；A/C/D 机械面与六候选由 Py-Eng。核心增量＝用同型子集实测把 Py-Eng 谨慎标注的「可能用例差异」坐实为「能力缺口」（P0-1/P0-2），并定位缺口在 blocks 组合子层而非单纯文档层。短板清单供 #24 leader 综合裁决上呈用户。
