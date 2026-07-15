# dongkl 遗留问题·取证综合 + 重新定稿 + 给用户的问题(2026-07-15)

> 用户裁决:不信 §18.15「设计中」定稿,从 Langfuse 真实 LLM 执行 + 盘上真实数据重新定稿,
> 有疑问讨论。4 个取证 teammate 只读实证,报告见 `docs/forensics/{A_oracle,B_attribution,C_gates,F_closeout}.md`。
> 本文综合 + 我(协调者)的独立核验 + 给用户的问题(附倾向/两方)。

## 0. 取证印证了「别信定稿」——§18.15 方向对,但有真实的洞

- 文档里 778012 有**三个互相矛盾的历史叙事**;只有 last_run 的实际归因是 ground truth(oracle 厘清:r1 语法错 G→修好后 subset RR 轮转 V,跨轮演化非矛盾)。
- §18.15-A **不能单飞**(见 Q1);§18.15-B「转 V 深归因」文案**有歧义**且会覆盖用户已选的 E(见 Q2/Q3);§18.15-C **已落地**(核验通过,非补齐)。

## 1. 统一根因:归因层机械后校验缺失(贯穿 A + B)

四份报告收敛到**一个共同根因**:`fail_attribution.py:submit_attribution` 对多数 disposition **无机械反证门**——只要 evidence 是 device_context 子串就无条件采信 layer/disposition。§18.14 只给 `s₀`(h_s0) 建了**前筛**复核;同类洞对其它 disposition 敞开:

| disposition | 洞 | 活案 | 后果 |
|---|---|---|---|
| `env_blocked` (B) | 无同案内一致性门(prompt 只教跨案) | 777976(同卷 passed_cp=2 自证伪"环境不通")/994986(fix_direction 自身说 V+`root@console` Linux 提示符) | **清空修法队列 + escalated 移出重编环**——可修的 V 案永不 reflow |
| `rerun_isolated`/h_lambda (A) | 无「配比×样本≫0 但 Hit:0=缺陷」反证 | 593516(配比40成员10次dig实得0,引擎发"加采样刷过") | flaky pass→**写回 precedent/footprint(live 可检索,采样噪声进第二权威源)** |

**三者同型**:§18.14 s₀=**前筛短路**(机械证据足→不派 LLM);B/A=**后校验**(LLM 判完机械扫反证)。同址 `fail_attribution.py`,信号全**结构化**(框架计数器 `The passed check point num:N`、shell 提示符 `root@…#`、配比×样本量算术),**非关键字白名单**(红线)。→ 定稿应把 A/B 合成**一条 attributor 后校验机制**,不同 disposition 挂不同结构化反证。

### 1b. 更深的暗线:判例投毒闭环((45)/(45b) 自指,trace 交叉印证)

三案 worker trace 揭出一个比"归因层缺后校验"更深的闭环:
- **593516**:flaky/observe-then-assert 断言 pass → **写回 precedent/footprint**(live 可检索)。
- **777976**:worker reasoning「both p1 and p2 have Hit:\s+1 after two queries」的 per-member 计数断言 **继承自 precedent**(与 593516 同源)→ 被误当 env_blocked。
- **572708**:round-1 worker 本写了 manual-忠实的正确 `not_found`(reasoning「method is gone」),**是 attributor 的 F1 面板**把历史机生 `found` 前轮检索抬出、去覆盖 worker 那条正确断言。
→ **闭环**:flaky/observe-then-assert 写回 precedent → 检索注入新案 worker → 归因器 F1 放大、盖过人源(manual)。这是 A(写回护栏)+ B(后校验)+ F1(血统)三条修法的**共同上游**——堵一处不够,要断闭环:写回端(A Gap3 降级 uncertain)+ 检索端(F1 不以机生血统盖人源)+ 归因端(后校验)三处合拢。

### 1c. abs_found 修正(用户 2026-07-15 challenge,已核 check_point.py)

oracle Gap1「集合相等不可构造」**过强**。拆两方向:**⊇(配置成员都参与)= `abs_found(ip_成员)` 合取可构造**(abs_found 行38=`re.escape` 字面 search);**⊆(无配置外成员)由 config 保证、不需断言**。∴ **membership h-不变式可构造**,A 门不必等 D;**唯 WRR 配比(跨成员比计数)真不可构造**(唯一计数算子 `found_times` 被 2 参门拒)→ D 收窄到只服务 distribution/ratio 子类。样本量用 **config 推导确定性覆盖数(Σweights×k)**,非引擎的"加采样刷过"。

## 2. 各单元重新定稿裁决

| 单元 | §18.15 原判 | 取证裁决 | 落点 |
|---|---|---|---|
| **A** RR 采样+写回 | BLOCKER,先做 | **方向对、三处不充分**:Gap1 emit 门要的"集合相等"框架 found/not_found **不可构造**(纯正则,写不出补集取反)→**A 门必须 D 先给可落形态**(见 Q1);Gap2 根因在归因层(补后校验,§1);Gap3 写回护栏该分流(见 Q5) | `fail_attribution.py`/`nodes.py:_writeback_one`/`grade_extract_script.py`(已有分布检测器可复用,补第三形态 `Hit:\s+[1-9]\d*`) |
| **B** env_blocked | MAJOR | **诊断对、未实现**;两机械信号全批零误伤但**只够触发复核、不够自动定 V**;文案"转 V"歧义(见 Q2) | `fail_attribution.py` + 挂进既有 escalate 面板(red-line-11 override 链) |
| **C** broken | 核验,小 | **已正确落地**(§18.1 七款全落地+测试+210998 实证);只需补 210998 回归锚 + 一个 rerun-vs-reflow 观察(见 Q7,倾向不改) | `test_window_audit.py`/`test_broken_third_state.py` 补锚 |
| **D-command_existence**(发现2/4) | — | **单信号门**;两档无红线信号可加(`nearest_heads==[]`→垃圾、严格前缀→截断),`sdns clear all` 需脑图溯源=撞红线→守(见 Q6) | `emit_xlsx_tool.py:_gate_command_existence`/`command_inventory.py` |
| **D-DNS lint**(发现5) | — | **一行 bug**:`structural_gate.py:1097 _DOMAIN_TOKEN_RE` 的 TLD 白名单锚,裸长单标签(无点)漏网;**直接可修**(裸标签扫描,RFC 63 物理常量,零硬编) | `structural_gate.py:1097-1100` + 补 no-TLD 回归锚 |
| **F1 血统**(发现8) | — | 面板预设"改found=与verified前轮一致",**机生血统把第三源极性倒置**(circular);正解=不预设默认、对称呈双源(见 Q4) | `compile-attributor.md`(prompt)/`ask_panel.py`(schema) |
| **Section B 三 TODO** | 声称 RESOLVED | **代码核实=真 RESOLVED**(18 passed + dongkl 全34案零 h_s0 假阳);可标 RESOLVED | 文档簿记 |
| **TODO_tui 面板** | 未修 | 根因坐实:`ist_app.py:2171 _replay_snapshot` 漏重置 `_ask_user`→resize/ctrl+t 复活答完面板;**直接可修**(复用 `replace_content_block` 样板) | `reducer.py`/`ist_app.py`/`ask_user/__init__.py` |

## 3. 给用户的问题(设计张力项,附倾向+两方;我不拍板)

**Q1【最大·架构 aha】A 与 D 的先后**:A 的 emit 门拒采样断言、却只能要"集合相等(不可构造)/区间(bug 温床)"→分布类案没有合法替代形态→**A 单飞把假 pass 变永久卡死**。真正的替代形态需 **D(我方验证侧解析响应→抽命中整数/成员集→真算子比,π 忠实实现)**。→ 是否把「A>B>C>D 分期」改为 **D-phase1(先覆盖 RR/dig/show statistics 命令族)与 A 门同批落**?倾向:是(否则卡死分布类案);反方:D 工程量大,可让 A 先落、分布类案暂走 ask_user/escalate 软性兜底,D 从容分期。

**Q2【归因后校验机制】自动降级 vs 标记复核**:机械检出 env_blocked 矛盾后,引擎**自动改判 V 直接重编**(省交互,但覆盖你已选的 E、且信号不足以定 V),还是**把矛盾并进现有环境确认面板交你复核**(多一条证据,你仍拍板)?倾向:标记复核(§2.6.6「冲突本身不构成判决」+ 仿 expectation_suspect 既有范式 + 不覆盖用户裁决权)。同一机制统辖 A 的"加采样 vs 缺陷"后校验。

**Q3【层定义】console 打到 Linux 主机算 V 还是 E**:验证命令落到 `root@console` Linux 主机(而非设备 SSH)——V(worker 通道错,reflow 换设备 SSH)还是 E(床 console 口没接设备,呈报)?你已对 994986 选 E。注:777976 和 994986 **不同**——777976 机械上几乎确定误归(passed_cp≥1 硬否证),994986 才是真 V/E 分歧。倾向:默认按 V 呈报候选、面板同时给 E 读法交你确认。

**Q4【F1 血统护栏】**prompt 软护栏 / schema 血统标注硬护栏 / 两者都做?倾向:都做(prompt 立即降偏向 + schema 让"机生同族·未审计·非独立佐证"在题面机械可见)。

**Q5【写回护栏粒度】**整案不写 footprint/precedent,还是分流(config/behavior 事实照写、只把案级 precedent `device_verified` 戳降 uncertain,引 (45))?倾向:分流(一刀切误伤合法知识增长)。

**Q6【command_existence 激进度】**加两档无红线前置分流(`nearest_heads==[]`→reflow、严格前缀→reflow),`sdns clear all` 类守红线继续 ask_user?倾向:是(守红线,宁多问一次不越界判命令词序)。

**Q7【broken 处置】**维持"一律 rerun + streak≥2 升级"(守 (44) 短路纯粹性),还是为 authoring-distortion broken 开 reflow 快捷路?倾向:不改(精化应走 pyATS 7 码子分类,属分期)。

## 4. 可直接做、无需你拍板(清晰修复+低风险,除非你否)
- DNS lint 裸标签扫描修复 + no-TLD 回归锚(Q6 的 command_existence 除外,DNS 这块无红线)
- TODO_tui 面板 answered 事件 + replay 重置(复用既有 `replace_content_block`)
- Section B 三 TODO 标 RESOLVED(文档)
- 210998 broken 形态回归锚
- 理论两处补注实现落点(S§0.5 分界判据归 attributor;(45) 写回护栏→降级 uncertain)——指出式,不改理论主体

## 5. 验收:用户要求「改完立即真机验收」
实现后走 /engine-verify-loop 真机通道(cmux 起 infotest + 跳板机上机 + langfuse/fastlog 三通道),跑受影响案(593516/778012/777976/994986/210998/994838/994869/572708)验证:
- A/B 后校验:归因不再误标(env_blocked 矛盾被标出 / "加采样"翻 defect_candidate)
- DNS lint:994838/994869 单标签超长 emit 期被拦
- broken:210998 正确路由不误重编
- F1:572708 面板不预设 found 偏向
