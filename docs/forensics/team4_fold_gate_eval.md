# 收口批预研·folding × 先问后落门交互 bug 修法候选评估（Py-Eng，只读，不实施）

> 状态：**评估存档，零代码改动**。收口批走 Theory+Design 双评审后实施。
> 触发：Test-Eng 机读取证坐实 P1 引擎 bug（599838 实证，折叠成员必败门，多烧一轮 re-ask 自愈）。

## 1. Bug 机制（行级证据）

- **先问后落门**（`verifiability_tool.py:405-426`）：`compile_user_decision` 落盘前，扫 `runtime/ask_user_answers.jsonl` 查是否有含该 case **autoid 全名或尾 6 位**的行（:415-419）；无则拒（:422-426）。**门的设计意图**（:405-408 + `ask_user/__init__.py:235-238`）：orchestrator 曾在 ask_user 前替 8 个欠定 case 自己拍板——prompt 红线拦不住，**只有"由真实问答路径落的独立凭证"是 A 层**。门的抗伪核心＝**独立于引擎/orchestrator 的自我断言**。
- **日志写入**（`ask_user/__init__.py:244-251`）：真实问答后落 `{"questions": [q.question[:500] for q in questions], "answers": {...}}`——**按问题记、题文截断 500 字**。
- **gather 折叠**（`nodes.py`）：N 个同(组,签名)案折成**一题**取代表 rep（`qs` 每 fold 一条、只含 rep 的 `_autoid`）；rep 题文加后缀「本题代表同组 N 案:尾号 X、Y…」（:649-655）。interrupt 按 4 分块发（:691-694）。
- **两侧口径分叉（根因）**：
  - **facts 侧**：`ask_shown` **逐成员**落，非代表标 `folded_into`（:679-687）——账目完整、每成员可回放。
  - **日志侧**：**按问题（rep）落一条**，成员尾 6 仅靠 rep 题文后缀携带，且题文 `[:500]` 截断——**大折叠组尾 6 列表越过 500 即丢**（599838 必败门的直接成因面）。
- 后果：门查成员尾 6 → 日志里没有（或被截断）→ 拒 → 折叠成员本轮不落决策 → 下轮 re-ask 自愈（多烧一轮）。

## 2. 三候选 × 三维评估

| 维度 | ① 每成员尾6也写Q&A日志 | ② _land传代表标识·门认rep尾6 | ③ 门读facts的folded_into放行 |
|---|---|---|---|
| **门设计意图（抗伪：防无问答记录的裁决入账）** | ✅ **不弱化**——成员确经折叠进 rep 题、用户**真答了**；尾 6 写日志是**如实**记录，且写在**真实问答路径**（非引擎事后补），门的独立性保持 | 🟡 **基本不弱化**——锚到 rep 的真实 Q&A（rep 确在日志）；但门改为"成员决策由 rep 问答间接背书"，且需信引擎传入的成员→rep 映射（部分信引擎输入） | ❌ **弱化**——门去读**引擎写的 facts**（folded_into）。门存在的前提正是"引擎/orchestrator 不可自证"（:405-408）；读引擎 facts＝引擎可伪造 folded_into 绕门，**独立性被摧毁** |
| **折叠语义一致性（统一到哪侧）** | ✅ 日志侧→**逐成员**，与 facts 侧 `ask_shown` 逐成员**同口径**（最干净） | 🟡 日志留 per-rep，门加 member→rep 映射；两侧**仍分叉** | 🟡 日志留 per-rep，门耦合 facts 流；两侧分叉 + 门新增账依赖 |
| **改动面/回归风险** | 🟡 中：日志写侧记专用成员尾 6 字段（**须专用字段，不靠可截断的题文后缀**）；引擎已知 fold、经 interrupt payload 传成员尾 6。**跨域触点**（answer-log 写侧＝ask_user 工具/TUI 桥 + nodes.py payload） | 🟡 中：`_land`（nodes.py）+ **门签名**（verifiability_tool——安全门，改需慎）；门语义变（认 rep 代成员） | 🔴 高：门读 facts（新耦合引擎账）+ 破门独立性；未来任何"信 facts"的门都被此先例带偏 |

## 3. 推荐结论

**推荐 ①**（日志侧统一到逐成员）。理由：唯一同时满足①不弱化抗伪（成员真被折叠进已答题，如实记录、写在真实问答路径）②口径统一到 facts 侧既有的逐成员形态③不动安全门签名/不耦合引擎账。**口径统一方向＝逐成员**（facts 侧已是，把日志侧拉齐）。

**① 落地必带的两条护栏（收口批实施时）**：
1. **专用成员锚字段**，不复用 `q.question[:500]` 题文后缀——现截断正是 599838 的失败面；日志 `_rec` 加 `folded_members: [tail6…]`（或逐成员一条），门查它。
2. **写在真实问答路径**（answer-log 写侧，即 `ask_user/__init__.py:247` 的等价点 / 引擎-interrupt 的应答落盘点），**绝不由引擎在 `_land` 后事后补写**——否则引擎又成了自证方，退化成 ③ 的抗伪漏洞。

**② 为次选**（门被逼改时的退路：锚 rep 真实 Q&A，可接受但不如①干净、且碰安全门）。**③ 不推荐**（违门抗伪设计意图，先例危害面大）。

## 4. 待收口批确认的开放点（评估边界声明）

- **引擎-interrupt 路径是否/如何写 ask_user_answers.jsonl** 未完全落定：`ask_user()` 工具（:244）是确证写点，但 gather 走 `interrupt()`（nodes.py:694）经 ist_app `_begin_ask_user`→AskUserSession→submit_answers；其应答落盘的确切触点需与 **TUI-Eng 联合核**（决定 ① 的写侧落在工具域还是 TUI 域）。此点不改推荐结论（①/②/③ 的抗伪与一致性排序与写点无关），只影响 ① 的具体触点与分工。
- 本评估只读、零代码改动；实施押收口批、经 Theory（门抗伪不变量）+ Design（折叠口径一致性条款）双评审。

---

## 5. 四方对表收敛结论（Py-Eng ↔ Theory ↔ Design ↔ TUI-Eng，2026-07-18）

**定案：候选 ①（合成形态）**。经互对证据面，纯①/纯③均被修正，收敛到合成案：

### 5.1 判决
- **③ = 设计红线 F（不可选，非权衡）**：门读引擎写的 facts.folded_into = 门信任被审计方的账 = 可伪造绕门，违 **审计器权威(公式18) + [[gates-on-credential-path-not-edit-path]] + §5 门独立性**（Design 准则级定性；Theory 改判承认「引擎读引擎账=可伪造」击穿③）。folded_into 生产侧零消费者、纯审计字段，让门消费它=把审计字段升级承重凭证（设计从未让它承重）。
- **② = 次优不推荐**：校验粒度成员→rep 下移，违「按成员校验」意图（rep 被问≠每成员知情），削弱门保真。
- **① = 合成形态**（见 5.2）。

### 5.2 ① 合成形态（Theory 精化 + 三方纳入）
1. **凭证形态**：代表案的**真实应答记录**（`ask_user/__init__.py:244` 唯一写点，凭证路）带 `folded_members:[全 aid]` 字段——引擎把清单塞进代表题 dict → 经 `_bridge→_panel`（engine_tool.py:26-47）→ `ask_user.func` → :247 落盘。凭证条数=真实应答批数（⌈N/4⌉），**不膨胀**。
2. **门匹配结构化**（Design 红利）：门（verifiability_tool:415）从子串 `aid[-6:] in _line` 改**集合成员判定** `aid in rec["folded_members"]`——顺带根治裸数字子串误撞（[[transient-error-bare-digit-marker]] 同型）。写(:247)读(:415)同步改。
3. **两路分立**：facts 的 `ask_shown`/`folded_into` **留作审计/回放（INV-7 辖业务态派生）、不作门凭证**；门凭证走独立应答路径（凭证路，独立于被检查方）。**辖区澄清**（Theory 定稿）：INV-7「业务态以事实流为准」辖引擎派生结论（counts/verdict 防显示漂移）；防伪门放行凭证必须独立于被检查方，本就该独立于事实流——不构成 INV-7 冲突。
4. **性质**：修的是 **nodes.py:653-655 既有桥**（代表题面本就披露全体成员尾号）被 `ask_user:247 [:500]` 截断破坏的意图——**不是建新真相源**（专用结构化锚 = 把 653-655 的披露做成不可截断形态）。

### 5.3 抗伪不变量 + 守门测试（Theory Q2 残留面对策）
- **不变量**：`凭证.folded_members == 代表题面披露的成员集(653-655) == 门放行集`——三者同源 `fold[rep]`、恒等。抗伪边界＝「折叠披露与凭证一致」（可机械守，非无界信任）。
- **三道守门测试**：①折叠正确性（凭证 folded_members 恰等于题文披露成员，防引擎偷塞用户没看到的案）；②折叠成员经集合判定过门（599838 反向：真答成员放行）；③截断免疫回归（大折叠组全 aid 清单不被截断丢，599838 根因锚）。

### 5.4 消费面 + 落地边界
- **消费面 1写1读**（Py-Eng+Design 双证）：`ask_user:244` 写 / `verifiability_tool:407` 读（门）；035413/记忆管线**不读**——改格式零跨管线连带。
- **写点单一**（TUI-Eng 触点核确认 :244 唯一，submit_answers 不落盘）→ **无双写点风险**；fold info 经 interrupt payload 流到 :244。
- **实施域**：nodes.py（代表题 dict 加 folded_members）+ ask_user/__init__.py:247（记字段）+ verifiability_tool:415（集合判定）+ 三守门测试。跨 Py-Eng（引擎/工具）；无 TUI 渲染改动。

---

## 6. 单一共署版本（定稿·Py-Eng+Theory 共署，送 Design 终审 → leader 终拍）

> §5 是收敛过程；**本 §6 是唯一权威版本**，取代 §5.2 中"日志 vs 事实流"的悬而未决。leader 暂挂拍板因我与 Theory 各报了 A/B 两案——此处定为 **变体 A**，理由见 6.3。

### 6.1 理论根：辖区判据（Theory 定稿句）
> **业务态 vs 防伪凭证辖区**：一个数据归 INV-7「业务态以事实流为准」还是 gates-on-credential-path「门挂独立凭证路」，取决于其角色——**业务态**（引擎派生结论 counts/verdict/deliverable）须 facts 单一真相源，防显示与事实流漂移；**防伪凭证**（防伪门放行依据）须独立于被检查方，防其自证。二者不矛盾：**凭证可进 facts 单一真相源**——抗伪性不来自"凭证在流外"，来自**写入点相对不可绕过外部凭证信号的时序位置**：写在外部信号（interrupt resume）之前=被检查方可自达=不抗伪；之后=需真实外部信号才可达=抗伪。精确判据：**门不能读被检查方在凭证信号之前能自达写入的账**（旧表述"门不能读引擎写的账"过粗——引擎 resume 之后才能写的凭证合法）。

### 6.2 三点明确（回 leader 版本分叉三问）
1. **门凭证源＝`ask_user_answers.jsonl` 的 `folded_members` 字段**（变体 A）。
2. **旁路日志门角色＝保留**（作凭证路；facts 的 `ask_shown`/`folded_into` 仅审计/回放、不作门凭证——两路分立）。
3. **写点/行号**：引擎供清单 `nodes.py`（代表题 dict 加 `folded_members:[全 aid]`，源 `fold[rep]`）→ 经 `_bridge→_panel`（engine_tool.py:26-47）→ `ask_user.func` → **写 `ask_user/__init__.py:247`**（`_rec` 加字段）；门 **读 `verifiability_tool.py:415`**（子串 `aid[-6:] in _line` → 集合成员判定 `aid in rec["folded_members"]`，全 aid）。

### 6.3 为何 A 不 B（两案在时序判据下同合法，选简）
- **A 同样过时序判据**：`ask_user:244` 落盘在 `event.wait()`（:225）返回**之后**，event 由真实 `submit_answers` set → **:244 写入点 post-signal**，A 凭证抗伪成立、不违辖区判据。
- **A 避开 B 专属成本**：B（facts 加 `user_answered`+门读 facts）须①永久守"`user_answered` 必 post-resume"隐形不变量（挪到 interrupt 前即破）②回答 resume 不可伪造边界（checkpoint 重放/`Command(resume)`）+ (48) per-member idem_key 设计 ③Design 准则级 F 是否被时序论证豁免（未定）。**A 三者全不触**：无新 facts 事实（无 idem_key 问题）；凭证是 ask_user 日志（凭证路、非引擎 facts）→ Design 的 F（针对引擎写的 facts）**不适用**；重放时日志 append-only 持久、门 live 复检一致。
- **A 已 leader 拍板**（"改动面收窄到纯你域单写点"＝:244）+ 更小 + 无新脆弱不变量 → **定 A**。B 的唯一优势=facts 单源纯度，而判据已判纯度非抗伪必需。

### 6.4 两层＝串联知情同意链（Theory 修正，非正交）
- **凭证层**（folded_members 专用字段，免 `[:500]` 截断）守门断言「凭证 folded_members == 代表题面**组装**披露成员(653-655 tails)」——同源 fold[rep]、构造恒等、**必过**。
- **展示层**（`ask_user:247` 题文 `[:500]` 截断修）保证「**组装**披露 == 用户**实际看到**」——没修则用户因截断只看到部分成员、门却按全集放行 → **知情同意假成立**。
- **∴ 串联依赖**：完整知情同意 =「凭证==组装披露」(凭证层守门) **串联**「组装披露==用户实际看到」(展示层修:247)。两 diff 可分离实施，但**逻辑串联、缺一环链断**——**展示层修是凭证层守门"三者恒等"真成立的前置**，非并列可选。守门测试注释须点明「本测试只保证组装侧恒等，用户侧完整送达依赖 :247 截断修复」。

### 6.5 守门测试（4 道）+ 实施域
- **T1 折叠正确性**：凭证 `folded_members` 恰等于 `fold[rep]` 组装成员（防引擎偷塞用户没看到的案）；
- **T2 集合判定过门**：折叠成员经 `aid in rec["folded_members"]` 过门（599838 反向：真答成员放行）；
- **T3 截断免疫**：大折叠组全 aid 清单不被 `[:500]` 截断丢（599838 根因锚，凭证层）；
- **T4 展示送达**（展示层 diff 配套）：题面披露成员经 :247 修复后完整送达用户侧（串联链下半环）。
- **实施域纯 Py-Eng**：`nodes.py`（代表题 dict 加 folded_members）+ `ask_user/__init__.py:247`（记字段 + 展示层截断修）+ `verifiability_tool.py:415`（集合判定）+ T1-T4。**无 TUI 渲染改动**。消费面 1写1读（ask_user:244 写 / verifiability_tool:407 读），035413/记忆管线不读。
- **③=设计红线 F 不可选**（门读 pre-signal 的 folded_into=可伪造）；**②=次优**（粒度成员→rep 下移）。

### 6.6 A 前提实证确认（分叉归约点，解 Theory↔TUI-Eng 读法冲突）
Theory 静态读疑「V8 折叠应答不落 ask_user_answers.jsonl → A 前提存疑」。**亲读 `engine_tool.py:26-47` `_panel` 定论**：
- **第 35 行 `out = ask_user.func(payload)`**——_panel **调 ask_user 工具**，写点 :244 在 **ask_user.func 内部**（event.wait 后），不在 _panel 体内。Theory「_panel 30 行内无写点」字面对但**漏跟这层调用**（写深一层）；**TUI-Eng 链路 …→_panel→ask_user.func:35→:244 正确**。→ **V8 折叠应答确落 ask_user_answers.jsonl，A 前提成立**。
- **folded_members 流通**：`_panel:33` payload 剥 `_` 前缀键 → `folded_members`（无 `_`）穿过 → 到 ask_user.func → 改 :247 记它。
- **非交互自动安全**：headless 下 `_panel` 返 `{_non_interactive:True}`（:38/:40），ask_user.func 在非交互早返（ask_user:196-206）**早于 :244** → 不落日志 → 无假凭证。**A 的 non_interactive 抗伪自动具备**（无需 B 那样显式护栏）。

**结论**：分叉归约点的实证落在 A——载体在 V8 路径非空、非交互自动安全。**定 A，凭证=ask_user_answers.jsonl（V8 经 _panel:35 落）**。Theory 的 F 豁免二分（外部信号门控的引擎写入=合法凭证，类比 lint）留作理论背景+B 后路，A 不依赖它。

### 6.7 辖区判据推论·门专用凭证的空间选择（Theory 定稿，判据本身推出 A 优于 B）
> 单源纯度（凭证进 facts）**只对业务态必需**（防显示漂移）；对**门专用凭证**（非业务态、单一消费者=门）**非必需**。post-signal 前提下，门专用凭证**留独立凭证路优于塞进 facts 单源**——塞进 facts 需靠「写点必 post-signal」的**隐形不变量**（时序承载抗伪的脆弱实现，无编译期守护，谁挪到 signal 前即破）；而独立凭证路（ask_user 工具内 `event.wait→write`）是**结构锁定的 post-signal**（wait 与 write 同函数体、顺序天然）。∴ B 把抗伪的时序约束下沉成需人守的隐形不变量，A 用结构锁定免除它——**A 更优不是工程妥协，是辖区判据的直接推论**。

**署名**：Py-Eng（工程实证：:35 写点/非交互自动安全/消费面 1写1读）+ Theory（理论根：辖区判据+串联知情同意链+本推论）**共署**。收敛路径诚实存档：③（门读 pre-signal facts，抗伪破）→ B（facts user_answered，单源纯度）→ **A（独立凭证路，结构锁定 post-signal）**——每步证据/判据夹出，A 是判据自指的解。**F 豁免二分**留作辖区判据理论注记（未来 facts 凭证场景可援），A 不依赖、不进主线。

### 6.8 Design 终审 = P + 三层分离（Design 边界勘定，修 6.4 的层次混淆）
**Design 终审 P**（team4_design_precheck.md §1.6）；准则 F 亲核不落 A（ask_user:232-251 在 `if not answers:return` 之后写=凭证路真实产物、非 facts 编辑路，符合 gates-on-credential-path）。4 点核全 P。

**关键勘定——三层须分清（我 6.4 把后两层混了）**：
1. **凭证层**＝`folded_members` **专用字段（全 aid）**——**不走 questions 的 `[:500]`、天然截断免疫**。门读它（集合成员判定）。**这是本 diff 的核心，599838 的解＝凭证从"题文后缀"挪到"专用字段"**。
2. **日志题文层**＝`ask_user:247` `[:500]` 截断的是**日志里的题文记录**（审计用）——与凭证**无关**（凭证在专用字段）。:247 修是审计完整性，**非本 diff 必需**、非凭证。
3. **TUI 渲染层**＝用户**屏幕所见**的成员披露——大 fold 组题面长可能被 TUI 面板截断（Design 面2② 同源）；**"用户真看全"是 TUI 渲染项，需 TUI-Eng/cmux 测，不进本 diff、非本 diff 验收条件**。

**修正后的测试（凭证层+门，纯 Py-Eng，本 diff 验收）**：
- **T1 折叠正确性**：凭证 `folded_members` 恰等于 `fold[rep]` 组装成员（防引擎偷塞）；
- **T2 集合判定过门**：`aid in rec["folded_members"]` 放行折叠成员（599838 反向）；
- **T3 凭证走专用字段**：断言 folded_members **不经 `[:500]`**（锁"凭证≠题文后缀"，防回归到 599838 病灶）。
- ~~T4 展示送达~~ **移出本 diff**：":247 日志写全"可选（审计）；"用户 TUI 看全"归面2② TUI 渲染批（TUI-Eng）。

**知情同意链的精确归属**（修 6.4）：凭证==组装披露(fold[rep])＝T1 守（纯 Py-Eng）；组装披露==用户所见＝**TUI 渲染**（面2②，非本 diff）。folding 语义（同 group_path+sig）保证成员同 intent，用户组级裁决语义覆盖全组——"看全每个尾号"是信息完整性（TUI 项），非逐案同意关键。

**本 diff 终定域**：`nodes.py`（代表题 dict 加 folded_members，源 fold[rep]）+ `ask_user/__init__.py:247`（_rec 记 folded_members 专用字段）+ `verifiability_tool.py:415`（子串→集合判定）+ T1/T2/T3。**无 TUI 改动**。:247 题文截断修 + TUI 渲染 = 面2② 独立批。**四关备**：Theory 共署 / Design P / 待 leader redline+亲跑+commit。
