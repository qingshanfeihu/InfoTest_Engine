# D31 裁决注·zhaiyq 对账门 report_mismatch（checker-bug，真值 42）

> 2026-07-18 · Test-Eng 取证 + leader 亲核 + Py-Eng 复现。对账门工作+双路漂移双实证，存档不随重渲丢。

## 现象
zhaiyq closing（round-11、4h37m/¥224.85）REPORT_MISMATCH.json 自捕：报告头行「53/42 通过」vs 事实重算「53/40」，尾号 516389/533097 判「通过整卷复验但事实台账不支撑」。

## 裁决：纯 checker-bug、真值=42（不移卷、不重跑、对外 42/53）
两处行级 bug（leader 亲核 + Py-Eng 复现）：
- `report_gate.py:32` 无条件 any-escalated 丢——曾 escalated 的案被无条件排除出「通过」重算，**未镜像 views 的 run18 authored 解除语义**。
- `views.py _is_escalated` run18 authored 解除逻辑——516389/533097 是 **escalated@0 被 authored@1/@5 解除的真 pass**，对账器 recount 谓词漏了这个解除、错把「曾 escalated」当「pass 不支撑」。
- **是纯 checker-bug、非账链缺口/第三出口**（关键澄清）：**账链完整**（authored 事件在账、produced 在账），bug 在 recount 谓词漏解除、不在事件写入。比账链缺口更干净。
- **全量验证零误减**：旧 checker 算 40、新 checker 算 42、report claimed 42——修后三者一致。

## 支撑证据（Test-Eng 行级）
- 516389：全 5 条 verdict 均 (delivery,pass)、artifact 恒定 `205271757988516389:1784367957.84`（对照案同样卷只产一次多轮复验，恒定是正常形态非 stale）。
- 533097：首 delivery:0 FAIL → subset:46 pass（重产 artifact ...860.66）→ delivery:70/119/161/204 全 pass。
- 无显式 stale/late_recovery facts 字段——「迟到回收」来自 TUI 显示、是**编写侧** fork 墙钟超时后合格卷回收（run18 型），非设备 stale。

## 教训
- **双路漂移**：REPORT_MISMATCH（对账/report/LLM 摘要三处报 40）是**一次计算三处回声**、非三个独立源。对账门价值在**逼出仲裁**（flag 分歧触发 D31），不在它重算的那边（40）先对。
- **口径反转**：40 是 bug 侧、render 42 才对。早前「D17 正面=LLM 摘要 40 没盲抄 42」反转——40 反映 buggy checker、非 positive。
- 诚实边界：Test-Eng「stale」是推断非 facts 字段、artifact 吻合不证 run-identity 新鲜——说清边界使 leader 得以反转假设面，正确姿势。

## 修复
Py-Eng 收口批列首件（D31 修两处行级 + 四关）→ 合入 → 重启 → 同参重调 zhaiyq（delivery 幂等闸零设备轮）→ 重渲 recount==claimed==42 无 REPORT_MISMATCH。
