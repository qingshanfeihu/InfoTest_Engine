# 593516 WRR 问题综合定性(团队四面调查汇总)

> 2026-07-15 dongkl 真机重验暴露。四个只读调查 agent(logic-tracer 推理逻辑 / v6-archaeologist V6考古 / theory-checker 理论 / design-checker 设计)独立取证,结论收敛。**本文只定性,不改代码**。

## 一、推理逻辑:单点根错 → 四级连环误判(logic-tracer)

**根错在 worker 编写**:把 WRR **分布**属性编码成成员 IP **存在性**检查(几个 `dig` + `found` 算子)。`found` 是 DOTALL 正则存在搜索——不能计频、不能把响应绑请求,**结构上无法区分"WRR 正常"与"WRR 卡死一个 pool"**。
- **铁证**:RouterA 四次 dig 全返 213(零轮转),`found 213` 却 **PASS**——零判别力、构造性假阳。

级联(每层带源码行):
1. **worker** 误编码(根错)→ 案只能靠 RouterB 偶发 timeout 才"fail"。
2. **归因** `fail_attribution.py:232-234` 词表只有 env/product/transient/expectation,**无"方法不当"桶**;且只看失败 checkpoint,看不到"RouterA 零轮转却 PASS"这条最强反证 → 落 `env_blocked`。
3. **ask** `engine_tool.py:243-252` 机械把 env_blocked 路由成"确认是环境问题吗?"二选(停/隔离复跑),**"改步骤"从未可表达** → 假二分。

## 二、V6 设计:曾有"数据+工具+门"三件套,当前删了门(v6-archaeologist)

- V6 分布 oracle = **数据**(`domain_grammar.json:151` 均摊/加权轮询=分布类,发N次→累计命中∈区间,Σ==N)+ **工具**(`checker_tool.py:12 compile_expected_hits` 算可验区间,**至今在**)+ **验收门**(V6 commit `984d0bf2`,grade 门跑分布检测器)。
- 当前 v8 只剩 数据+工具+**散文**,门被删(2026-07-07)——检测器(`grade_extract_script.py:400-408`,含"分布类 dig 写死单成员IP")**降为诊断-only 不拦 emit**。
- **时间线冒烟枪(post-fix 回归)**:S1 分布指引 `dc435c93` @19:21 落地 → 593516 @21:33(2h后)编译,provenance 8×dig+成员226、**零 show statistics**。指引在 prompt 里,worker 照样没用。
- **worker.md 分类灰区**:73-88(分布→区间/dist)vs 89-98(存在/枚举→abs_found,无h)。"p4 参不参与轮转"长得像成员存在检查、实为分布(h-in-λ),**无消歧句** → worker 默认走 few-digs。
- **同批反证**:593545(同 WRR)用了 show statistics 但写脆 `Hit:\s+3`;593516 用 few-digs。**同指引、行为不一致**。

## 三、理论核对:理论没缺口,是实现丢理论合取(theory-checker)

- 593516 = **class-6 欠定**(R 依赖 h-in-λ 采样),(40)七类处置里唯一出口 = **"R 边缘化改写(verifiability 通道)" = 改断言形态/步骤**(S §0.5:179-186 明写"大样本+show statistics+区间")——**与用户裁决逐字一致**。非 env/非缺陷/非编译错。
- 唯一 thin 理论子缺口(h-样本 vs h-不变式的机检判据)**2026-07-15 已就此案补上**(S §0.5:168-186;K §2.13:802-841)。**无需新公理**。
- 实现三处误用:
  1. **verifiability 只是 V_U 检测器**(§2.10)——只抓"真不可表达";dig 命中计数能出数字、放行 → 欠定**编译期漏网**。盲区="能出数字但是 h-样本"。
  2. **归因缺 h-位置轴**(S §0.5:158-162)——分不清"env 超时"与"设计不当欠定" → class-6 误标 class-4。
  3. **ask 违 (46) 问询三元组律**——必含⟨R+出处、阻碍、**已推导替代**⟩,env-vs-缺陷丢第三项。run22 同构先例(:560-564)。
- infra 无关(理论故意把分布随机性划归 K/S 域)。

## 四、设计核对:三阶段都点了名,但全是散文-only(design-checker)

- 设计**非静默**:finalization 今日把 593516 列"单元A"、env_blocked 列"单元B",S1/S2 已改 worker.md/attributor.md。
- **残余病灶 = §0 治理原则**(finalization:8-16)"全走摆事实+LLM 自查,**不加机械门**"(用户红线)——把每个修复**封顶在 prompt 陈述强度**。
- Q1 DESIGN_v8 §18.15-A 原有 emit 门(:1646),finalization **删了**,分布分类→oracle 全交 worker 判断 → **WEAK**。
- Q2 worker.md 内容好但**触发+强制弱**:需先自分类(无"比例X:Y:Z→分布 oracle"触发钩)、程序(大量发包/read statistics)被弱化为断言形态、纯 prompt。分布验证本是**低自由度"唯一安全路"却被当高自由度**。→ WEAK + 实证反证(593516/593545 分裂)。
- Q3 attributor **无"方法不当→改步骤"一等公民处置**;有同案自查(56-77:passing cp⇒可达⇒非env⇒分布敏感→V/区间)但**明标 advisory 不自动降级**(§B 不自动降级)→ 没翻案。此即 §18.15 X2("disposition 双重语义")。
- Q5 ask 两套:worker-欠定 ask(`questions.py` 有 改过程/改预期 + distribution→dist)**但只在 worker 主动报欠定时触发**,593516 worker 自信 emit → 不可达;post-fail ask(env_blocked→停/复跑)**无改步骤项**。
- **设计本意**:可推导的方法修复应是**静默 reflow 不是 ask**(`nodes.py:366-367`)。**用户裁决与设计本意一致**——本该无 env-vs-缺陷 ask、直接静默 reflow 到 statistics+interval。**错 ask 是 Stage-2 误归因的症状,非缺 ask 分支**。

## 五、当前问题定性(四家收敛)

**593516 不是理论/设计的"没想到",是一个哲学张力的实弹暴露**:

> **`§0"零机械门、纯散文自查"红线** vs **分布验证形态本质是"低自由度、唯一正确形"决策**——散文单独镇不住,而 V6 本来用门镇,门被红线删了。**

具体:理论已预言正确处置(class-6 欠定→改步骤=大样本+statistics+区间)、已补 thin 判据;设计三阶段都点名。但三处修复全 prompt-only,于是:
- **worker 选形态**:灰区无消歧 → 可选结构盲的 few-digs(实证 593516/593545 不一致);
- **verifiability 编译期**:V_U 太粗 → 盲形态漏到设备;
- **归因降级**:env_blocked→reflow 是 advisory → timeout 形 fail 误标 env → 错 ask。

**最高杠杆点(design-checker)= Stage-2 归因**:若归因对"分布敏感 + passing cp⇒可达"的 fail 可靠地把 env_blocked 降级为 reflow/V,案就变**静默 reflow 到正确 statistics+interval 法**,伪 env-vs-缺陷 ask 根本不出现。

**开放张力(留给用户裁决,本文不解)**:这种可靠性能否在**不加机械门(§0 禁)**下靠散文达成?还是分布形态这类低自由度决策**应破例保留一道窄门**(如 V6 的分布检测器重新挂 emit,仅此一类)?这是 prompt-only 哲学的边界问题。

## 附:同时暴露的第二问题(572741,已记录)

572741 用例断言写错(`clear sdns host method` 重置为 rr 不删条目,断言 `not_found` 应 `found "rr"`),非跨案污染。属用例质量,与上述引擎处置问题独立。
