# SLB 吃透报告（#51 · 2026-07-19 · leader 合成）

> 上线主线 Phase 1 第二棒（SSL 侧见 `team4_ssl_digest_report.md`）。三线对齐 #50 标准：
> **A 机制** `team4_slb_method_cards.md`（execute 40 动作全读+server 触发端+模糊碰撞仿真）
> **B 用法** `team4_slb_usage_patterns.md`（全域 86 卷挖掘+SLB 面语料定量）
> **C 特性** `team4_slb_ssl_feature_model.md` §7-§9（G1-G7 模型+四方矩阵 SLB 版）
> 评审链：三线交叉互检 → Design 五维格式审 **P 全清（零 finding）** → leader 合成。
> 床实证：`team4_bed_readiness_probe.md`（#53，5 项 4✅+1◐）。

## 一、理解层终判（G1-G7）

| 域 | verdict | 关键事实 |
|---|---|---|
| G1 虚服务 / G2 real+组 / G3 调度 / G6 策略 / G7 统计 | 吃透 | 全走通用 cmd_config（编译器 105 卷已实弹的主力方法），配置面零新方法要教 |
| G4 健康检查 | 吃透 | 判例最厚（41 断言行）+execute 健检等待族（func_209-213）+server 起停触发 |
| G5 会话保持 | 吃透（机制）/零先例（用法） | func_219 查表机制清楚，但金标准零 L4 粘性先例 |

**核心结构事实**：`slb_comm.py` 是**空文件（0 行）**——SLB 无任何专用模板方法（对照 SSL 的 25 证书方法族），其「方法」＝通用配置 + execute 动作 + server 触发 + curl。**SLB enablement 没有 SSL 的证书族 emit 卡点。**

## 二、「数不出、读出来才知道」的核心事实

1. **模糊派发语义反转风险（新发现→已闭环）**：离线真跑框架模糊匹配（≥0.8），40 动作名中 **9 对碰撞、5 对语义相反**（健检等 UP⇄等 DOWN 0.812、绑定⇄检查 0.897、AXFR⇄IXFR 0.944）——worker 动作名不精确+精确匹配失败＝静默派到反义函数，设备层不可见。**已催生 #56 A 层 emit 门**（动作名精确 ∈ mirror 解析闭集 66 项，含同义词表；金标准 2208 行 execute 100% 命中零误杀实证）。
2. **server 触发端契约**：config env 是逻辑名→IP 表——**换床改配置不改用例**（可移植性）；后端跑 shell 起停真实服务器造 UP/DOWN；IP 恢复副作用（框架自动记账，用例勿自行 del）。
3. **SLB 语料远薄于 SSL**：86 卷提及 slb 中 **79 卷纯脚手架**（slb 对象作 sdns 本地池、断言全 DNS 面），真 SLB 面仅 **7 卷**、SLB 中心仅 **2 卷**——SLB 从未作独立测试域。**G3 调度分发＝零先例**（rr 配 128 次、无一卷发流量验分发）；**G5 L4 保持＝零先例**（仅有命中是 sdns GSLB 亲和）。
4. **纯 SLB 观测独立可用（上机实证，破历史惯例）**：`show statistics slb` 10 个独立子命令、global/connection 表**零 sdns 语境**返回结构化输出——金标准全嵌 sdns 是**惯例而非设备限制**；唯一前提=先配 VS 再看 per-VS 数据（用例自然结构）。
5. **部分 execute 动作自带断言**（func_3/4 内嵌 check_point）——观测第四形态，SLB 健检类可自验。

## 三、床就绪（#53 实证）

✅ 后端 server213/231/232 全可达 ✅ 本地证书树在（SSL 共用）✅ OCSP 间接投影 ✅ 纯 SLB show 独立 ◐ routerA 工具链（执行宿主追踪中——框架无直连 routerA 代码，client 命令疑似跳板机本地执行，若证实则无需凭据）。

## 四、上线排序判定（三方实证收敛）

**SLB-first·限幅**：①无证书族 emit 卡点（slb_comm 空实证）②观测更全（show 主力、零 EMPTY 格 vs SSL 的 OCSP 间接）③配置面全走已实弹方法。**首批范围＝纯配置存在性 + G4 健康翻转 + G1 VS 可达**；**G3 调度分发 / G5 会话保持 DEFERRED**——零先例意味着纯新造（novel authoring），押上机建 footprint 后另批。HTTPS-VS 卷（SSL∩SLB 交点）为两域联合冒烟天然候选。

## 五、enablement 现状（并轨中）

- SLB 文法草案 8 条已出（Theory 草拟：5 statements+3 reference_closures，G1/G2/G4 限幅，诚实留空待实证字段）→ LLM-Eng 单写者与 ssl 条目一次合入 domain_grammar.json（合前逐字对手册精校 regex）→ 四关同批。
- #56 精确门四关中（双专家 P，待 redline）。
- 剩余观察项（import prompt 文本/长证书截断/execute 实派正确率）并入 #54 首批实弹。

## 六、方法论沉淀

「吃透三线+交叉互检」在 SLB 侧二次验证：Theory ② 预判此次被 A 证实（#50 同类预判曾被证伪——两次都以「待证」标注、证据落地即核，预判不锚结论）；Design 读全文纪律自拦 2 个 near-false-flag；模糊碰撞用离线仿真定量（零设备时占用）。
