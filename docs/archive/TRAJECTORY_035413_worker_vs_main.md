# LLM 运行轨迹对比：035413 三轮 worker（漏根因） vs 一次 main（中根因）

> ⚠️ **历史存档（2026-07-17 归档,team4 docs 整编）**：035413 轨迹对比(DESIGN_grade_grounding 证据链,随其同归档)。事实存档不删,现状勿引本文。

> 数据源：LangSmith project `infotest_engine`，2026-07-07 `CNAME pool支持ipo算法_dongkl` 编译三轮全 trace + 2026-07-08 main 复核。全程只读取证，未改代码。
> 目的：同一个模型（deepseek-v4-pro）、同样深度思考，为什么三轮 worker（含 max 思考的 R3）漏掉功能配置根因，而 main 一次就中。结论：**差别不在能力，在输入的框定**。
> 关联：根因诊断 `docs/DIAG_035413_reasoning_divergence.md`；grade=grounding 设计 `docs/DESIGN_grade_grounding.md`。

---

## 0. 一句话结论

三轮 worker 每一轮的设备回显里，`dig @172.16.34.70 www.a.com` 都返回字面串 **`cname.a.com.`（不是 IP）**——根因（cname.a.com 从没配成本地域名、解析不出 IP）从**第 1 轮就摆在回显里**。但每轮 worker 收到的输入都被两股力量框住注意力：①**系统提示**把它 prime 成"断言编译器"；②**brief 用 attributor 的错结论开路**（R1「加 host method ga」→ R2「加 priority」），把"问题=配置语法"当既定事实内联在最显眼处。真正的意图（脑图）只按引用给 manifest 路径。结果：模型顺着喂进来的错轨道越走越深，max 思考只是把错方向想得更精细。

main 拿到的是**一句无污染、单焦点的诊断问题**，系统提示是"自由只读诊断者"，能力当场释放、一次中根因。

---

## 1. 两条轨迹总览

| | R1-worker | R1-attr | R2-worker | R2-attr | R3-worker(max) | **main(今天)** |
|---|---|---|---|---|---|---|
| trace | 019f3ba9… | 019f3bb1…4697 | 019f3bbb-6e30… | 019f3bbf-25b5 | 019f3bc3-a190 | 019f3f5d-7b07 |
| 收到的框定 | round1，无前置结论 | 上机 fail 回显 | 「加 host method ga」 | 上机 fail 回显 | **「ga 下 priority 必填，加 priority」** | 一句干净问题 |
| 做了什么 | 全挂 www.a.com，无 ga/priority | 判「cname 池该被抑制」 | 补 `sdns host method www.a.com ga` | 判「缺 priority」 | 补 priority 排序 | grep 手册→footprint→dev_probe(show) |
| 设备结果 | dig→`cname.a.com.` **fail** | — | dig→仍非 231 **fail** | — | 产出 xlsx（**根因仍在**） | **中根因** |
| 有没有碰根因 | ✗（回显已暴露） | ✗（治表面：抑制 cname 池） | ✗ | ✗（注意力被 priority 劫走） | ✗（思维链自证锁死） | ✓ |

> R1-worker/R1-attr 的 brief 未直接含 autoid 文本（批派走 briefs_path 按引用），trace 前缀取自 `docs/DIAG_035413_reasoning_divergence.md` 已锁定的锚点；R2/R3 由本次 LangSmith 直接命中并逐字取证。

---

## 2. worker 三轮轨迹（逐轮取证）

### 铁证：dig 每轮都返回 `cname.a.com.`，从第 1 轮就可见

R3 worker 的 brief 里内联了前两轮的完整设备回显（`_build_brief` 末轮全历史），逐字摘录：

**第 1 次（R1）设备回显**（`RouterA.txt`）：
```
dig @172.16.34.70 www.a.com A +time=2 +short
cname.a.com.
```
配置片段：`sdns host pool "www.a.com" p_main` / `sdns host pool "www.a.com" cname` / `sdns pool cname member cname cname.a.com`——**cname.a.com 只作为 cname 池成员出现，从没被 `sdns host name cname.a.com` 配成本地域名**。所以 dig 解析到 cname.a.com 这个名字就停了，它不是本地域名、解析不出 IP → 返回字面串。**这就是根因，第 1 轮回显已完整暴露**。断言 `fail to find 172.16.35.231`。

**第 2 次（R2）设备回显**：已补 `sdns host method www.a.com ga`（照 R1-attr 的方向），骨架不变，dig 仍非 231 **fail**。根因原样还在。

### R1-attr：看到正确症状、归错方向

R1-attr 看到 `dig=cname.a.com≠IP` 的症状，但没质疑 worker 的心智模型，把问题归成「cname 池该被抑制」，修法＝「加 `sdns host method www.a.com ga` 让 GA 抑制 cname 池」。**它接受了 www.a.com 的错误骨架，只治表面。**（来源：DIAG 锚点 + R2 配置确实新增了这条）

### R2-attr：注意力被 priority 完全劫走（错结论定型）

R2-attr 的产出 = R3 brief 顶部的「定向重做」，逐字：
> 当 host method 为 "ga" 时，sdns host pool 命令的 priority 参数为设备端必填（设备回显明确要求 priority must be valid，并拒绝执行）。需在编译生成 sdns host pool 命令时，检测当前 host 的 method 是否为 ga/wrr，若是则附加 priority 值（0-65535）。两条被拒命令应改为：`sdns host pool "www.a.com" p_main <priority>` 和 `sdns host pool "www.a.com" cname <priority>`。

这是一段**又长又自信、且技术上属实（priority 确实必填）但完全错焦**的定向——它把"配置期一条命令被语法拒"当成了主因，而真正的主因是"运行时 dig 根本返回不了 IP"。这段话此后成了 R3 worker 输入里最响的信号。

### R3-worker：max 思考，思维链自证被锁死

R3 worker（trace `019f3bc3-a190`，08:50 UTC，max 思考）实际做了：`fs_read manifest ×7`（**拿到了脑图意图**）、`kb_footprint ×6`、**`dev_probe ×1`（碰了设备）**、`compile_emit ×1`。**意图有、能力有、设备也碰了。** 但它最终产出的思维链（`reasoning_content` 逐字）证明注意力被彻底锁死：

> "p_main priority 10 (higher), cname priority 5 (lower) → GA always selects p_main for all query types... This **fixes both round 1 (CNAME pool interfering with A queries) and round 2 (missing priority on host pool commands)**."

它把根因归成"CNAME 池干扰 + 缺 priority"——**逐字复刻了 attributor 喂进来的错方向**，全程**没问过一句"dig 到底返不返回 IP / cname.a.com 是不是本地域名"**，尽管这个反例就摆在它 brief 的每一轮回显里。max 思考没有帮它跳出框，只是把错方向（priority 排序让 GA 选 p_main）想得更精细自洽。

---

## 3. main 轨迹（2026-07-08，trace 019f3f5d-7b07）

**收到的输入（我发的原话，单条 HumanMessage）**：
> 自动化环境上我下发 `sdns host pool "www.a.com" "poolA" ga` 这条命令被设备拒了，回显在某个位置打了个 ^（前置 www.a.com 已建为 host、method 已设 ga、poolA 池也建好了）。帮我在设备上确认设备为什么拒这条命令、这个位置到底该填什么、正确命令怎么写。

**做了什么**：grep 手册 `app_10.5_Chapter25.md` → `kb_footprint('sdns host pool')` → 加载 device-verify → `dev_probe(show sdns host pool/pool/host)` 上设备确认现状。

**结论**（一次中）：
> 第三个参数是 0~65535 的整数（权重/优先级），不是 ga。ga 是算法名、在 `sdns host method` 里设，不在 pool 命令里……正确命令 `sdns host pool "www.a.com" "poolA" 5`。

无任何前置错结论污染，模型从零推理直接推对。

---

## 4. 输入框定并排对比（核心）

| 维度 | R3-worker 收到的 | main 收到的 |
|---|---|---|
| **系统提示** | 9273 字 `compile-worker.md`：`<role>`＝"编这条 case、只对**断言真覆盖**负责"；`<task>`＝**6772 字断言机械**（desc 写法/意图分层/rr-wrr 命中计数…），关键词密度 `断言×39 / 算法×11 / 层×13`。把模型 prime 成**断言编译器** | 6950 字 `build_system_prompt`：`<role>`＝"默认只读分析，读证据**理解用户目标并回答**"；`<workflow>`＝探索/理解/验证/设备，**零断言机械**。把模型 prime 成**自由诊断者** |
| **任务消息** | **以 attributor 的错结论开路**：「定向重做：ga 下 priority 必填，加 priority」内联在最显眼处，作为既定事实 | **一句干净、单焦点、无前置结论**的诊断问题：「为什么被拒、该填什么、正确怎么写」 |
| **真实意图** | 脑图**按引用**（只给 `manifest_path`，要自己 fs_read；即便读了，响度也拼不过内联的错方向） | 症状（^）与目标**直接内联**在问题里 |
| **前几轮包袱** | max 末轮喂**全历史设备回显 + 逐轮错归因**，全部围绕 priority 叙事，进一步加固错框 | 无历史，无包袱 |

---

## 5. 机制结论：三重注意力劫持（全在输入侧，与能力无关）

1. **brief 用一个自信的错结论开路。** attributor 的 `fix_direction` 把"问题=priority"当既定事实内联在最靠前处。模型顺着被喂进来的轨道走，不会回头质疑"域名根本没配对"。这是可复现的注意力劫持——R1→R2→R3 三轮，错方向越锁越死（R1「抑制 cname 池」→ R2「加 priority」→ R3「priority 排序让 GA 选 p_main」），每一轮都在上一轮的错前提上做更精细的文章。
2. **系统提示把模型 prime 成"断言编译器"而非"配置诊断者"。** 6772 字断言机械 vs main 的"理解目标"。同一个问题，戴断言的镜看（该断言什么值、属哪层）和戴诊断的镜看（这配置到底通不通），落点不同。
3. **真正的意图被降级为"按引用"。** 脑图要自己 fs_read，而错方向是内联的、大声的、还有全历史加固。即便 R3 读了 manifest、还 dev_probe 了设备，也拼不过那段 priority 定向的响度。

**一句话**：R3 worker 不是没能力判断功能配置错误，是它的输入把注意力钉死在 attributor 喂进来的错方向上、并用断言机械的框架盖住了配置诊断的框架；main 因为拿到的是一句无污染、单焦点的诊断问题，能力才释放出来。max 思考放大的是"当前框架内的推理深度"，救不了"框架本身就错"。

---

## 6. 证据锚点

| 项 | 值 |
|---|---|
| R3-worker trace | `019f3bc3-a190-7213-aec4-e7e362466825`，08:50–08:54 UTC，首步 run `019f3bc5-5960-7ce2-a03e-4b9ae2da6ad3` |
| R3 系统提示 | 9273 字，顶层块 `inherited_rules/role/task(6772)/feature_id/xlsx/rules(688)/autoid`；断言×39 算法×11 层×13 |
| R3 brief | 10308 字；「定向重做」＝priority；内联前 2 轮全回显；脑图仅 `manifest_path` 按引用 |
| R3 工具调用 | fs_read×7（含 manifest）/ kb_footprint×6 / dev_probe×1 / compile_precedent×1 / compile_emit×1 |
| R3 思维链自证 | reasoning_content 逐字："fixes both round 1 (CNAME pool interfering) and round 2 (missing priority)" |
| R2-attr 产出 | trace `019f3bbf-25b5`，08:43–08:48 UTC；fix_direction＝「ga 下 priority 必填，加 priority」 |
| 每轮 dig 回显 | `dig @172.16.34.70 www.a.com` → `cname.a.com.`（非 IP），R1/R2 回显均在 |
| main trace | `019f3f5d-7b07-7932-9754-550617549a31`，2026-07-08 01:44 UTC；grep→footprint→dev_probe(show)→中根因 |
| 正确配置（设备实证，见 DIAG） | cname.a.com 必须 `sdns host name` 配成本地域名 + 在其上配服务/回退池；www.a.com 的池替不了它兜底 |

---

## 7. 对设计的启示（只记录，本轮不改代码）

- **修复的层不对**：三轮都在"上机后 attributor 归因 → 重派 worker"这条**最贵最晚**的环里打转，而错结论正是在这条环里被一轮轮加固的。正解是把"配置到底通不通"的判断挪到**产出后、上机前**（grade=grounding），别让错归因有机会开始循环。对上 DIAG/DESIGN 的结论。
- **brief 不该以 attributor 的结论开路当既定事实**：fix_direction 是"一种假设"，不是"已定的根因"。以它开路 = 把注意力劫持写进了输入契约。可考虑：把 fix_direction 降为"上一轮的假设（可能错）"，并把"先独立复核 dig 是否返回 IP / 解析链是否闭合"提为 worker/grade 的第一动作，强度高于任何被喂进来的方向。
- **意图不该只按引用**：真正的覆盖目标（脑图 step_intents）若只给路径，响度天然输给内联的错方向。至少把"这条 case 到底要验证什么行为"内联进 brief 最前，与错方向争夺注意力。
- **系统提示的框定要匹配任务**：末轮该做的是"诊断这配置为什么在设备上不生效"，但系统提示仍是"断言编译器"。诊断轮或许该切一套"配置诊断者"的框定（像 main 那样），而不是继续戴断言的镜。
- **dev_help 已就位**：`^`/`Failed` 那类**参数层**的错，worker 现在能当场追问设备拿到解释（本轮已交付）；但 035413 的主根因是**命令层/配置闭合**（dig 返回 cname.a.com 而非 IP），dev_help 不覆盖，仍需 grade 的引用图链接器 + 设备 grounding。两层两个修复家，别混。

---

## 附录：035413 不是孤例——全 batch 7/7 R1 失败同类（LangSmith/engine_report 取证）

> 数据源：`workspace/outputs/CNAME pool支持ipo算法_dongkl/engine_report.json` 的 `fail_evidence`（＝喂进各 worker LangSmith brief 的同一份 `device_context`）+ `attribution`。13 个用例，10 过 3 未过；R1 上机失败 7 个。逐个取"设备实际返回 vs 期望 + attributor 定向"。

### 7 个 R1 失败分三簇

**簇 A — 真·配置没实现意图，与 035413 同病（4 个）**：worker 对 SDNS 池交互抱错误心智模型，配置在设备上不产生意图要的行为，R1 设备回显一眼可见、一次 grounding dig/show 即可拦。

| case | 设备实际返回 vs 期望 | 根因（错模型） | 归因层/终态 |
|---|---|---|---|
| 035413 | dig→`cname.a.com.`，期望 IP `172.16.35.231` | cname.a.com 没配成本地域名 | G / escalated |
| 035373 | `disable p1` 后 cname.a.com **仍返回**，期望 not_found | 以为"disable 服务池抑制 cname 池"（实际独立池） | V / passed |
| 035493 | `show sdns host status`→`www.a.com UP`，期望 DOWN | host 挂了 cname 池→无健康检查→恒 UP | V / passed |
| 035570 | `disable s1` 后 host 仍 `UP`→返 cname，期望 DOWN | **与 035493 同一根因** | product_defect / terminal |

簇 A 内两处**归因不可靠**的实证：
- **035570 与 035493 是同一设备行为（host 挂 cname 池恒 UP），却被判成两个层**——035493 判 V（改断言/去关联，pass），035570 判 **product_defect**（terminal）。同症不同判。
- **035373 的"修法"是把断言从 not_found 改成 found 去迁就设备行为**——observe-then-assert 假验证收尾（项目红线），表面 pass 实为迁就设备、非真修。

**簇 B — 判了 product_defect 但从没上机复核（1 个）**：
- 035453：GA 对 cname 池优先级没排序（期望高优先级 cname1，设备返回 cname2），R1 就判产品缺陷 terminal。结合 035570 的误判，这个 product_defect 标签同样存疑——需 grounding 定性，不能盲信标签。

**簇 C — 断言/emit 结构问题，离线可拦（2 个）**：
- 044572：断言期望 `ga` 缺引号，设备输出 `"ga"`——结构 lint（引号对齐）可拦。
- 044605：step7 的 G 列空（captured_relation 未产出值）——emit 结构 lint（空 check_point）可拦。
- 这两个不是"配置没实现意图"，是断言/产出结构问题，**离线零设备就拦**。

### 关键共性（正面印证全文结论）

**7 个 R1 失败里，没有一个是"真需要烧多轮上机才能发现"的——全部能在 R1 产出后、第一次上机之前被便宜地拦下**：
- 4 个（簇 A）靠一次 grounding dig/show（配置没实现意图，设备一句话戳破）
- 2 个（簇 C）靠离线结构 lint（引号/空 check_point，零设备）
- 1 个（簇 B）靠 grounding 复核，而非盲信 product_defect 标签

**反向旁证**：越晚越贵的 attributor 层本身不可信——同一个 host-恒-UP 行为被判成 V 和 product_defect 两种（035493 vs 035570）、035373 用迁就断言收尾、035453/035570 的 product_defect 从未上机验证。035413 不是孤例，是**全 batch 的系统病**：错模型在产出前无人拦、错归因在产出后越锁越死。
