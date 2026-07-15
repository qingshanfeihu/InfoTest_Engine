# 回归线索 #3 — bed_gate 干净床误报「分区配置残留」

> 只读取证(报根因+修法方向,不改代码)。主源:`workspace/outputs/{yzg,dongkl}/bed_before.json`、
> `bed.py`/`run_case.py`/`nodes.py` 代码 + git 溯源。
> **结论:既有 bug(2026-07-02 起),非 S3 本次引入;是探针元输出被当床内容的又一同型坑。**
> 标注:〖数据事实〗盘上/代码铁证;〖我的判断〗据证据推断;〖修法〗方向建议。

---

## 1. 观测症状

〖数据事实〗yzg 真机启动 bed_gate(床态体检)报「测试床上仍有残留:**分区配置残留**(1 项引擎不认识、
不敢动)」。用户明确:**床本来就没残留** → 探针误报。

〖数据事实〗`bed_probes.segments` 即「分区配置」通道(`domain_grammar.json:257-260`,
provenance「CLI Ch10/Multi_Segment_Spec rev1.2;探通道③残留分区」)。

---

## 2. 根因(行级铁证 + 机制链)

### 2.1 铁证:yzg 的 `segments.lines` 装的是探针的**兜底说明文字**,不是床上的配置

〖数据事实〗对比两 run 的 `bed_before.json`,**唯一差异在 `segments` 段**:

```
dongkl/bed_before.json:  "segments": {"failed": false, "lines": []}          ← 干净
yzg/bed_before.json:     "segments": {"failed": false, "lines": [<1 行>]}     ← 报残留
```

〖数据事实〗yzg `segments.lines` 那唯一 1 行,逐字＝`run_case.py:_annotate_if_empty_probe` 的注入 note
(首「(note: an empty echo does not mean the p…」／尾「…do not keep re-probing emptiness.)」):

> (note: an empty echo does not mean the probe failed — at compile time the device is in a
> **clean state** (the framework wipes config after every case), so statistics/session/state
> data exist only while a case is executing and always probe empty here. …)

**这是探针对空回显附的时机语义提示,不是设备上的分区配置。** 床是干净的,探针空回,dev_probe 好心
附了一段"空是正常的"说明——这段说明被 bed_gate 当成了「1 项引擎不认识、不敢动」的残留。

### 2.2 机制链(代码级,全部确认)

〖数据事实〗三跳把探针的自解释文字变成「残留」:

1. **bed 探针走注 note 的 dev_probe 路**:`nodes.py:_probe_fn`(line 39-41)`→ _do_probe(cmd)`;
   `_do_probe`(run_case.py:336/358)`return _annotate_if_empty_probe(...)`。**bed_check / bed_snapshot 的
   probe_fn 就是这个 `_probe_fn`**(`nodes.py:204/244` 等)。
2. **空探针被追加 note**:`_annotate_if_empty_probe`(run_case.py:269-295)——剥标头/裸提示符后 body 为空
   即在回显尾部拼接那段 note。clean 床上 `show segments` 类探针本就空 → 追加 note。
3. **bed_check 把 note 当残留**:`bed.py:bed_check`(563-594)对 `segments` 通道——
   - `_probe_failed(note)` = **False**(note 非 error、无 `status:error`、无 `% Invalid`+`^`,line 484-504);
   - body 过滤器(578-592)只滤**结构性元数据**(`===`/`---`/`command:`/`status:`/`key=val`/裸提示符/
     冒号收尾头/header_patterns)——**散文 note 一条都不匹配** → 留作 body;
   - `body.strip()` 非空 → `findings.append({"kind":"segments","detail":<note>})`(line 593-594);
   - 末尾 `foreign and not ours → needs_ask=True`(603-604)→ 弹「分区配置残留」问询。

〖我的判断〗**这是「探针元输出被当床内容」的又一同型实例**——bed.py 里已记录两个同类坑并各打了补丁,
但都没覆盖 note 这一种:
- `bed.py:494-498`:「105 床 SSH 挂死被报成"分区配置残留"」(error banner 泄漏)→ 已加 `error:` 首行门;
- `bed.py:569-572`:「`% Invalid input` 单次瞬态被报成"分区配置残留"」→ 已加 `% Invalid`+`^` 门 + 复探;
- 记忆 `[[bed-baseline-face-no-autorestore]]`:探针截断致基线地址误判漂移 → 同型。
- **本次 note 泄漏是第三种**:既不是 error、不是 % Invalid、不是截断,是 dev_probe **主动附加的合法说明**,
  三个既有门全部不认它,body 过滤器也不滤散文 → 漏成幽灵残留。

---

## 3. 是否本次引入?——**否,既有 bug,自 2026-07-02**

〖数据事实〗git 溯源:
- `_annotate_if_empty_probe` 函数**及其在 `_do_probe` 里的调用**同在 `0e65ff0c`(**2026-07-02** feat(verify))
  落地;此后该函数/调用**无逻辑改动**(仅 `86089265` 2026-07-09 把 note 文本英文化)。
- bed 探针 `_probe_fn → _do_probe` 接线自 `da888beb`(V8 首版床态门)就存在。
- **当前工作树** `run_case.py`/`bed.py`/`nodes.py`(`_probe_fn` 段)/`domain_grammar.json` **零未提交改动**
  (`git status` 干净);HEAD `2a03b16f` 及近期提交均未碰 probe 段。
- S3 本次足迹在 `batch_tools.py`/`nodes.py` broken 段,**与 bed 探针 note 路不重叠**。

〖我的判断〗**非 S3、非本轮实现引入**。这条链从 2026-07-02 就在,只是需要「探针恰好空回 ∧ 回显不带
抑制 note 的元数据行」两个条件同时满足才现形,平时被掩盖。

## 4. 为何 dongkl 干净、yzg 误报?——两个过滤器对 `key=val` 元数据行判据分歧

〖数据事实〗`_annotate_if_empty_probe` 的"空"判据(run_case.py:277-286)与 bed 的
`_clean_probe_body`(bed.py:172-181)/`bed_check` body 过滤器(bed.py:578-592)**不一致**:

| 行类型 | `_annotate` 判为 | bed 过滤器判为 |
|---|---|---|
| `===`/裸提示符/`(no output)` | 空(跳过) | 空(跳过) |
| **`key=val` 元数据行**(如 `host=<IP>  mode=show`) | **内容(保留!)** | **空(跳过,bed.py:585)** |

〖我的判断〗**分歧点就在 `key=val` 行**(bed.py:583-585 注释明确实录过 `host=IP mode=show` 组合行):
- 探针回显**带** `host=… mode=show` 头时 → `_annotate` 见 body 非空 → **不注 note** → bed_check 也滤掉该头 →
  `lines=[]` → **床干净(dongkl 形态)**;
- 探针回显**不带**该头(或换了通道/mode)时 → `_annotate` 见空 → **注 note** → bed_check 不滤散文 note →
  **报残留(yzg 形态)**。

〖我的判断〗所以误报是**间歇的**(取决于 FastMCP 探针那次带不带 key=val 头),dongkl 恰好躲过、yzg 撞上。
这间歇性本身正是根因的表征:**note 是否出现由 `_annotate` 的"空"定义决定,而它与 bed 的"空/残留"定义
不是同一把尺** —— note 在 A 尺下生成、被 B 尺当残留判读。

〖数据边界〗两 run 的 `bed_before.json` 只存**清洗后的 lines**,不存探针原始回显,故「dongkl 那次带了
key=val 头」是从两过滤器差异+结果反推的〖我的判断〗,非直接抓到原始回显。但机制闭合:note 仅在
`_annotate` 判空时出现,而 yzg 出现了 note ⇒ 那次 `_annotate` 判空 ⇒ 回显无被 `_annotate` 视作内容的行。

---

## 5. 修法方向(不改代码,列选项 + 倾向)

根因＝**bed 残留检测把 dev_probe 的自解释 note 当成床内容**。三条修法,按根治程度:

**〖修法 A(倾向,根治·分离关注点)〗bed 探针走「不注 note」的原始回显。**
- `note` 是**给 worker 编译期看的便利提示**(别对空统计反复重探,OBS-15);**bed_check 是机器消费者**,
  要的是**原始探针事实**,不需要也不该吃这段人话提示。
- 落点:`run_case.py:_do_probe` 加 `annotate: bool = True` 参数(默认 True 保 worker 行为不变);
  `nodes.py:_probe_fn`(bed 专用)调 `_do_probe(cmd, annotate=False)`。
- 优点:最小、精确、**零关键字匹配**、根除 note 进 bed 路;不动 bed 过滤器、不影响 worker 侧 note。
- 回归锚:`tests/ist_core/compile_engine_v8/test_bed_gate.py` 加——`_probe_fn` 对空探针的回显**不含**
  `_annotate_if_empty_probe` note;`bed_check` 对空 `segments` 探针 **findings 无 `kind==segments`**。

**〖修法 B(兜底·防御纵深)〗bed 过滤器识别并剥掉 dev_probe 的 note。**
- 若 A 之外还要一道防线:`_clean_probe_body` + `bed_check` body 过滤把「dev_probe 空探针 note」也当元数据剥掉。
- 注意红线:**别 grep note 首句关键字当白名单**(脆、note 文本会变)。宜从 `run_case` 导出一个 note 结构
  标记(如给 note 加一个稳定的机读前缀 sentinel,两处共用常量),bed 按 sentinel 剥——机读契约而非关键字。
- 定位:与 A 互补(A 治源、B 治漏网),但单用 B 是治标(note 仍被生成、只是被下游剥)。

**〖修法 C(顺带·消间歇性,非根治)〗对齐两个"空"过滤器。**
- 让 `_annotate_if_empty_probe` 的 body 判据与 `_clean_probe_body` 一致(补 `key=val` 剥除)。
- 只消除 dongkl/yzg 的间歇差异,**不解决 note 泄漏本身**(真空床仍会注 note、仍被 bed 当残留)——
  不能单独用,可作 A 的附带清理(两把尺本就该同源)。

〖我的倾向〗**A 为主**(分离 worker 便利提示 vs 机器残留事实,根治且零关键字);**C 附带**(两过滤器同源,
消除间歇性,降低这类分歧再生);B 视稳健度要求可选。

---

## 6. 回归锚建议(供实现阶段)

放 `tests/ist_core/compile_engine_v8/test_bed_gate.py`(已存在,扩之):

1. **note 不进 bed 残留**(核心负例):注一个空回显的 `probe_fn`(clean 床)→ `bed_check` 的 `findings`
   **不含** `kind==segments`(或任何通道)的残留项、`needs_ask` 不因此为 True。
2. **note 抑制条件不脆**:分别注「带 `host=IP mode=show` 头的空探针」与「纯裸提示符的空探针」两种回显 →
   两种都**不产残留 finding**(现状:后者会误报——正是 yzg)。
3. 若采修法 A:`_probe_fn`(bed 专用)对空探针回显**不含** `_annotate_if_empty_probe` note 文本;
   worker 侧 `dev_probe`/`_do_probe(annotate=True)` **仍含** note(不回归 OBS-15 的 worker 便利)。
4. 信号纯度门:断言 bed 的 note 剥除**不靠 note 首句关键字白名单**(若走修法 B,靠共用 sentinel 常量)。

〖修法归属提示〗落点 `run_case.py`(`_do_probe` annotate 参数)+ `nodes.py:_probe_fn`(bed 专用传 annotate=False)
——与 S3 的 batch_tools/nodes broken 段**不重叠**,但都碰 `nodes.py`,实现时与 S3 协调避撞车(不同函数区)。

---

## 7. 理论层对账(THEORY_infra_reliability + THEORY_k s₀)

### 7.1 分诊:理论缺口 / 设计误用 / 实现 bug?——**实现层丢对象链(§18.14 病),非理论缺口**

〖数据事实〗理论对「床态残留」说得很清楚,且**这一层正是它管的**:
- `THEORY_infra_reliability §T4`(资源泄漏):「segment `.conf.tmp` 尸体;SDNS 配置文件残留」→
  检测手段明写「**bed_check 残留探针**+cleanup_refs」。segments 探针就是 T4 的 `.conf.tmp` 尸体检测器。
- `THEORY_infra_reliability §T1`(执行序依赖):污染者改共享态未复位、受害者读**脏态**;床账快照 diff=
  污染的**状态侧**检测。
- `THEORY_k`(§18.14 对象链合取,`docs/DESIGN_v8_engine.md:1582-1601`):**「实现层系统性地在机械化理论时
  丢掉『对象链』合取,退化成过程/构造近似」**——表里明列 `s₀ 谓词(I6) | 理论要求「读脏态(床对象状态)」|
  实现丢成「命令文本/IP 交集(过程共享)」| 假象=persist/L2L3 假阳`。

〖我的判断〗**分诊结论:不是理论缺口,是「实现丢对象链」(§18.14 同一根病)**——
- 理论要求的谓词是**对象存在**:「床上存在一个非己方的脏配置**对象**(残留 segment / `.conf.tmp` 尸体 /
  他人 synconfig 态)」。
- `bed_check` 实现的谓词是**文本非空**:`bed.py:562` 注释自白「引擎只做『非空即报』」——把「残留对象存在」
  退化成「探针回显 body 非空」。**这是过程/文本近似替代对象事实**,正是 §18.14 的病。
- note 泄漏是这个退化的**最新实例**:探针的自解释文字(过程 artifact)满足了「文本非空」代理谓词,却
  对应**零残留对象**。§18.14 早预言「delta 聚集在 intent→object 接缝」——此处 delta 聚集在
  「残留对象存在」→「探针文本非空」的接缝。

### 7.2 与 §18.14 s₀ 排固定基础设施 IP、[[bed-baseline-face-no-autorestore]] **同型确认**

〖我的判断〗三者是**同一病的三个实例**——床态谓词都吞了一个**非对象的 artifact**,因为用了文本/过程代理:

| 实例 | 吞进的非对象 artifact | 代理谓词误判 | 已有修法 |
|---|---|---|---|
| §18.14 S1(s₀ 排固定基础设施 IP) | 固定基础设施 IP(基线,非脏态) | 「命令/IP 交集」当脏态共享 | 排固定 IP,要对象真脏 |
| [[bed-baseline-face-no-autorestore]] | 探针**截断**(读窗串位丢地址) | 残缺基线当「漂移」 | snapshot_only 纯 added 不自动删 |
| **本次(note 泄漏)** | 探针**自解释 note**(过程提示) | 「文本非空」当残留对象 | (待修:A/B/C) |

〖我的判断〗**同型且互补**:前两者在 **diff/漂移路径**(snapshot before/after、s₀ 配对),本次在
**残留检测路径**(`bed_check` findings)——同一床态检测的两个子机制都栽在「文本/过程代理 ≠ 对象事实」。
`bed.py` 已为「error banner(105 床)」「`% Invalid` 瞬态」各补过**协议级门**(`_probe_failed` 扩充),
但那两次补的是「**探针失败**的 artifact」;note 是「**探针成功但空**」的 artifact,落在 `_probe_failed`
与 body 过滤之间的缝——**三个既有门都在防『失败 artifact』,没人防『空回显的善意注释』**。

〖理论更新指向(不改,只指)〗§18.14 对象链回补表可**增一行**:
`bed_check 残留谓词 | 理论「残留对象存在」| 实现「探针 body 非空」| 假象=探针元输出(note/banner)假残留`
——与既有五行同构,是「实现丢对象链」的第六个已实证接缝。

---

## 8. 设计层:bed_gate 该报什么、不该报什么

〖数据事实〗`DESIGN_v8_engine.md:116-127` bed_gate 设计意图:
- **该报**(残留对象):版本锚差、**残留 segment 与 `.conf.tmp`**、synconfig peer/ha 同步态、本机磁盘残留
  配置文件——都是「床上客观存在的、跨案/跨批遗留的配置对象」。
- **判据分层**:己方未复原产物(床账内)→ 自动恢复;**非己方残留一律 ask 不动手**(INV-9,line 126:
  「床是共享的,别人的现场不能清」)。

〖我的判断〗**「1 项引擎不认识、不敢动」措辞背后的判据链**(`bed_check` 末段 601-604):finding 满足
①body 非空 ∧ ②非 maintenance_explained ∧ ③不在床账(非己方)→ 判 foreign 残留 → INV-9 → ask 不清。
note 把这三关**全部假过**:①它非空(但不是对象);②`annotate_maintenance` 要行内有身份 token(接口名/IP)
才可解释,note **零身份 token** → 不被解释、留 foreign;③床账里当然没有 note 的配对 → 非己方。
→ 于是「引擎不认识(非己方)、不敢动(INV-9)」——**措辞本身是对的,错在把探针注释误当成了『别人留在床上的配置对象』**。

〖我的判断〗**设计意图没错、INV-9 没错**——错在设计→实现的**代理谓词选择**:用「文本非空」代理「残留对象
存在」。设计该补一句**边界声明**:残留检测的输入必须是**探针的原始设备事实**,探针自身的元输出
(注释/横幅/失败文本)不是床内容——这正好落到修法 A(bed 走原始探针)。

---

## 9. 系统性风险:会不会误导其它批 / 诱发连锁?

〖数据事实〗bed_gate 是**每批启动都跑**的 host 级体检(`nodes.py:204/279` 在批前 bed_check)。

〖我的判断〗**风险范围:潜伏于每一批**,不是 yzg 个案——凡「segments 探针空回 ∧ 该次回显不带抑制 note 的
`key=val` 头」的批,启动即误报。dongkl 那批只是恰好带了头躲过。

〖我的判断〗**连锁分析(分两类,好在都被 INV-9 挡住了破坏面)**:
1. **不会触发破坏性清理**(关键安全结论):note 判 foreign → INV-9 → **只 ask 不动手**。且 note **零身份
   token** → `own_writes_by_command`/`entity_gate`/`restore_mechanical` 都要身份 token 才生成恢复命令 →
   **note 派生不出任何删除/恢复命令**。所以**不会**像 `[[destructive-command-killed-beds]]` 那样级联到毁灭
   性清床。这条护栏(实体门 + 机械逆放要 token)恰好兜住了本 bug 的破坏面。
2. **会造成的实际连锁(非破坏但有害)**:
   - **每批启动多一道假问询**:受影响批在 bed_gate 停下问「分区配置残留」,用户须驳回——**假 ask,
     摩擦成本**,违 (26) 非法 ask 精神(信息本应「床本干净」)。
   - **告警疲劳 → 掩盖真 T4 残留**(最隐蔽的害):segments 探针的**本职**是抓 `.conf.tmp` 尸体
     (T4 资源泄漏)。它反复误报「分区配置残留」→ 用户学会条件反射驳回 →**某天真有 `.conf.tmp` 尸体时
     也被顺手驳回**。**误报侵蚀的是这个 T4 检测器自己的可信度**——把「本该救命的告警」训练成「狼来了」。
   - **快照 diff 噪声**:note 也进 `bed_snapshot`(bed_before/after)。若 before/after 两次的 `key=val` 头
     presence 不一致 → `bed_diff` 把 note 当 added/removed 漂移 → 批后报告混入幽灵「本批漂移」(报告噪声;
     但零身份 token → 不被恢复,不破坏)。
   - **对 broken/ask 的级联**:bed_gate 是**批级 host 门**,不直接把某个 case 判 broken;它诱发的是**批级
     启动 ask**。故不会像线索#2 那样进 case 级 ask 路由,但会占用一次批级问询预算、并在非交互/自动挂起
     场景下**误把整批卡在启动体检**上。

〖我的判断〗**系统性结论**:破坏面被 INV-9 + 实体门兜住(不会毁床),但**可用性与检测器可信度**受实打实
损害——每批潜在假 ask + 训练用户忽视真 T4 残留。**优先级:MAJOR-可用性**(非 BLOCKER-安全,因无破坏路径),
建议随修法 A 一并根治,并把「探针元输出 ≠ 床内容」立成 §7.2 那条对象链回补锚,防第四种同型 artifact 再钻缝。

STATUS: done
