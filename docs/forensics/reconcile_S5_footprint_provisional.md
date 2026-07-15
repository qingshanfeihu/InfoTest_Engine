# Reconcile — S5 footprint 是否标 provisional(设计张力收尾)

> 张力:深审矩阵 §1#7 / finalization §3.1 说「precedent 标 provisional、footprint 写回标注策略**未同步**」,
> 依 DESIGN §A 字面(line 36:「compile_writeback/**footprint** 写回时如实标…provisional」)footprint 也该标;
> 但 #12 实现保持 footprint `on_device_passed=True` 不标 provisional。read-only reconcile,产结论、不改代码。

---

## 结论:**保持现状(footprint 不标 provisional)。矩阵 §1#7 是轻度误判——过度字面读 §A 的三标清单。**

§A line 36 把 `compile_writeback`(precedent)与 footprint 并列「如实标 采样敏感/机生血统/provisional」,
读起来像两通道机械套同一三标。但**总原则(line 11)是「如实标」——标**为真**的,不是机械套三标**。
对 footprint 逐通道核「三标各自为真吗」,结论是 footprint 只该标机生(已标)、**不该标 provisional**,理由三条:

### 1. footprint 是 per-fact 累积、provisional 是 per-case 属性——两者不组合
- 实测 `sdns.host.json`:单节点 `verified_count: 211`、`source_threads` ≈10 条 `compile_writeback:<autoid>`——
  **一条语法事实由 10+ 个 case 累积背书**,不归属单一 case。
- provisional=「某 case 子集轮过、未终验」是**单次写回事件/单 case** 的属性。把它贴到一条 10 case 累积的语法事实上,
  语义坍塌:「因为 10 个贡献者里有 1 个是子集轮,这条 211 次验证的语法就 provisional?」——**不如实**。
- 对比 precedent:一卷 `verified_<autoid>.xlsx`=**一个 case 的整条断言链**,per-case,provisional 贴上去恰好对位。
  ∴ **provisional 天然属 precedent(per-case)、不属 footprint(per-fact 累积)**。

### 2. footprint 存的是 G 段命令语法=h-不变量,子集轮也真上机跑过=genuinely verified
- 语法合法性(`sdns host pool <h> <p> <w>` 能否解析)不依赖采样/轮转/断言结果——h-不变量。
- 子集轮 PASS 证明该命令**在设备上真发过、被接受**(verified_runs 有 device_run_ref)。标 provisional=谎报「这语法没确认」,**不如实**。

### 3. 子集轮 footprint 事实已被 V8 回滚保护——标 provisional 既冗余、又砸 device_verified
- `_rollback_one`(nodes.py:1170):终验 fail 时「**footprint 按 device_run 锚摘条**」——子集轮写的事实若没熬过 delivery,
  **机械摘除**。∴「provisional 事实可能被推翻」这层担忧**回滚已兜住**,不需再标。
- 且实现上 footprint 的 provisional 只能经 `on_device_passed=False` 表达,而 `compile_writeback.py:135` 的
  **device_verified 第二权威源重试仅在 `on_device_passed=True` 触发**——设 False → 运行时命令(不在 CLI 手册那批)
  整个 skip 不写回(28/28 skip 型「知识循环堵死」回归)。**标 provisional = 砸 device_verified,硬伤。**

## 方案C(解耦:on_device_passed=True + 另加 provisional 标签)——不值得
- per-fact 累积模型下,per-写回事件的 provisional 标签会 flip-flop(子集 case 写、delivery case 再确认→算不算 provisional?),语义不清。
- 它要防的「subset 事实被推翻」已由回滚兜住(理由3);要防的「flaky 断言被照抄」在**断言链=precedent**、已标(#12)。
- footprint 语法**不是投毒向量**(投毒在断言极性/采样形态,那在 precedent)。为不存在的 harm 加标签+渲染=过度工程。

## 投毒治理边界(收尾定性)
**投毒活在 per-case 的断言链(precedent)——已由 #12 三标(采样敏感/机生/provisional)覆盖。**
**footprint 存的是 per-fact 累积的命令语法(h-不变量),不是投毒向量,标 provisional 既不如实、又砸 device_verified、且与回滚冗余。**
∴ §3.1 的「未同步」实为「**正确地区别对待**」:两通道语义不同(per-case 断言链 vs per-fact 语法),标注策略本就该不同,不是 bug。

## 建议(doc-only,不改代码)
1. **保持现状**——footprint `on_device_passed=True`、不标 provisional;provisional 只落 precedent。(已有专锚 `test_writeback_threads_provisional_keeps_footprint_device_verified` 锁死。)
2. **澄清 DESIGN §A line 36 措辞**:「如实标」=按通道语义标**为真**的——precedent(per-case)标 采样敏感/机生/provisional;footprint(per-fact 累积 h-不变量语法)标机生(source_threads,已有)、**不标 provisional**(per-case 状态不组合到累积事实上;子集轮语法真 verified;回滚已兜半毒)。§3.1 的「未同步」改注为「按通道语义正确区别」。
3. **理论对账**:与 K §2.9.4 (45)一致——(45) 治的是**判例源**(per-case verified 卷)的自指投毒,footprint 语法事实经 evidence 门+device_verified 三重校验+回滚,不在 (45) 的 per-case 投毒面上。

STATUS: done
