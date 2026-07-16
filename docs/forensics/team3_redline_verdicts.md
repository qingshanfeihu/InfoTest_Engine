# 三处「零写死领域命令」红线裁决（team3，主协调终裁）

> 背景：skill-audit（team2）移交的张力点 + origin/main 合并带入的新命令面。redline-check 子 agent 因工具集无消息通道未能交付，本裁决由主协调依 CLAUDE.md「skill/agent prompt 编写红线」（自由度分层 + 参考文档只写机制 + 引擎不注入命令建议）直接作出。2026-07-16。

## ① device-verify SKILL.md 的 show 命令表 —— **违规（延期修复，需 eval 先行）**

- 证据：`SKILL.md:104-116` 九行「已验证正确命令」表（`show slb group method` 等），并要求「use the exact commands from the table; never simplify」。
- 定性：**与它自己的机制条款自相矛盾**——`:100-102` 已强制「每条命令先 grep CLI 手册确认全名与参数」，表格把该查的答案预先烤进 prompt = 领域判断答案硬编码，随手册版本漂移（强字典误杀/漂移已有 GA-CUT 前科）。
- 豁免部分：`:52-58` 危险命令黑名单/白名单 = **安全边界禁令，合规**（窄桥护栏非知识），保留。
- 为何延期：该表是针对「LLM 简化命令丢关键信息」实弹回归（`show slb group` vs `show slb group method`）的**有意反制**；按「改 prompt 前先有 eval」纪律，无 eval 直接拆表=裸奔风险，且 device-verify 不在本轮 yzg 验收关键路径。
- 最小修法（留给专项轮）：表格降级为「形态示例（标注可能随版本漂移）」+ 机制强化（全名必须以 grep 手册结果为准，简化形态列为反例类型而非逐条命令）；或把已验证命令下沉判例层（footprint）运行时引用。

## ② config-answer-draft.md F5→APV 对照表 + epolicy 三命令 —— **合规豁免**

- 证据：表内 `slb virtual http`、`epolicy import script/attach script/class` 等目标文法词。
- 定性：这是**配置翻译任务的目标文法=内容本体**（低自由度窄桥：翻译产物的形态契约），非「替 LLM 做该查手册的领域判断」；且 epolicy 三命令要求的执行机制是「必须用 `build_command` 生成」——命令经工具生成而非照抄 prompt，机制合规。该行来自远端有意提交（「缺少 epolicy 命令等同于翻译遗漏」，实弹缺口反制）。
- 附注：目标文法随版本漂移的风险由 build_command 的手册闭合承接，不在 prompt 层。

## ③ compile-worker.md 现状基线 —— **合规**

- 通道消歧 bullet 仅用泛型通道词（dig/show 作为通道类别）；无具体设备命令；D8 新增段按「类级措辞、零写死命令」指令实施中（impl-tools）。prompt 结构门持续把关。

## 汇总

| 处 | 裁决 | 动作 |
|---|---|---|
| device-verify 命令表 | 违规 | 延期专项轮（先建 eval），本轮不动 |
| config-answer-draft | 豁免 | 不动 |
| compile-worker.md | 合规 | D8 按令继续 |
