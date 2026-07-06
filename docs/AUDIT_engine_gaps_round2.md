# 审计二轮:两轮实跑 + 人工卷对照挖出的引擎级缺口(2026-07-05)

> 触发:用户实证"数据面仍未 XML 化",并要求"检查所有没想到的、走了必有坑的、不符合先进引擎要求的"。
> 证据源:dongkl_v12 + yzg_v1 两轮全量数据、380 份人工卷(框架 mirror)结构画像、框架源码(mirror/lib/test_xlsx.py)。

## 一、三坑(用户确认,本轮已修)

| 坑 | 实证 | 修复 |
|---|---|---|
| **坑1 · XML 在工具里手改而非中间件** | 36 工具只改 3 个;fork 路径零覆盖;4 种不统一临时标签 | `ToolEnvelopeMiddleware`(wrap_tool_call):**全部**工具返回统一 `<tool_result name= status=>` 信封,一处生效;机读面零影响(代码层 .func 直调不经 ToolNode);内层自有标签保留成嵌套;幂等;`IST_TOOL_ENVELOPE=0` 关 |
| **坑2 · fork 中间件残缺** | get_subagent_runnable 只挂 LoopGuard——worker 跑 900s 堆几十个裸返回,剪枝/信封全漏 | `_build_fork_middleware()`:LoopGuard+ToolResultPrune+ToolEnvelope 三件套对齐(不挂 gating:fork 白名单已显式);提为可测函数 |
| **坑3 · 环境能力无事实源,靠上机撞** | 双机可用性要翻源码才知道;DC-1/2/3 三条缺陷全是烧设备时间撞出来的 | `knowledge/data/auto_env/env_capabilities.json`(双机/已知缺陷/静默失败模式,全带证据引用);compile_prep 自动注入 manifest;worker rules 首条=编写前对照;digest 归因第一步=对照 known_defects |

附:**坑4(APV_1 事故机械化)**——手写参考文档与框架源码漂移无人捕捉 → 一致性门(`test_reference_doc_covers_framework_dut_slots`:解析 test_xlsx.py 设备槽,断言 EXCEL_FUNCTIONS 全覆盖)。blocks 组合子补 APV_1 表达(CONFIG.host/观测 host,非法值拒)。

## 二、人工卷对照(380 份/4873 case vs 编译两卷)——三个重量级盲区

| 能力 | 人工用量 | 我们 | 定性 |
|---|---|---|---|
| **`execute`(运行时值抽取到变量)** | 2,208 次(如"提取PTR自动生成名称:{}\|8.8.8.8 → I=result1") | **0** | EXCEL_FUNCTIONS **零覆盖**——draft prompt 提过"能 execute 抽就抽"但没有语法文档,worker 无据可用。③层(设备不透明单值)本可少标很多 `<RUNTIME>` |
| **后端服务器直操(F=server231/232/console)** | 4,179+301 次 | **0** | 框架 devices 槽有 server231/213/http_server_231;健康检查/故障切换类用例**必需**(起停后端服务)——文档只教了 test_env+routera,未来编 failover 必撞墙 |
| **I 列(通用变量/参数位)** | 1,802 次(cmd_config+I 78/execute+I 37/found+I 19) | 1 | 文档只写了 found_times 一种用法;I 列真实语义是变量名/参数通用位 |
| routerb 多触发机 | 117 次 | 1 | 已在拓扑,轻量 |

**处置(2026-07-05 已完成取证+落地)**:跳板机源码全量取证(`/home/test/apv_src/lib/` 的 test_xlsx.py/env.py/ssh_server.py/client_action.py/dic_operation.py/client_synonyms 已同步进 mirror),权威语义:
- **E 列全集** = devices 表 12 键(test_xlsx.py:176):APV_0/1/2、Seg0-2_tmp、test_env(Env 对象,F=主机名方法闭集 9 个)、routera/server213/231/232(主机直连槽,fixture 返回 ssh_server 对象)、http_server_231。**E 拼错=框架静默跳过整步;F 拼错=getattr AttributeError 崩整卷**。
- **execute** 挂在 ssh_server 上(仅直连槽形态可用):动作闭集 8 个(client_action.py:10-19),`：`前缀匹配(直匹配→同义词→SequenceMatcher≥0.8),**不在闭集静默跳过不 fail**;dnsperf 统计字段没抓到静默返回 '0'。
- **H/I 变量机制**(test_xlsx.py:293-336):H=任意步存返回值;I=非 check_point 步 G 的 `{}` format 注入(支持 obj.attr)/check_point 步替换被比较输出;非 check_point 步 I 引用未定义变量 **raise NameError 崩整卷**。
- 落地:EXCEL_FUNCTIONS 增补(E 表/F 节/execute 机制/变量机制,found_times I 列旧说法修正);env_capabilities 三能力+两静默失败模式;structural_gate 新增分发白名单必崩门(_check_dispatch_targets)+observation/ip-cleanup(含 ip route 记账半边)/payload 三门扩围(直连槽/APV_1 此前漏)+非 check_point I 引用检查+G 逗号切参 lint+autoid 行 E 空 lint+steps_from_xlsx 对齐框架 case_begin;回归 13 新例。
- **过程教训(用户拦下,已固化 CLAUDE.md 红线+记忆)**:初版把 execute 27 动作分组清单+用途点评抄进 EXCEL_FUNCTIONS——注册表是数据,抄进文档=漂移面+替模型思考,违背「LLM 走控制面、数据按引用流」。收敛为:文档只写分发机制/语法契约/静默失败模式+源码路径(mirror 盘上 fs_read 现查);门的 execute 观测性判定同理从 mirror 源码解析(_execute_returning_actions),不硬编码。blocks 组合子(EXTRACT 类)仍待做(见遗留)。

## 二b、逐 autoid 对齐对照(用户纠正后的正确做法,2026-07-05 补)

对齐率:dongkl 33/34(97%)、yzg 18/26——51 个 case 人工版与编译版逐行 diff。总密度健康(人工 8.6 步/3.7 断言 vs 编译 8.9/3.8),四个实质结论:

1. **人工多出的断言 ≈ 写死值形态**(777976 人工:`found 1.1.1.1`+`Hit:\s+1` 写死单次命中与计数——正是 942 配对证伪的偶对偶错家族)。**不学**;引擎的区间/关系/归属形态是对写死值的修正,数据第三次佐证。
2. **多源触发是真维度差**:人工在对齐 case 里用第二触发机 ×42 模拟多客户端——我们全程单源,客户端区分类语义(会话保持/源哈希/多源轮转)产生不出"不同客户端"变量。**已修(按设计语言:陈述事实+指路先例,零命令零方案)**:compile-worker <task> 记两条先例事实(多触发机可用、同 autoid 先例可查、临时网络改动有框架恢复契约别自己发明清理);EXCEL_FUNCTIONS test_env 节补触发机事实与框架 IP 恢复契约警示。
   - **过程教训(2026-07-05,两次拦截)**:初版写死 `ip addr add/del`+"必须配对删除"被用户拦下;**重写后仍不干净**——redline-reviewer 抓到我把契约转述失真到了三处(json/EXCEL/worker),核心错误:以为"add 合法、del 非法"或"单次 add 框架兜底",而门的机械事实(structural_gate._check_no_manual_ip_cleanup)是 **test_env 步任何 ip addr add/del 都整步拒**,替代是"用拓扑既有多触发机"。三处已按门的真相二次重写。双重教训:①prompt 改动必过红线自查+评审(已存记忆);②**转述机械契约前必先读门的代码,以门的实际行为为准,不凭理解**——我两次都是凭对契约的模糊记忆写,门实际比记忆更严。
3. **execute 盲区的代价被量化**(667986):人工 `execute 配满16条+检查` 5 步完成,我们无此能力被迫 21 步(16 逐配+16 条重复 found),且行为验证反而只 dig 1 个端口——覆盖更弱。**已修(指导层,事实陈述式)**:worker 记"N 条同型存在性断言对'都能工作'覆盖为零+人工先例重心在行为侧且不止一点"的现象事实,具体验多少由 case 目的判断;**待做**:execute 语义跳板机取证后进 blocks(如 EXTRACT/BATCH 组合子)。
4. 人工 add/del 配对习惯 = 网络配对恢复门(遗留 #2)的人工起源佐证,优先级上调。

## 三、两轮实际数据的其余发现

1. **跨脑图效度假设被数据修正**:V4 验收 4 假设"dongkl 写回 → yzg 首跑受益"——实测 yzg(listener/HA 域)与 dongkl(sdns pool/method 域)先例几乎零重合,首跑 fail 80% 全是新域问题(1 个跨 case 网络污染辐射 16 个 + 4 个多余 sancheck)。**ρ_k 是按域增长的,跨域度量要重定义为"同域第二脑图"**(如 zhaiyq 若同域)。
2. **跨 case 网络污染是可门化的模式**(yzg 655233):case 内改 vlan/ip 未恢复 → 污染后续全部。已进 env_capabilities.silent_failure_patterns;**待做**:emit 结构门加"网络类配置命令(vlan/ip addr/route)必须配对恢复步"的机械检查(与框架 IP 恢复契约同族)。
3. **desc fallback 模板**已修(29/154 内部术语溯源=工具 fallback 非 worker)。
4. **grade 复核位的循环倾向仍在**(778041 三连 CUT 被人工停):**待做**:submit_verdict 对同一 autoid 的 CUT 连击计数,≥2 时工具返回强制提示"语义终判在上机,停止重判"。
5. 信封逃逸硬化(内容含 `</tool_result>` 字面可破框):风险低,记录不修(标签是结构提示非安全边界;安全边界在沙箱/门)。

## 三b、第三轮扫描(2026-07-05 晚,"已证缺陷类反推同类未爆点",均已修+回归)

方法论:**从已证实缺陷反推同类,比随机扫命中率高**——有一个实例就必有同类的模式。

| # | 坑 | 证据/判定 | 处置 |
|---|---|---|---|
| 1 | **非原子写是一整类**(意图索引损坏同病) | `last_run.json`(跨轮对照/归因/翻案/写回事实源)同为非原子 write_text——杀进程/并发截断成拼接损坏则整链失灵 | 已改 tmp+os.replace 原子写(读侧本有 try/except 兜底) |
| 2 | **回填重放生命周期洞(重量级)** | `compile_runtime_fill` 只写合并卷,per-case 卷仍 `<RUNTIME>`;任何重合并从 per-case 重建=**静默丢全部已填值**(v12 恰逢 RUNTIME=0 才没炸) | fill 把成功回填按内容键(autoid+observe_cmd+原G;整值槽 G 全是 `<RUNTIME>` 不独特靠观测命令锚)记 sidecar,merged 后按内容重放:卷面未变必中/重编改观测必不中(跳过不猜)。回归 test_runtime_fill_replay |
| 3 | **中间件交互:信封×剪枝标签不平衡** | ToolEnvelope 头部放 `<tool_result>`,ToolResultPrune 剪尾带走 `</tool_result>` → LLM 见不平衡 XML | 剪枝 stub 检测头部未闭合标签补回闭合。回归 test_pruned_envelope_stays_balanced |

## 三c、欠定判定复核(2026-07-05 晚,用户质疑"这 8 个是否真欠定、人工怎么解决的、我们逻辑有没有问题")

三方对照(脑图原文 × 我们的 needs_decision × 人工卷 sdns_method.xlsx 同 autoid 逐行反解):

1. **人工解法破译**:脑图"三个 pool"=v4 池+v6 池+混合池;人工让"客户端2"发 **AAAA 查询**——AAAA 应答只能携带 IPv6(协议事实),v6 池是唯一候选 → "命中第二个池"是**确定性行为,与 rr 起点无关**(v12 归档真实回显 `dig AAAA → 172::232` 佐证)。人工验的是地址族路由,不是轮转位置。
2. **我们的逻辑缺陷(坐实)**:claim 抽取把"两客户端各命中一池"整体读成 absolute_position 判欠定——缺"查询类型×池地址族→候选池过滤"维度。真相半可验半欠定:AAAA 半段静态可验(不该问用户);A 半段(v4 候选=纯v4+混合 2 个)才真欠定。保守方向(没产假断言)但违"明确的事情一遍做完"。
3. **人工的另一半不学没错**:`A 恰中 p1`/`Hit:\s+1` 精确计数写死依赖起点固定+零干扰——942 配对证过的偶对偶错家族。
4. **已落地**:worker 四层模型节补"先按查询类型缩候选池集合"事实;verifiability 工具 n_pools 口径改"候选池数"并注明"唯一候选=静态层不用调本工具"。
5. **待上机证实的边界**:设备对 AAAA 是候选过滤还是"轮转到纯 v4 池给空应答"——v12 单点回显支持前者;verify 轮加 6 连发 AAAA 探针(全 172::232 + p2 Hit=6 即证),证实后写 env_capabilities/footprint。

## 四、遗留清单(优先级序)

1. ~~execute/I 列/server231 语义取证 → 补 EXCEL_FUNCTIONS~~(2026-07-05 已完成,见 §二处置);**blocks 组合子扩展**(EXTRACT/直连槽表达)仍待做——文档+steps 通道+门已通,组合子是省心通道的补齐
2. 网络配置配对恢复的 emit 机械门(须先核实 655233 真因,防强字典误杀——需上机)
3. ~~grade CUT 连击止损~~(2026-07-05 已落:submit_verdict 凭证记 cut_streak 跨重编累计、PASS 清零,≥2 附加"942 配对实证 CUT 重做零增益,疑虑写 caveats 交上机 oracle"机械提示;回归 test_submit_verdict_cut_streak_hint)
4. ~~跨域效度度量重定义~~(2026-07-05 已落:PLAN_v4 步骤 4 验收②改为"同域第二脑图",原跨域对照测的是新域冷启动非写回增益,修订记录在 PLAN 原文)
5. ~~TUI 粘性错误状态条~~(2026-07-05 已落 ink 侧:FooterPane.set_sticky_error 驻留 run_error 摘要于状态行(红,单行截断 96),下一轮 busy 自动清;Textual tui/ 侧 reducer 已有 _status=error,渲染同型待需要再补;回归 test_sticky_error_*)
6. yzg 剩余 9 fail 收口(4 双机递归转发语义 + 655233 隔离验证 + …)——下轮会话继续
7. 非 check_point I 未定义引用是必崩类,当前挂 _check_capture_refs_defined(lint/strict 路径)未进 check_crash_gates_mandatory——lint 双卡点(凭证+合并)兜住不会漏网上机,但 worker 反馈慢一轮;下次动 gate 时顺手挪
