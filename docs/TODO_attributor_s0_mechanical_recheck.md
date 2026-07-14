# 待修:attributor 的 s₀ 判定未过 S1 机械复核(run24 暴露,aha 覆盖缺口)

> 发现 2026-07-15 run24:655173 被 attributor(LLM fork)判 h_s0→走 bed 床治理呈报,
> 但机械 `_s0_pair` 对它返回 `polluters=[]`(S1 正确排除固定基础设施 IP)。真问题是
> **dig 打 IPv6 `@3ffc::70` 而断言要 IPv4 172.16.35.231**(配置问题),被 s₀ 假阳
> 误导到床面板,而非 V 层深归因修配置。这是 §18.14 S1 的覆盖缺口——**S1 只补了
> 机械 `_s0_pair` 的脏态合取,attributor 的 LLM s₀ 判定还是过程近似**(看到"154 配
> listener 没清理"就判污染,丢了"172.16.34.70 是合法共用基础设施 IP"的对象判断)。

## 根因(定位到行)

- attributor(LLM fork)独立判 `h_position=h_s0 disp=rerun_isolated`(读证据认为前案
  没清理→污染),**不经 S1 的固定基础设施 IP 过滤**。
- `attribute` 节点 `nodes.py:1375` 落 attribution 事实时**直接继承** attributor 的
  `h_position`(`str(att.get("h_position") or "")`)——**无机械复核**。
- `diagnose`/`bed_treatment_waiting` 据 diagnosis 的 h_s0 + disp∈{rerun_isolated,
  transient} → bed 呈报。机械 `_s0_pair`(S1 生效,polluters=[])与 attributor 判定
  **冲突**,但继承路径以 attributor 为准。

## 修法(机械配对为准,红线:判断用结构化事实非 LLM 凭空造 s₀)

`attribute` 收账(1368-1377)或 `diagnose` 复核:attributor 判 `h_s0` 时,用机械
`_s0_pair`(该案,当前组成)复核——**若机械 polluters=[](S1 判无污染者)且非
self_persist → 降级**:h_position 落非 s₀(如 h_pi/深归因标记),不进 bed 呈报,走
V 层深归因。即"LLM 归因不能凭空造 s₀——无机械污染者的 s₀ 不成立"。

**这是 aha 的直接延伸**:§18.14 说"实现系统性丢对象链合取",attributor 层就是又
一处(它判 s₀ 用过程近似"没清理",丢了固定基础设施 IP 的对象判断)。S1 该从"补机械
_s0_pair"扩展到"机械复核 attributor 的 s₀"。

## 验证锚

改后 run:655173 型(attributor 判 s₀ 但机械无 polluter)→ 走 V 层深归因(修 dig
IPv6/断言配置),不进 bed 床面板;真 s₀(机械有 polluter)仍走 bed。回归:构造
attributor 判 h_s0 + 机械 polluters=[] → diagnosis 降级非 s₀;+ 机械有 polluter →
保留 h_s0。

## 附:run24 其他验收(供参考)

- 667986(run23 s₀ 假阳受害者)这轮 **pass**——对象链意识让满配断言写对,源头没 fail;
- 对象链自查生效:668000 查 show startup、668044 点明"证伪观测对象=重启后加载的运行
  配置"、668059 绕过不存在命令、655233 不猜不通 IP;
- 655203 正确判 h_pi(框架 session split race,附件 IPv6≠卷面 IPv4);
- 668015 半成品(有对象敏感自查但方案含 clear config all,被 destructive 门+用户裁决
  兜住)——B1 登记的 LLM 判断残余边界。
