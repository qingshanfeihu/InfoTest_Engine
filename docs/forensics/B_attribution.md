# 取证单元 B — env_blocked 归因机械后校验 + F1 建议血统风险

> 阶段：只读取证（实证→理论→设计三段，零代码改动）。
> 主源：`workspace/outputs/dongkl/last_run.json`（每案 `device_context` 原始设备回显 + `_attribution` 判定）
> + F1 面板 `workspace/outputs/<autoid>/ask_panel.json` + attributor prompt `agents/compile-attributor.md`
> + 路由代码 `compile_engine_v8/{nodes,remedies}.py` + 归因工具 `tools/device/{fail_attribution,ask_panel}.py`。
> 覆盖：dongkl 三案 **777976 / 994986**（env_blocked 2/2 误判）+ **572708**（F1 血统，发现8）。
>
> **本报告三类标注严格区分**：〖数据事实〗＝盘上行级铁证；〖我的判断〗＝据证据的推断；
> 〖给用户的问题〗＝设计张力项，我不拍板、附两方论据。

---

## 1. 实证根因（行级铁证）

### 1.1 单元 B — env_blocked 两案：归因器看表面症状、不做内部一致性检验

#### 994986 —「标签 E vs 自身推理 V」自相矛盾（铁证清晰）

〖数据事实〗`last_run.json` 该案 `_attribution`：

```
layer:        "E"
disposition:  "env_blocked"
evidence:     "Command 'show' not found, but can be installed with:"
fix_direction:「验证步骤通过 console 执行 show sdns host pool，但 console 落在 Linux 主机
              （root@console:/home/test#），非设备 CLI，导致 show 命令不可用。修复方向：将验证命令
              改为通过设备 SSH 会话（172.16.35.70）执行 show sdns host pool，与同批通过用例
              （如 203031754287572672）一致。需在编译层修正 case 的验证步骤通道，或确认 console
              端口正确连接到设备。」
```

〖数据事实〗device_context 铁证（同案原文子串，逐字）：

```
172.16.35.70 - sends command in config: sdns host pool www.test-a.com pool_a   ← 配置命令正确发到设备
begin to login console / success to login console / switch to root for console
console executes command: show sdns host pool www.test-a.com
#### Fail Num 1: fail to find pool_a in:
Command 'show' not found, but can be installed with:                           ← bash 报错，不是设备
apt install mailutils-mh  # version 1:3.7-2.1, or ...
root@console:/home/test#                                                       ← Linux shell 提示符
```

〖数据事实〗同案 device_context 里 `APV(config)#` 设备提示符出现 3 次（配置会话），
`root@console:/home/test#` Linux 提示符出现 2 次（验证步）——**两种提示符共存且形态截然可分**。

〖我的判断〗**标签与自身推理自相矛盾**：`_attribution.layer=E/disposition=env_blocked`（＝真环境、
呈报人、引擎无修法权），但同一条 `fix_direction` **首句就是 V 层 reflow 指令**（「将验证命令改为
通过设备 SSH 执行」「需在编译层修正 case 的验证步骤通道」），**末句才补 E 读法**（「或确认 console
端口正确连接到设备」）。归因器自己都推出了「通道选错、该 reflow」，却把 disposition 落成了
env_blocked——**它读到了矛盾，但没有让矛盾改变 disposition 路由**。

〖数据事实〗**worker 思维链交叉印证**（`trace_dumps/994986_r1_320b482b.txt`，compile-worker r1）——
误派根因是**框架 host 词表陷阱**，不是 worker 随意选错：worker 先写 `host="device"`，被 emit 机械门
拒绝：`step[1] F='device' is not a valid method of the E=test_env object (valid: clientc, clientd,
cliente, console, routera, routerb, server213, server231, server232)`。worker 的 `reasoning_content`
逐字：「The host in OBSERVE_ASSERT should be "console" (**the device**) not "device". Let me check the
valid hosts: … So I should use "console" for device commands.」→ 改 `host="console"`（emit payload
逐字：`"cmd":"show sdns host pool www.test-a.com","host":"console","kind":"OBSERVE_ASSERT"`）。

〖我的判断〗**这把 §3.2 的 V/E 分歧从「worker 粗心」精化成「框架词表缺口」**：`test_env` 的合法
host 方法里**没有一个清楚叫「设备 SSH / device CLI」的**——配置命令走的是另一套通道（config-mode
到 172.16.35.70，非 host 方法），而 OBSERVE_ASSERT 验证只能从 {clientc…server232} 里挑；worker 合理
地把 `console` 猜成设备，但 `console` 落在 Linux 主机。**V 读法**（该 reflow 换正确验证机制）仍成立；
**E 读法**（用户已选）也有正当内核——环境（host 命名空间）确实没给 worker 需要的通道。信号②正确检出
了「show 打到错主机」，但正解是「reflow + worker 自查正确机制」，不是引擎判 V/E（引擎无权，且不得
注入具体机制——红线）。

#### 777976 — 同卷 Hit≥1 自证伪「环境不通」（较微妙，但机械上更硬）

〖数据事实〗`_attribution`：

```
layer:        "E"
disposition:  "env_blocked"
evidence:     "2026-07-15 15:06:47     Hit:                   0"
fix_direction:「routerb dig produced no output; pool p2 Hit=0 means no traffic reached it.
              Environment/reachability failure on second DNS request from routerb. Case config
              is correct (rr with 3 pools). Rerun batch; if persistent check routerb to
              172.16.34.70 network path.」
```

〖数据事实〗同案 causality/detail_tail 的框架自有计数器（逐字）：

```
################# The failed check point num:   2   ####
#### Fail Num 1: fail to find: \b172\.16\.35\.231\b
#### Fail Num 2: fail to find: Hit:\s*1
################# The passed check point num:   2   ####          ← 通过数 = 2，不是 0
#### Success Num 1: successed to find: \b172\.16\.35\.213\b       ← 另一成员命中了
#### Success Num 2: successed to find: Hit:\s*1                   ← 确有 Hit:1
```

〖数据事实〗机械核对（脚本解析 last_run）：777976 `passed_check_point_num=2`；994986 `passed_check_point_num=0`。

〖我的判断〗归因结论「routerb dig produced no output / no traffic reached / environment failure」
被**同卷两个通过 check point 直接自证伪**：框架在该案真实设备输出上成功匹配了 `172.16.35.213` 和
`Hit:\s*1` 两个断言——**DNS 流量确实到达、且某成员确实命中**。归因器只读了失败池 p2 的
`Hit: 0`（它抄进 evidence 的那一行），**把单个池的 Hit:0 泛化成了整案「环境不通」，无视同案 p1
成员 213 已 Hit:1**。真根因是 RR 分布采样敏感（3 记录池、成员 231 这一轮没轮到），属**欠定
（h-in-λ）**，是单元 A 的领域，**不是真环境**。

〖数据事实〗**worker 思维链交叉印证**（`trace_dumps/777976_r1_58a6b998.txt`）——过定断言是 worker
自己写的、且继承自 precedent。worker `reasoning_content` 逐字：「if I check p2's stats, it should
also show Hit:\s+1 (from the second dig).」「Looking at the precedent, after the second dig, they
check p2's stats: `Hit:\s+1`. **So both p1 and p2 have Hit:\s+1 after two queries.**」emit 产出
（worker 复盘逐字）：Row34 `found 172.16.35.213`、Row36 `found Hit:\s*1`、Row38 `found
172.16.35.231`、Row40 `found Hit:\s*1`——**对两个成员各断言一次 `Hit:\s*1`**。

〖我的判断〗worker trace 与同卷 passed_cp≥1 **双重否证 env_blocked**：失败不是环境，是 worker 把
「每个成员恰好命中一次」这个**依赖 RR 轮转态的 per-member 计数**写死成断言（routerb 第二次 dig 没落
到 p2/231，231 Hit=0）。且这条过定形态**继承自 precedent 的 `Hit:\s+1`**——与单元 A 的 flaky 写回
投毒同源（precedent 用命中计数当断言）。**这案根本不该进 env_blocked，该走单元 A 的 h-不变式改写**。

〖我的判断〗**777976 与 994986 不是同一种误判**——这点对设计很关键：
- **777976**：机械信号（同卷 passed_cp≥1）**干净地否证**了「环境不通」。真层是 V/欠定（RR 采样）。
  **不是层定义分歧，是清楚的误归**。
- **994986**：机械信号（Linux 提示符）检出「show 打到了错主机」，但**这算 V（worker 选错通道，该
  reflow）还是 E（测试床 console 口没接到设备，接线问题）本身是层定义分歧**——`fix_direction`
  末句两读都通。

### 1.2 误判的真实后果：env_blocked → 空修法队列 → 被移出 reflow 环

〖数据事实〗`compile_engine_v8/remedies.py:derive_queue` line 83 注释：
「env_blocked / capped / 无归因：队列空——修法在权限外或待归因/待人裁」。
`nodes.py` line 1378-1379：`if att.get("disposition")=="env_blocked": sh.signal("escalated", aid, reason="env_blocked")`。

〖我的判断〗disposition=env_blocked 有**真实路由后果**：修法队列被清空、案子被 `escalated` 移出
自愈重编环，当作「环境问题在引擎权限外」泊住、交用户。所以**一个被误标 env_blocked 的 V 层案，
永远不会被 reflow 修好**——这正是 §18.15-B 要堵的洞：错误的 disposition 不是记个标签，是把案子
从修复通道里摘出去。

### 1.3 归因器为何漏掉：prompt 只查跨案一致性，不查同案内一致性

〖数据事实〗`agents/compile-attributor.md`：
- line 42-45：「Cross-case consistency before any systemic claim … a 'whole batch broken' story
  must explain why the passing cases pass」——教的是**跨案**一致性。
- line 49-50：「E = reachability/environment (a dig with a responding `SERVER:` line is NOT
  unreachable)」——**有一句同案内一致性提示，但只覆盖 dig-SERVER 一种形态**，且只是 prose（C 层
  信赖），未强制；不覆盖「同案 Hit≥1」「Linux 提示符」。

〖我的判断〗777976 的矛盾是**同案内**（同案有通过 check point），归因器按 prompt 只做了跨案检查、
没检查「env_blocked 是否与本案自己的通过 check point 相容」，于是漏过。§18.15-B 的机械后校验正好补
这个位。

### 1.4 单元 E — F1 面板血统偏向（572708，发现8）

〖数据事实〗572708 `_attribution`：`layer=V / disposition=expectation_suspect`，
`fix_direction` 结尾：「…verified_203031754287572708.xlsx 前轮使用 found 断言（断言删除后条目仍在）
已 PASS。当前断言期望 not_found 与设备真实行为矛盾。需用户裁决：若设备行为正确（no 不移除条目），
断言应改为 found；若 manual 删除语义正确，该行为为设备缺陷。」

〖数据事实〗**实际呈给用户的面板** `workspace/outputs/203031754287572708/ask_panel.json`（逐字）：

```
conflict_shape: "manual_vs_device"
sides[0] (device): "… no sdns host method autotest1.com"          （设备侧：发了删除命令）
sides[1] (manual): "该命令用于删除指定域名的SDNS域名算法。"
                   source_ref: knowledge/data/markdown/product/manual_10.5/cli_10.5_Chapter20.md:426
retrieval_receipt[1]: "kb_footprint … 'no 后 show 回显 method 仍在'"  outcome: hit_conflicting
hypothesis:「…此行为在本批至少两个同签名用例及 verified 前轮中反复确认。manual 声称该命令"删除"
            域名算法，但设备表现为 no-op。建议将断言改为 found（与 verified 前轮一致），或确认为
            设备缺陷。」
ask:「no sdns host method 命令在设备上不生效（条目仍在），verified 前轮用 found 断言已通过。
     应将断言改为 found（接受设备现状），还是判定为设备缺陷？」
```

〖数据事实〗device 侧证据：`no sdns host method autotest1.com` 执行后，`show sdns host method` 仍显示
`sdns host method "autotest1.com" "rr"`（条目未移除，no-op）；断言期望 `not_found autotest1.com` 因此
fail。manual（人源，`cli_10.5_Chapter20.md:426`）明写该命令「用于删除」。

〖我的判断〗**面板把机生血统当成了偏向一侧的理由，且把第三源极性倒置了**：
- device no-op 行为**本身**由设备证据充分坐实（同批 2 案 + 复现），这没争议。
- 争议在**期望该取哪极**：`found`（接受 no-op）还是 `not_found`（manual 删除意图→若设备该删而没删＝
  缺陷）。面板 `hypothesis`/`ask` 都把「**改 found**」列首、并用「**与 verified 前轮一致**」作理由。
- 但 attributor 自己的 prompt（line 66-68）逻辑是「third-source 显示设备行为是**文档常态** →
  expectation_suspect（改期望）」。**这里第三源（manual）恰恰说设备行为不是常态**（该删），本应偏
  向「设备缺陷」候选。**是机生 verified 血统（同 autoid 族、`found` 前轮 PASS）把极性从「疑似缺陷」
  拉向了「接受设备现状」**——而那条 verified 前轮的 `found` 恰是 observe-then-assert 产物：它 PASS
  只证明「设备是 no-op」（已知），**不证明 found 期望是对的**（那正是争议本身）。援引它＝循环论证。

〖数据事实〗**worker 思维链交叉印证血统注入点在归因层、非编写层**（`trace_dumps/572708_r1_18df7961.txt`）——
round-1 worker 写的是**manual-忠实的 `not_found`**，逐字：「**Test point**: 验证 `no sdns host method
<host_name>` 能成功删除…删除后 `show sdns host method` 不再显示该配置」「**Falsifying observation**:
After `no sdns host method autotest1.com`, `show sdns host method` still displays autotest1.com's
method entry」「Verifies autotest1.com's method is gone (**not_found**)」。worker **跟的是脑图删除意图
（「删除成功」）、没锚 verified 前轮**。

〖我的判断〗**F1 血统拉力发生在 attributor/裁决层，不是 worker 编写层**：worker 的 `not_found` 是
**正确的 manual-忠实断言**，它上机 fail 恰恰是因为设备 no-op（疑似缺陷的正信号）。是**归因器的 F1 面板**
把历史机生 `found` 前轮抬出来、要抛弃 worker 那条正确断言、拉向「接受设备现状」。这比「排序偏差」更重：
**机生 observe-then-assert 前轮被检索放大，去覆盖一条人源(manual)-忠实的正确断言**——(45) 自指投毒的
最纯形态（人源采信先验本应 > 机生，这里被倒置）。

---

## 2. §18.15-B 设计裁决（对抗性）

### 2.1 诊断方向：**正确**（B 是真实且未实现的空白）

〖我的判断〗§18.15-B 说「(40) env_blocked 出口缺内部一致性机械后校验，同型 §18.14 s₀ 复核」——**站得住**：
- `tools/device/fail_attribution.py:submit_attribution` 对 `env_blocked` **无任何机械反证门**：只要
  evidence 是 device_context 子串就无条件落盘（layer/disposition 只做枚举校验）。归因器判 env_blocked
  即被采信、清空修法队列、escalate。
- 已有的机械可达性检查（`batch_tools._probe_device_reachable` + `test_device_reachability.py`）是
  **批级主动探针**：ping 设备，不可达→全批 fail 降 `broken`、禁 s₀ 配对。**它抓不到 B 的场景**——
  777976/994986 时设备是**活的**（整批跑通、他案 pass），是归因器凭单案症状误标。B 填的是
  「**单案 env_blocked 标签对该案自身 device_context 的内部一致性**」，与批级探针**机制不同、可组合**。
- 全仓无第二处 env_blocked 后校验（`env_blocked` 在 nodes.py 只现于 escalate/user-stop/user-override
  三处）。B 确为「设计中」、未实现。

### 2.2 机械信号在真实数据上判得准吗？——两信号**都可靠地做「触发复核」，但都不足以「自动定 V」**

〖数据事实〗对全批 32 案扫两信号，env_blocked 门内零误伤：
- 信号 ①（同卷 `The passed check point num: N`，N≥1）：777976 命中（passed=2），994986 不命中（passed=0）。
- 信号 ②（非设备主机提示符 `root@[\w.-]+:/[^#]*#` / bash `Command '…' not found, but can be installed`）：
  994986 命中，777976 不命中。
- 两信号在 2 个 env_blocked 案上**互补且各自精确命中一案**，对其余 30 案无一在 env_blocked 门内误触。

〖我的判断〗**信号必须精化，别用裸文本 grep**：
- 信号 ① **不能用裸 `Hit:\s*[1-9]` grep**——`Hit:\s*1` 本身是断言 regex 的字面文本，会同时出现在
  `fail to find Hit:\s*1` 和 `Success … Hit:\s*1` 两种行里（777976 实测两种都在）。**可靠的结构化事实
  是框架自有计数器 `The passed check point num: N`**：N≥1 ⟺ 框架在真实设备输出上匹配到了断言 ⟺
  设备可达、命令有回显。这比解析 Hit 更硬（协议级、语义无关）。
- 信号 ② 是**结构化提示符**：`root@host:/path#` 是 shell 自己的提示符格式、`Command 'X' not found,
  but can be installed with` 是 bash 自己的 stderr 格式——**协议级形态，同 `^` 设备语法拒绝标记
  一样上下文无关**，不是领域关键字白名单。**红线守住的关键**：信号要键在**提示符/bash 报错形态**
  上，**绝不键在具体命令词 `show` 上**（那才是会误杀金标准的关键字白名单）。

〖我的判断〗**但两信号都只够触发「复核」，不够「自动定 V」**（这是我对设计的最重要对抗性质疑）：
- 信号 ① 的 passed_cp≥1 只证明「环境非全域宕」，**不证明失败那一项的 Hit:0 是非环境性的**。
  反例：p1 可达（passed_cp≥1）但 p2 成员在不可达子网（该项真环境）——信号会触发，但该 fail 可能
  真是环境。（777976 恰好不是此形，231 与 213 同在 172.16.35.x，但信号本身分辨不了。）
- 信号 ② 检出「show 打到错主机」，但那是 V（worker 选错通道）还是 E（床 console 没接到设备）
  **本就是层定义分歧**（见 §1.1）。
- 结论：**机械矛盾＝「env_blocked 内部不自洽、该复核」的可靠信号；≠「此案是 V」的判决**。
  这直接指向 §3 的核心设计问题。

### 2.3 与 THEORY 的映射：**对，但设计文案「转 V 深归因」有歧义**

〖我的判断〗§18.15-B 引 (40) 处置分类学 + §18.14 同型——映射正确（见 §4）。**但文案有隐患**：
「矛盾则不采信 env_blocked、**转 V 深归因**」——「转 V」被协调者读作「自动降级 env_blocked→V」，
但也能读作「重跑一次聚焦 V 的归因」。这个歧义本身是设计缺陷，必须在定稿里消掉（见 §3.1）。

### 2.4 红线 11（门配 override 通道）：**已成对，机械门必须挂在其上、不得绕过**

〖数据事实〗env_blocked disposition 已与 escalate→用户裁决通道**成对**：`nodes.py` line 1378 env_blocked
→ escalated；line 2051-2069 用户可裁 `stop`（确认 env_blocked，E round 99）/ `retry`（override→
rerun_isolated，「user overrode env_blocked」）/ `defect`（product_defect）。

〖我的判断〗这是 red-line-11 的正例：env_blocked 早有 override 出口。**§18.15-B 的机械门必须组合进
这条既有链**（把矛盾喂进 escalate 面板、让用户 override 决策更明），**不能在用户看到之前自动改判**
——否则会破坏已存在的用户裁决权（见 §3.1）。

---

## 3. 待讨论问题（核心）+ 修法方向

### 3.1 〖给用户的问题 A〗机械检出矛盾后：**自动降级 env_blocked→V**，还是**标记交用户复核**？

**背景张力**：§18.15-B 原文提「矛盾则不采信 env_blocked、转 V 深归因」。但**用户在 dongkl 里已对
777976 和 994986 都选了「确认环境问题」(E)**。自动降级会**覆盖用户已经做出的 E 选择**。

> ⚠️ 数据边界（如实）：盘上 dongkl 输出**无 engine_ledger.json**，我无法从磁盘独立复核用户的最终
> 裁决，仅见 last_run 的 round-1 归因；「用户已选 E」采信协调者陈述。这也是为何我倾向「标记复核」
> 而非「自动改判」——引擎不该在无法回看用户账的地方替用户翻案。

| | **方案①：自动降级 env_blocked→V + 直接 reflow** | **方案②：机械检出矛盾→标记，喂进既有 escalate 面板交用户复核** |
|---|---|---|
| 论据（正） | 省一轮用户交互；777976 这类硬否证（passed_cp≥1）几乎确定是误归；把误归案直接拉回修复环 | 不覆盖用户 E 选择；矛盾只是「该复核」信号非「是 V」判决（§2.2）；994986 的 V/E 本是层定义分歧、引擎无权替判；组合进 red-line-11 既有 override 链、零新终态 |
| 论据（反） | 信号不足以定 V（§2.2）：真·部分环境失败会被误 reflow→烧轮、可能 frozen；994986 自动判 V 会抹掉合法的 E 读法、违用户已选；违 §2.6.6「冲突本身不构成判决」 | 多一次用户交互（但 env_blocked 本来就 escalate，边际成本≈把矛盾附进已有面板） |
| 我的倾向 | ✗ | ✓（理由见 §4：§2.6.6 对称怀疑 + 信号只证「非全域宕」不证「非环境」） |

〖我的倾向〗**方案②**。机械后校验的产物应是「**在 env_blocked 的 escalate 面板里，把机械矛盾作为
一条结构化证据呈给用户**」（「归因判 env_blocked，但同案有 2 个通过 check point / 回显含 Linux 提示符
`root@…#`，与『环境不通』矛盾——请复核」），让用户带着矛盾做 E-vs-V 裁决，而不是替他翻案。
**工程形态**：仿 `expectation_suspect` 的既有范式——检出矛盾时，要求归因器要么改判非 env_blocked 层、
要么落一条把矛盾写进 sides 的复核面板（同 `submit_ask_panel` 机制，保证案子不活锁、有合法出口）。

〖给用户的问题〗**你要引擎在检出机械矛盾时自动改判 V 并直接重编（省交互、但可能覆盖你的 E 选择、
且信号不足以定 V），还是把矛盾标出来、并进现有的环境确认面板交你复核（多一条证据、你仍拍板）？**

### 3.2 〖给用户的问题 B〗777976 / 994986 的层定义分歧：console 打到 Linux 主机算 V 还是 E？

**这是层定义问题，不是谁对谁错。** 张力：worker 把 `show sdns` 派到了 console（落在 Linux 主机
`root@console:/home/test#`）而非设备 SSH。**worker trace 已定性根因＝框架 host 词表陷阱**（§1.1）：
worker 先试 `host="device"` 被拒、框架列出合法 host `{clientc…console…server232}`（无「device SSH」项），
worker 把 `console` 猜成设备。

- **V 读法**（我/ANALYSIS）：验证机制是编译层（worker）决策，换成正确的 device-show 机制即修复＝reflow。
- **E 读法**（用户已选）：`test_env` host 命名空间没给出「在被测设备上跑 show」的干净通道＝环境/框架
  接口缺口，编译层绕不过去。
- 994986 `fix_direction` 末句「或确认 console 端口正确连接到设备」**两读都通**；worker trace 显示这
  **不是粗心、是词表诱导**，两读都更有据。

〖我的判断〗**777976 与 994986 该分开处理**：
- 777976 机械上更硬——passed_cp≥1 直接否证「环境不通」，真层是 V/欠定（RR 采样，单元 A）。这案
  「E」几乎可确定是误归。
- 994986 是真层定义分歧，V/E 都有正当性，应交用户（且用户已选 E）。

〖给用户的问题〗**「验证命令落到了 Linux 主机而非设备 CLI」这类，你希望默认归 V（worker 通道错、
reflow 换成设备 SSH 验证）还是 E（床 console 接线、呈报）？** 若归 V，引擎可自动 reflow 修复；若归 E，
保持呈报。（我倾向：**默认按 V 呈报候选、但面板同时给出 E 读法交你确认**，不预判。）

### 3.3 〖给用户的问题 C〗F1 血统：面板该不该预设默认建议？机生 verified 前轮该不该作采信理由？

**背景**：572708 面板 `hypothesis`/`ask` 把「改 found」列首、用「与 verified 前轮一致」作理由，
而 manual（人源）说「删除」——**机生血统把第三源极性倒置了**（§1.4）。这直接违 (45) 判例血统
（人源采信先验 > 机生）、(45b) 防自指（判例检索结果不得被自产血统垄断）、§2.6.6 对称怀疑。

〖我的判断〗**协调者提的正解「F1 不预设默认、纯呈报双源交裁决」方向正确，但要处理与 (46) 的张力**：
- (46) 问询三元组律要求题面含「已推导的最优替代」——面板必须有 worker 的理解，不能空手问。
- 二者可调和：F1/expectation_suspect 的「最优替代」**恰恰是「引擎无权替判此意图分歧」**——(46)
  允许「如实声明无替代及原因」。所以正解不是「删掉 hypothesis」，而是「**hypothesis 呈报意图分歧
  本身、对称给出 device 行为与 manual 意图两原文，不用机生血统作偏向理由**」。

〖修法方向（我倾向，但具体落点＝问题 C）〗
- **A（prompt 层，`compile-attributor.md`）**：F1 段补——形成 hypothesis 时，同 autoid 族的机生
  verified 卷**不是**期望极性的独立佐证（它只证设备行为可复现、不证期望对错，援引＝自指），须标为
  uncertain 级；device 行为与人源 manual 须对称呈报，第三源极性（manual 说该删）不得被机生血统盖过。
- **B（机械/schema 层，`ask_panel.py`）**：可选加血统标注——`sides`/`retrieval_receipt` 标 source
  血统（human-source / machine-generated-selffamily），渲染层对机生同族条目缀「（机生·未审计·非独立
  佐证）」，让血统在面板上机械可见（而非埋在 free text 里）。

〖给用户的问题〗**F1 面板的血统防护走哪条？**（a）只改 attributor prompt（软护栏、成本低、但靠
LLM 自觉）；（b）加 schema 血统标注 + 渲染层机械缀标（硬护栏、机生血统可见、但要动 ask_panel schema）；
（c）两者都做。我倾向 (c)：prompt 立即降偏向 + schema 让「这条是机生同族」在题面上一眼可见。

---

## 4. 理论对账

| 结论 | THEORY 锚 | 一致 / 需更新 |
|---|---|---|
| env_blocked 出口缺内部一致性门 | THEORY_k (40) §2.12.1「真环境→呈报人」类——出口只在案**真是**真环境时才对；无门验证 env_blocked 标签正确性，则 V/欠定案会被误走呈报出口 | 一致（B 正是补这个门） |
| 机械矛盾＝复核信号≠判决，应交裁决 | THEORY_k §2.6.6 对称怀疑「实然与应然冲突时，冲突本身不构成对任一侧的判决…唯一合法出口是矛盾即问边」 | 一致（直接支持 §3.1 方案②「标记复核」而非「自动降级」） |
| 777976 真层＝欠定(h-in-λ)非真环境 | THEORY_k (40)「欠定(R 依赖 h-in-λ)→R 边缘化改写」；S §0.5 h-不变式（单元 A） | 一致（777976 该走单元 A 的 h-不变式 emit 门，不是 env_blocked） |
| B 同型 §18.14 s₀ 复核 | §18.14「机械化理论时丢对象链合取」——s₀ 复核＝机械扫 device_context 结构化事实 | 一致，**但时序相反需在文档点明**：§18.14 s₀ 复核是**前筛短路**（`nodes.py:1230` 机械证据足→不派 LLM）；B 是**后校验**（LLM 判 env_blocked **后**机械扫反证）。「同型」指「机械读结构化事实」，非「同时序」 |
| F1 面板血统偏向违防自指 | THEORY_k §2.9.4 (45)「人源采信先验>机生；未经窗口对账的 verified 降 uncertain」、(45b)「判例检索不得被自产血统垄断」、§2.6.6 对称怀疑 | 一致（572708 是 (45)/(45b) 的又一实弹：机生 `found` 前轮把 manual 极性盖过） |
| F1 不预设默认 与 (46) 三元组律 | THEORY_k §2.9.5 (46)「题面必须含已推导的最优替代 **或如实声明无替代及原因**」 | 一致（F1 的「最优替代」＝「引擎无权替判、呈双源」，属 (46) 允许的「如实声明无替代」——**建议在 (46) 或 §2.12.1 第七类补一句：expectation_suspect 的第三分量以『呈报双源、不预设默认』满足，不得以机生血统充当替代倾向**） |

〖理论更新指向（不改，只指）〗
1. **§18.15-B 文案**：把「转 V 深归因」改为无歧义表述——「检出矛盾→不静默采信 env_blocked→
   把矛盾并入既有 escalate 面板交用户复核（非自动改判 V）」。
2. **THEORY_k (46) 或 §2.12.1 第七类**：补 expectation_suspect 的「最优替代」满足方式（呈双源、
   禁机生血统充当默认倾向），把 §1.4 教训入文。
3. **§18.14 同型说明**：点明 B 是**后校验**、s₀ 是**前筛**，同「机械读结构化事实」不同时序。

---

## 5. 回归锚建议（供实现阶段）

〖机读断言形态〗（先不实现，供 §6/§7 用）：

**单元 B（env_blocked 内部一致性后校验）**——放 `tests/ist_core/compile_engine_v8/test_env_blocked_recheck.py`：

1. **信号①正例**：构造 777976 形态 fixture（`_attribution.disposition="env_blocked"` +
   device_context 含 `The passed check point num: 2`）→ 断言后校验**检出矛盾**（产出复核标记 /
   进 escalate 面板 sides），**不静默采信 env_blocked**。
2. **信号②正例**：994986 形态（env_blocked + device_context 含 `root@[\w.-]+:/[^#]*#` 或
   `Command '…' not found, but can be installed`）→ 断言检出矛盾。
3. **负例（防误伤，关键）**：真·env_blocked fixture（`passed_check_point_num=0` ∧ 无 Linux 提示符
   ∧ dig 无 SERVER: 响应行）→ 断言后校验**不触发**（无假阳）。
4. **信号纯度门**：断言实现解析 `The passed check point num:\s*(\d+)` 计数器与提示符/ bash 报错
   **形态正则**，**不含**任何具体命令词（`show`/`sdns`/…）白名单——防退化成强字典（红线，
   `[[compile-judgment-structural-not-strongdict]]`）。
5. **不覆盖用户裁决门（red-line-11）**：断言检出矛盾时案子仍走既有 escalate→用户 override 链
   （retry/stop/defect 三出口不变），后校验只**加证据**、不**改终态**、不绕过用户。

**单元 E（F1 血统）**——扩 `tests/ist_core/compile_engine_v8/test_ask_panel.py`：

6. 若采纳 schema 血统标注：断言 `source_ref` 指向引擎 verified 同族卷的 `sides`/`receipt` 条目被标
   `machine-generated`，渲染缀「机生·未审计·非独立佐证」。
7. 若仅 prompt 层：为 572708 形态留一条 prompt 结构门 fixture（`agents/` prompt 结构测试）——断言
   F1 段含「机生同族 verified 非期望极性独立佐证」纪律句（弱锚，靠 prompt 结构门 `test_prompt_structure.py`）。

---

## 附：数据边界与未决点（如实）

- 〖数据边界〗dongkl 输出目录**无 engine_ledger.json**（只有 last_run.json + facts.jsonl，后者是
  grade_extract 事实、非引擎台账）。故**用户对 777976/994986 的最终裁决无法从盘上独立复核**，
  「用户已选 E」采信协调者陈述。777/994 的 `_attribution` 均为 round-1 归因器判定。
- 〖已交叉印证，2026-07-15 补〗**worker 思维链 trace 已落盘并核对**（`<SCRATCH>/trace_dumps/{777976_r1,
  994986_r1,572708_r1}.txt`，compile-worker 轨迹）——三案的编写侧推理均已行级核实（见 §1.1/§1.4 的
  worker trace 证据块），**强化而非推翻**了原结论：994986＝框架 host 词表陷阱、777976＝worker 显式
  过定 RR 双成员 Hit（继承 precedent）、572708＝worker 写的是 manual-忠实 not_found（血统拉力在归因层）。
- 〖仍未及〗**无独立 compile-attributor 轨迹**（归因孔的 LLM 依据只在 last_run._attribution 或引擎图
  trace 的归因观测步）。故「归因器为何只读 p2 Hit:0（偏读）/ F1 面板为何抬 verified 血统」这两条**归因
  侧**推理链，本报告从 `_attribution.evidence`（恰抄了 `Hit: 0` 那行）+ `fix_direction` + ask_panel.json
  的 hypothesis 措辞反推，属〖我的判断〗；worker trace 只能印证「编写侧写对了/写错了什么」，印证不到
  「归因侧怎么想的」。实现阶段若要把归因侧坐实，需挖引擎图 trace 的归因观测步（本阶段不碰 live langfuse）。
- 〖交叉引用〗777976 的真层归属（RR 采样 / h-in-λ）属**单元 A**（h-不变式 emit 门）领域——B 的后校验
  只负责「否证 env_blocked、交出去」，具体改成 h-不变式断言由单元 A 承接。两单元在 777976 上接力。

STATUS: done
