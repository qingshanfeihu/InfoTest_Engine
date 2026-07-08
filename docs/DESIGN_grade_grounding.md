# 设计：grade = 设备实验循环——让 worker 的错模型在交货前被设备戳破

> 全链条证据：`docs/DIAG_035413_reasoning_divergence.md`（LangSmith trace + 设备实证 3 实验 + 学界调研 + infotest 最小实验 8 轮 + 工具可行性验证）。本文是定案 + 执行入口（compact 后从这里续）。

## 一句话

worker 会拿一个内部自洽但事实错误的产品行为模型写配置、自己发现不了（035413：以为 cname.a.com 会绕回 www.a.com 的池）。**唯一能戳破它的是设备。** grade ＝ 把「配→dig→比意图→不对就调再试」这个设备实验循环，做成 worker 交货前的一步。用设备事实（不是 LLM 意见）挡住脑补的错配置。

## 为什么是这个方向（已实测坐实，不是推测）

- **同一模型，框架决定成败**：deepseek-v4-pro 作为 worker（凭先验硬写）3 轮 escalated；给「设备验、dig 对不上就迭代」框架后，8 个实验自主收敛到正确多根因诊断（cname.a.com 需配 host + service disable 不触发 pool 回退），比人工手动实验挖得更深。它还激活了原 worker 有却忽略的手册 requery 规则——**grounding 让沉睡知识变可用**。
- **学界背书**：失败模式有名（EnvSimBench「fabricating incorrect state transitions」）；GILP（arxiv 2606.27806）量化证明 grounding-before-commit 完胜 post-hoc（0.838/15k vs 0.684/26k token）→ **修复属产出前、不属 attributor 那层**；我们比论文更好——用真设备当 oracle，不吃学习模型的近似误差。

## 三角色定案（结合，不是取代）

| 角色 | 保持 | 结合点 |
|------|------|--------|
| **worker** | 产出配置+断言 | 承认注意力会被劫持、**不指望它自纠**（这正是被劫持的那步推理） |
| **grade** | 继承老 grade 的**目标（断言真覆盖行为）/溯源核对/边界（结构归 emit 门）/纪律（上机型疑虑不当 CUT）** | **补上老 grade 唯一缺的——设备**：worker 写完必须触发；纯结构问题离线拦，行为问题设备验 |
| **attributor** | 判真正只有整批上机才显形的（并发/时序） | **结构化多维填槽防劫持**（配置期拒绝／配置实现意图＝dig 对不对／断言质量，各占一格，priority 挤不掉 coherence）+ `?` 工具解拒绝 |

**老 grade 为何删（考古）**：它是 LLM 意见型断言质量审批、纯离线，942 对实证判别力仅 3pp、同卷面 PASS↔CUT 翻 5 轮——删掉「LLM 意见」这个噪声手段是对的。新 grade 不复活意见层，换成设备事实（dig 返回 cname.a.com ＝不翻案）。

## 触发策略定案（用户拍板，选择性 + 末轮 max think）

- **每轮都跑（便宜）**：① 离线引用图链接器（查悬空引用：cname.a.com 被引用却无 host 定义——红线内，引用完整性=文法规则；但只出提示、不下判决，判交给设备）+ ② `?` 解拒绝 + ③ 结构化 coherence-first 归因。解掉能正常收敛的 case（本轮 6/13 R1 就过）。
- **末轮 max think 才触发设备实验循环（贵、精准）**：一个 case 熬到第三轮还没过＝真卡住的错模型硬骨头（如 035413）。引擎本就在末轮升 max think + 喂全历史，正好在这步给 worker 设备实验能力，像手动 A→B→C 那样试出正解。**只给少数末轮 case，不摊到全部。**
- **为何不早触发**：7/7 R1 失败虽都 R1 可拦，但便宜三件套先救大多数；设备实验最贵、留给三件套救不回来的。代价＝硬骨头先花 R1/R2（正常返工），这正是 ④ feedback 的价值（末轮学到的正确模型缓存进 footprint，下次上机前就会、不再花 R1/R2）。

## 落地第一块：dev_ground 轻量工具（前置条件，已验证可行）

设备实验循环要「应用配置块→dig→回显」秒级完成，不能走 compile_emit 造 xlsx + dev_run_batch(30s)（agent 实验就烧在这、¥7.87/18min）。**90% 能力已在框架里**：
- **应用配置已存在**：`apv_ssh_execute` 本就支持 `mode=config`（特权下发，实测 `sdns host name ...` → `APV(config)#` success、show 验到、`no` 清理）。dev_probe 只是工具层白名单成 show/get 把它藏了。
- **dig 现成**：跳板机直接 `dig @172.16.34.70 <域名>` 返回真 IP（已验）。
- **做法**：改造 dev_probe 或加兄弟工具 `dev_ground`——暴露 apv_ssh_execute 的 config 模式 + 加一步跳板机 dig + 清理。低风险（复用已验证零件）。
- **caveat**：ga 是 geo-aware，跳板机 dig vs routera dig geo 选池可能不同；grounding 判「观测类别」（IP vs cname 字符串、链通不通）跟源无关，跳板机 dig 够用。

## v2（2026-07-08 定案落地）：证据分级后的最终形态

> v1 的执行顺序（dev_ground 工具→末轮设备实验→…）已被两轮对抗性质疑 + 两个验证实验**修订**。
> 全量取证见 `docs/TRAJECTORY_035413_worker_vs_main.md`（含 7/7 R1 失败三簇分类）。

### 已落地（A 级，证据充分）

1. **A1 空断言 pattern 必崩门**（`structural_gate.py`）：check_point 的 G/H/I 三列全空=无物可比。存量反扫 541 卷校准——初版只查空 G 险些误杀 28 张金标准卷（空 G+H 寄存器=捕获比较合法形态），收紧后零误报。覆盖 044605。
2. **A2 引用图链接器**（`grade_extract_script.py` + `compile_phase.py`）：cname 池成员未本地定义→结构事实。**两个意外发现**：①机械探针接线 bug（单参调双参函数、TypeError 被吞）——**探针自引擎上线从未生效**，已修；②该事实在 12/13 真机 PASS 卷上同形（委托外部 DNS 是常态）→ **无 rework 触发资格**（`_PROBE_NO_REWORK`），改为 fail 重编时注入 brief、与设备回显合取才有诊断力；rework 环加同 suspect 只触发一次防打转。
3. **A3 brief 去劫持**（`_build_brief`）：意图摘要内联置顶（响度对抗错方向）、fix_direction 降级为「上一轮假设(可能已被证伪,先独立复核)」、末轮首问「配置实现意图了吗」。
4. **A4 知识沉淀**：`sdns.pool.cname.json` 种 3 条设备实证 decision_rules + 锐化被 R1 误读的含糊 requery 规则 + `sdns.host.name.json` 交叉引用；attributor 对配置一致性发现必调 `submit_behavior_fact`（晋升机制 `closing.py` 本就存在）。
5. **A5 归因判层收紧**（`compile-attributor.md`）：coherence-first（先答「配置实现意图了吗」再分层）+ product_defect 两道前置核对（同批同签名 cross-check + 写明已排除配置未实现意图）。redline-reviewer 全过，建议级发现（prompt 裸放未定论行为语义）已修正。
6. **dev_help `?` 工具**（此前已落地）：`^`/`Failed to execute` 后追问设备该位置期望什么，零副作用。

### B0 方向盲测结果（2026-07-08）→ **B1 设备实验环取消**

盲 judge（意图+配置+R1 回显，无归因结论）判方向：
- 035413（真配置错）→ 判「改配置」✓（但其具体修法「删 cname 池绑定」违背意图第一条——方向对、修法层错）；
- 035373 → 判「改配置」，与部署系统当年的「改断言」相反。**但复核 035373 意图原文**（「disable/enable service pool → 按不同的操作进行返回」），设备恒返回 cname 并不满足意图——盲 judge 的读法对着意图反而站得住，当年的 not_found→found 正是迁就式假验证（TRAJECTORY 附录已标记）。

**结论**：不是 judge 被证伪，是「方向真值」本身需要意图仲裁、而部署系统自己都仲裁错过——假设「LLM+设备事实可靠判方向」**未获验证**（一干净通过、一无法裁决）。按方案纪律（任一判反即止），**B1 末轮设备实验环不落地**；防线由 A 级承担：结构错→lint 门，已知语义→footprint 注入，错方向→brief 去劫持+归因收紧。若未来对一批 case 建立**人工仲裁过的方向真值集**，B0 可重跑翻案。

**附带发现**：035373 交付卷的 PASS 是迁就式假验证候选（断言接受了与意图相反的不变行为），建议人工复核。

### 验证
- 门回归：`test_xlsx_lint_gates.py`(32) / `test_grade_extract.py`(19) / `test_skill_package_standard.py` / `test_prompt_structure.py` 全绿；541 卷存量反扫零误报。
- **A3 eval 已跑（2026-07-08，trace `019f401c-8571`，413s max worker）**：机读判据对比 before 基线（trace `019f3bc3`）——拓扑洞察 **0→5**、dig 形态质疑（返回 CNAME 而非 IP）**0→33**、priority 词频 203→122、host method 165→56。**去劫持生效**：worker 首次判到配置结构层（"前 3 轮失败均因 CNAME 池被绑定到域名…跳过回退"），产出改配置方向。
  - **残余缺口（已补）**：它的修法是"解绑 cname 池"（剪掉可疑部件）而非"把 cname.a.com 配成本地域名"（接通链路）——对意图第一条覆盖存疑。溯因：worker 查了 10 次 kb_footprint（fallback/host pool/host method…）**唯独没查 `sdns pool cname`**，A4 种子触达失败。已补交叉种子进它实际必查的 `sdns.host.pool` 节点；且真实引擎流程中 R2 失败卷会触发 A2 的 fail 路径注入（重放时盘上恰好是已修好的卷故未触发），双通道兜底。
- 端到端（待用户确认烧设备）：cmux 重跑 CNAME 脑图（93/79/105），判据：R1 probe 拦截>0、上机轮次<4、同症不同判=0、035413 不再 escalated 且配置**接通** cname 链路（不是剪掉）。

### 端到端对照轮终验（2026-07-08，批 `CNAME_ipo_rerun2`，环境 93）

**终态：11/13 通过、0 escalated、2 个证据齐全的缺陷候选**（dongkl 批：10/13、1 escalated、2 个未复核缺陷标签）。

| 判据 | 结果 |
|---|---|
| 035413 接通链路不 escalated | ✅ **R1 一次 PASS**（卷面 `sdns host name cname.a.com` 接通 re-query 链路；上轮 3 轮 escalated） |
| 同症不同判=0 | ✅ R1 时 035493/035570 同判 V/reflow（上轮 V/defect 分裂）；035570 后升 defect 是基于 R2 新证据+同批 644/608 交叉对照，非同证据分裂 |
| 上机轮次<4 | ➖ 持平（4 轮：R1 全卷+R2 子集5+R3 子集3+终验全卷；dongkl 也 4 轮）——轮数没省，但轮内产出质变（11 pass+0 escalated vs 10+1） |
| R1 probe 拦截>0 | ❌ 0 次触发——合格 suspects 未命中（cname suspect 已设计排除出 rework），R1 改善实际来自 A3 意图置顶+A4 种子（13/13 R1 即正确拓扑）。判据当初设错了通道，探针是兜底不是主力 |

**判据外的实证收获**：
- **035373 真修**：断言真覆盖「按不同操作返回」（not_found/found 交替断言 IP 随 disable/enable 变化），替代上轮的 not_found→found 迁就式假验证——B0 盲测质疑的那个案例被真解了。
- 044572/044605 **R1 直接过**（上轮各烧 2 轮）。
- **dev_help 有机使用**：035644 一行式 cname 语法被 `^` 拒后，worker 自发 `dev_help` 追问三种语法变体、改两步子命令修复——当天上线的工具当天在生产被消费。
- **种子知识被引用 ×3**：035373/035493/035570 的归因 fix_direction 明文引用 footprint 种子规则。
- **035570 发现全新行为交互**（cname 成员同时为本地 host 且其池 service disable → CNAME 查询 ANSWER:0，与「别名池无健康检查」预期矛盾）——正是 grounding 类知识，已按 defect_candidate 走人工复核。
- 顺手抓出并修复 **2 个静默 bug**：①机械探针接线 TypeError 被吞（自引擎上线从未生效）；②`_xlsx_apv_lines` 等 4 处硬编 "203" autoid 前缀——204 批 105/105 条台账 apv_cmds 为空，device_verified 写回/行为晋升对 204 批一直静默失效（本轮 attributor 的 submit_behavior_fact 全被此 bug 拦下，修复自下轮生效）。
