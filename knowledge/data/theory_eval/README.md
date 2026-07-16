# theory_eval — 理论评估数据集(THEORY_k_state_machine.md §7)

- ds1_attribution_gold.jsonl — 归因金标准(20 案):每次改归因链跑回归,报层级分派与根因准确率
- ds2_intent_fidelity.jsonl — 意图保真集(7 对种子):标签与上机结果独立;任何合取② oracle 候选先在此量判别力
- ds4_k_performance.jsonl — K-性能曲线(4 点):中心论断可证伪监测器,每批追加一行;r1_hit 引用一律取
  首跑口径(selfheal2 已按 07-13 校准改 6/13;pe1 标 caliber=unverifiable 仅供定性,2026-07-16 修正)
- DS-3(K 状态标注集)未建:待 build 锚落地后与 stale 扫描一起做

维护:escalated/defect_candidate 案例人工裁决后追加 ds1;交付卷保真审计违例追加 ds2;每批交付追加 ds4。
