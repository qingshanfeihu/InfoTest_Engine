# 回归#2 取证 — ask 面板没触发的路由 bug(yzg run,pid 45545)

> 只读调查。结论:**非我 S3 改动引入**(git 铁证),是**既有的活锁/饥饿**——非收敛 broken 案让 `live>0` 恒真,把 7 个 awaiting_user 案的 gather→ask 永久挡在门外。

## 一、实证根因(数据 + 路由模拟)

### 1.1 现象
- yzg 26 案:17 pass@delivery、2 fail@delivery、7 needs_decision(欠定)。
- 2 个 fail 案(667986/668059)reflow 后子集复跑 = **not_run@subset → broken(broken_subtype=None,undetermined)**。
- 引擎 `outcome=delivered_with_labels` 收口,7 欠定案被标「等待你的决定」**但从未真问**(engine_summary `decisions` 只有一条 `bed_gate: proceed`,ask answered=1 全是 bed_gate)。

### 1.2 铁证:路由模拟(用最终 facts.jsonl 跑真路由函数)
```
view counts: {subset_verified: 17, awaiting_user: 7, broken: 2}
_after_reconcile(final_state) = "merge"        # live = 0+17+2 = 19 > 0
_gather_or_close(final_state) = "ask_decision" # n_awaiting_user=7 > 0
```
`_after_reconcile`(graph.py:98-102):
```python
live = n_authored + n_subset_verified + n_broken   # = 19
if live > 0: return "merge"        # ← 命中,恒回 merge
return _gather_or_close(s)          # ← 永远到不了(gather 会 ask 那 7 案)
```
**reconcile 只要有 subset_verified 或 broken 案就恒回 merge,`_gather_or_close` 永远不可达 → 7 欠定案永不被 gather 问询。**

### 1.3 为什么 live 不收敛(双重卡死)
- **主因**:2 broken 案(not_run)每轮进 `n_broken` → `live>0`。它们**复跑救不了**(not_run=案没跑成,再跑还是没跑成),`n_broken` 恒 ≥2。
- **加剧**:broken 案走**子集复跑**(merged #73/#76,ctx=subset,volume `6557feb7`),把 `current_volume` 从交付卷 `1e562569` 改成子集卷 → 17 个已 pass@delivery 的案**卷指纹失配**(`F.deliverable` 要 verdict.volume==current_volume)→ 从 deliverable **降级回 subset_verified**,永不沉淀成交付态 → `n_subset_verified` 也恒 17。两头都不让 live 归零。

### 1.4 为什么 streak≥2 护栏没救场
`reconcile` 的 broken 连击护栏(nodes.py:989-1012)按**同一 artifact** 连续 broken/not_run 计数,≥2 才 escalated(移出 broken→live 归零)。但:
- reflow 每轮换新 artifact → streak 每 artifact 只 1;
- 本 run 每案只 1 条 not_run@subset(run 在第 2 次同 artifact not_run 前结束)→ streak=1 → **没升级** → 没从 live 移出。

### 1.5 收口的确切触发(次要,存疑不影响根因)
live 恒 >0 → reconcile→merge→run 循环。recursion_limit=200(engine_tool.py:353)没打满(仅 ~3 merge 轮),故非递归上限。live.log 末尾停在 broken 案 reflow+「上机运行 10s/600s」——**收口很可能来自最后一次 run/merge 的非 ok 相位**(`_after_run`/`_after_merge` 的 `else→closing` 不走 `_gather_or_close`,run 错误出口见 nodes.py:918/928)。但**无论哪条收口边,7 欠定案都到不了 ask**——因为 reconcile 阶段就已恒回 merge,gather 从不可达。

## 二、是不是我 S3 改动引入的?——**否**(git 铁证)

`git show HEAD:graph.py` 对照 `git diff`:
- `live = n_authored + n_subset_verified + n_broken; if live>0: return "merge"` **在 HEAD(我 S3 之前)就是这样**——我只改了这行的**注释**(`broken=没跑成`→`broken=协议级分不清`),代码字节没动。
- 我唯一的功能新增:`or n_broken_errored > 0`(attribute 边)——yzg 的 2 broken 是 **undetermined(broken_subtype=None)**,`n_broken_errored=0`,**该条件恒 False、完全惰性**。
- 我 S3 对 undetermined broken 的处置 = 原样落 `n_broken`→live→merge,**与改动前逐字节等价**。

∴ **回归#2 与 S3 无因果**。团队观察「基线 broken=0 没触发、当前 broken=2 触发」成立,但触发源是「出现了非收敛 broken 案」这一**数据条件**,踩中的是**既有** live-gate 活锁,非我新代码。(S3 反而对 errored/blocked 子类**改善**了此问题:它们不再落 `n_broken`→不再无谓占 live。)

## 二·5、理论层(THEORY_k)——(44) broken 没有 (40) 的终止性证明【这是缺口】

**结论:理论缺口(非 S3 实现、非设计误用)。** 精确定位:

- **(40) §2.12.1 有终止性论证**(line 674-677):fail 案七类处置「每案有限步到终态——**每次处置严格降秩(污染源数量或未决类数单调减)**」。这条**严格降秩**正是「山穷水尽才 ask」安全的**理论前提**:每个 fail 案有限步收敛 ⇒ live 必归零 ⇒ gather 必触发 ⇒「欠定必问」(I1)得满足。
- **(44) §2.12.3b broken 吸收态**(2026-07-13 补,**晚于 (40)**)只给了 broken 的**局部**语义(⊥_err、≙ ERROR、不计签名/不深归因、**处置=复跑**),**没有对应的降秩终止性证明**。要命的是:**复跑一个 not_run 案 → 还是 not_run,秩没降**(污染源/未决类数不变)。所以 broken 的「复跑」处置**不在 (40) 的降秩映射内、无有限步到终态保证**。
- broken 的事实终止靠 reconcile 的 streak≥2 escalated(nodes.py:989-1012),但它 (a) 不是 (44) 的组成、(b) 是**计数**不是**降秩**、(c) per-artifact + reflow 重置 → 脆(yzg 实证:streak 恒 1、never 升级)。
- **未理论化的交互**:「欠定必问」⟸「batch 到 gather」⟸「所有非欠定 work 终止」。(40) 覆盖 fail 的终止,**(44) broken 的终止悬空** → 这条 liveness 链在 broken 处断裂。这是 **C14 型缺口**:(44) 从 668030 空真自推了 broken 局部语义,却**没回头把 (40) 的终止性覆盖延伸到它**。

**直接回答团队问①**:S3 的 pyATS broken 子分类**不是**让「broken 吸收态与欠定必问冲突」的原因——冲突**先于 S3**,根在 (40)↔(44)↔「欠定必问」的 liveness 三角不完整(理论缺口)。

## 二·6、设计层(DESIGN §14-R4 / §16)——「批末必有聚合点」被断言但未强制

- **§14-R4**(line 634)明写:「**不可接受=整批停在中间态**」「单案待人不得阻塞全批——欠定案标挂起继续跑其余,问询批末汇总」。yzg bug **正是 R4 的红线现象**:整批停在中间态(7 欠定案卡 awaiting_user、既没批中挂出也没批末聚合就 closing)。
- **§16**(line 757-759)设计意图:「**面板批中即挂出、批末必有聚合点**——人在随时可答;人不在批不停」。但**实现没兑现这条不变量**:①「批中即挂出」需路由到 ask_decision/ask_contradiction,live-gate 让 reconcile 恒回 merge、永不挂出;②「批末必有聚合点」被**多条绕过 `_gather_or_close` 的 closing 边**架空(见二·7)。
- **团队问②(S3 是否破坏「awaiting_user 在 closing 前必被 gather」)——否,但也没补上**:S3 的 errored/blocked 子态路由到 attribute(reflow,有轮次封顶→cap_reached→escalated,**是降秩、会终止**)/ ask(env 呈报,用户解),**它们其实把这两个 broken 子类拉进了 (40) 式的终止性**(errored≈自污染者出口、blocked≈真环境出口)。所以 S3 **不破坏**不变量、反而**部分修补**了 (44) 的终止缺口。**但 undetermined broken(not_run/stale,正是 yzg 的 2 案)S3 没碰**——仍「处置=复跑」、仍靠脆 streak → **缺口残留,恰是 yzg 触发点**。∴ S3 中性偏改善,但没根治。

## 二·7、系统性风险(团队问③)——「欠定必问」对**所有**终态都不稳,不止 broken

枚举 graph.py 里**所有到 closing 的边**,标注是否过 `_gather_or_close`(过=欠定会被问;绕=欠定被吞):

| 边 | 条件 | 过 gather? |
|---|---|---|
| `_after_reconcile`:93 | phase_status==error(INV-2 残差/last_run 不可读) | **绕→吞** |
| `_after_run`:88 | phase_status!=ok(device_busy/digest 无 last_run/error) | **绕→吞** |
| `_after_merge`:84 else | phase_status∈{error,device_busy} | **绕→吞** |
| `_after_ask_contradiction`:126 | 零实答(非交互/面板取消)∧ n_ask_contradiction>0 | **绕→吞** |
| `_after_bed`:45 | bed_blocked(续跑批可能已有 awaiting_user) | **绕→吞** |
| `_after_ask_decision`:76 | ask 后无 pending/authored(仍有未答欠定时) | **绕→吞** |
| `_after_reconcile`:103 / `_after_merge`:83 / `_after_diagnose`:117 / `_after_author`:68 / `_after_ask_contradiction`:131 | live==0 正常收敛 | 过→问 ✓ |

**结论:NO——「欠定必问」不是被强制的不变量,只是 happy-path(干净收敛到 live==0)的副产品。** 任一**硬错误**(reconcile/run/merge error)、**ask 零答**、或**非收敛 live**(broken/failed/subset 卷 churn)在有 awaiting_user 时都会**吞掉欠定问询**。broken 只是其中一个触发器(且是 yzg 实际踩中的),`n_failed` 长期不收敛、设备 busy、last_run 采集断裂等**同样**会吞。这是**面比 broken 宽得多的系统性洞**。

## 三、修法方向(三层,读-only,待团队/DESIGN 定夺)

根因是**未理论化的 liveness 张力**:「山穷水尽才 ask」(live==0 才 gather)默认「所有 work 有限步终止」,而 (44) broken 无终止证明 + 多条 error 边绕过 gather → 「欠定必问」失守。三层对症:

**A. 理论层(补 (44) 的终止性,延伸 (40))**:给 broken 一个**降秩终止**处置,纳入 (40) §2.12.1 的满射+严格降秩框架。undetermined broken 的复跑必须**有界**:同 case(跨 reflow)复跑/重编计数 ≥N 仍 not_run/broken → 转 escalated(或缺陷候选)——这**是一次降秩**(未决类数 −1),终止性即恢复。S3 已给 errored(→reflow,自污染者式降秩)/blocked(→env,真环境式降秩)做到了;**只差 undetermined broken 这一类**补终止出口。理论上写清:「(44) broken 的复跑处置受 (40) 终止性约束——复跑预算耗尽 = 强制降秩到终态」。

**B. 设计层(把「批末必有聚合点」变成真不变量)**:§16 声称「批末必有聚合点」,但二·7 那 6 条 error/零答/bed 边**绕过** `_gather_or_close`。设计不变量应是:**任何到 closing 的边,在 closing 前必先 flush awaiting_user**(有欠定→先 gather 呈报或显式落「因硬错误未问」事实,禁静默吞)。机械形态:把 `_gather_or_close` 上移为 **closing 的前置门**(所有 `return "closing"` 改成 `return _flush_then_close(s)`,内部:n_awaiting_user>0 → ask_decision,否则 closing)。这样即便 reconcile/run/merge 硬错误,欠定也先被问/被如实记账,呼应 §18.2 fail-open 清算(式③:不静默)。

**C. 实现层(治 yzg 的直接触发 + 加剧因)**:
- **liveness 守卫**:streak 护栏从 **per-artifact** 改 **per-case**(跨 reflow 累计 broken/not_run),或 broken 复跑加轮次封顶(复用 reflow 的 `max_rounds`+granted)——落地 A 的降秩。
- **卷指纹隔离**:broken 子集复跑不改 delivery 卷 current_volume(或 deliverable 绑「该案自己的 delivery 卷」),消掉 17 pass 案被反复降级的假 live(治二·3 加剧因)。

**倾向 A+B 为主**(B 是**面向全系统性洞**的治本:不止救 broken,连 error/零答/bed 吞并一起堵;A 让 broken 有确定终止),C 落地 A、顺带清卷 churn。B 需与「不打扰」调和:flush 只在**已到 closing 决策点**(确已山穷水尽或硬停)才触发,不改「批中不打断兄弟案」。

## 四、回归锚建议(供实现阶段,三层各一)
```
# tests/ist_core/compile_engine_v8/test_gather_ask.py
def test_awaiting_user_not_starved_by_persistent_broken():   # C:治本触发
    # 7 needs_decision(未答)+2 broken(undetermined,复跑≥N轮)+17 subset_verified
    # 断言:路由收敛到 ask_decision,不是 merge 死循环/静默 closing
def test_awaiting_user_flushed_before_error_closing():        # B:系统性不变量
    # 有 awaiting_user 时,reconcile/run/merge 硬错误 → 仍先过 gather(或落显式未问事实),不静默吞
def test_broken_rerun_budget_terminates_per_case():           # A:终止性
    # 同 case 跨 reflow 复跑 N 次仍 broken → escalated(降秩到终态),live 归零
```

## 五、三层裁决速览(团队三问)
| 团队问 | 结论 |
|---|---|
| ① 理论:S3 broken 子分类让吸收态与「欠定必问」冲突? | **否**。冲突先于 S3,是**理论缺口**:(40) §2.12.1 有 fail 终止性(严格降秩),(44) §2.12.3b broken(晚补)**无对应终止证明**,复跑 not_run 不降秩;(40)↔(44)↔「欠定必问」liveness 三角不完整(C14 型) |
| ② 设计:S3 破坏「awaiting_user 在 closing 前必被 gather」? | **否,但也没补上**。S3 的 errored/blocked 反而拉进 (40) 式终止(部分修补);**undetermined broken(yzg 的 2 案)S3 没碰、缺口残留**。真正的设计问题是 §16「批末必有聚合点」被 6 条 error 边架空,**从来就不是强制不变量** |
| ③ 系统性:「欠定必问」对所有终态都稳? | **否**。二·7 枚举:reconcile/run/merge 硬错误、ask 零答、bed_blocked、ask_decision 耗尽 6 条边全**绕过 gather**。broken 只是 yzg 踩中的一个触发器,failed 不收敛/设备 busy/采集断裂同样吞。**面比 broken 宽得多** |

## 六、数据事实 / 判断 / 待定 一览
| 项 | 类型 |
|---|---|
| `_after_reconcile(final)="merge"`、`_gather_or_close(final)="ask_decision"`(模拟) | 数据事实 |
| 2 broken 案 broken_subtype=None(undetermined)、not_run@subset | 数据事实 |
| live-check(含 n_broken)在 HEAD 即存在,我只改注释;n_broken_errored 对 yzg 恒 0 | 数据事实(git) |
| 6 条 closing 边绕过 `_gather_or_close`(行级枚举二·7) | 数据事实(源码) |
| (40) 有终止性降秩证明、(44) broken 无——理论缺口 | 我的判断(THEORY 行 674 / 727) |
| 根因=broken 无终止 → live 恒>0 饿死 gather;卷 churn 加剧;「批末必有聚合点」未强制 | 我的判断 |
| 修法 A 理论补终止 + B 设计 flush 前置门 + C 实现 per-case 守卫/卷隔离 | 待团队/DESIGN 定 |

STATUS: done
