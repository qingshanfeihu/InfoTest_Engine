# 4 脑图准入报告模板（D+5~7 冲刺交付 · Design 定稿 · 并入 #24）

> 外部借鉴（NeTestLLM arXiv 2510.13248 / IETF draft-cui-nmrg）设计面定稿产出（team4_leader_nettest_survey.md 五加速点 #1/#3 落地）。
> 用途：D+5~7 准入报告直接按此结构出；数字全程**照抄 engine_report 机械事实**（D17 纪律、非 LLM 自行数）。
> Design 出模板 + Py-Eng 供数据（kb_bug_search / engine_report），批终前定稿。

## 一、自动化成熟度定位（L0-L5 · IETF draft-cui-nmrg-auto-test）

- **分级**：L0 全手工 → L1 辅助 → L2 部分自动 → L3 有条件自动 → L4 高度自动（人机协同自适应） → L5 全自主。
- **本项目当前 ≈ L3-L4**：人机协同——欠定问询（ask 三面板）+ 批级放行（终验/交付门）+ 判例自愈（shape-aware 采信）。
- **准入目标表述 = 「特定域 L4」**（网关/SLB 配置验证域的高度自动人机协同），**不主张 L5**（诚实边界：仍需人裁欠定/缺陷确认）。

## 二、交付统计（照抄 engine_report totals · D17 纪律）

- **数字/计数/分类一律照抄 `engine_report.json` 的 `totals` block**（cases/deliverable/failed/suspended/broken）——**禁 LLM 自行数、禁 per-theme 主题细分**（D17：engine_report 无 per-theme 字段、自行 theme 归类=数错根，如 4+4=8）。
- **格式**：「本批 N 个用例：交付 X / 未通过 Y / 挂起 Z / 未跑成 W」——每个数字来自 totals 对应字段（copied，非 re-tally）。
- 人话措辞可友好包装（控制面），数字是数据（照抄 engine_report）——两者分离。

## 三、缺陷覆盖口径（NeTestLLM 评价法 · kb_bug_search）

- **核心度量 = 卷面覆盖历史缺陷数 vs 人工卷基线**（NeTestLLM 用「覆盖 41 FRRouting bug vs 国标 11」讲价值，同法）。
- **数据源**：kb_bug_search 对账——本引擎卷面断言真覆盖的历史缺陷数 / 同域人工卷覆盖数（同床同域可比）。
- **叙事**：「引擎卷面覆盖 M 个历史缺陷（同域人工基线 K）」——对用户汇报和专利叙事都更硬（比"25/26 交付"的相对数字更实）。
- **诚实边界**：覆盖数是「卷面断言指向的缺陷」、非「上机复现的缺陷」（复现另计）；基线是同床同域人工卷（跨域不可比）。

## 四、缺陷候选（引擎产出）

- `defect_candidates.md`——引擎两轮自判疑似产品缺陷（换配置形态复现待人核），准入报告列候选数+去向（人核）。

## 五、覆盖段（breadth 覆盖对账 · ★观察级不阻塞交付）

- **breadth 机械可判**（Theory 解：脑图结构化枚举 + intent 盖章链——**depth 不判是红线**，深度覆盖靠上机 oracle 非机械对账）。
- **★观察级（leader 裁定，A2 先例防新门误杀）**：覆盖段**只报告漏编、不阻塞交付**——「脑图 N 测试点、卷面覆盖 M、漏编 K：列出漏编测试点」；**升交付门（残差清零才交付）押实测数据后**（防覆盖评估器新门误杀金标准，同 GA-CUT 强字典误杀教训）。
- **INV-breadth「残差清零才交付」= 观察期目标**（非当前硬门）——观察期收集覆盖评估器误判率，实测稳后再升门。

---

**模板落地分工**：Design 出本模板结构（并入 #24 六裁决方案）；Py-Eng 供二/三/五段数据（engine_report totals / kb_bug_search 对账 / breadth 覆盖对账 closing 节点观察级产出）；D+5~7 准入报告按此填。**数字纪律贯穿**：二/三/五段所有数字照抄引擎机械事实（D17），报告是判定式渲染+人话包装、非 LLM 自行统计。
