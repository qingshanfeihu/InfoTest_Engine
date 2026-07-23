---
name: engine-verify-loop
description: 引擎问题标准处理循环——真机上机(cmux+Langfuse+fastlog 三通道监控)→log+Langfuse 取证定位→查理论(更新+反向质疑)→对照设计(冲突审计+反向质疑)→修复实现(带测试)→清理临时数据→cmux 重新上机验证,循环到无问题。用户说「跑真机验收/引擎出问题了/按验收循环走」时用,也可 /engine-verify-loop 调用。
---

# engine-verify-loop

2026-07-11 yzg 三轮验收(run5→run7→run8)沉淀的完整方法论。核心构造:**每个问题走
「实证→理论→设计→实现→再实证」全链,每层都过反向质疑(对抗),不许跳层**。跳层的
实证代价在案:跳过理论层直接加检测器=人写规则膨胀(233 案第一轮分析被用户三连否);
跳过对抗直接落地=¥96 整批回退。

## 循环骨架(顺序是硬的;单步内自由判断)

### 0. 起跑与监控(cmux 三通道)

- **清理先行**:防 grep/read 旧产物——`workspace/outputs/` 全清(先 `mv` 备份到
  `runtime/backups/<批名>_<轮次标签>_<日期>/`,含批目录+全部 per-case 散目录),删
  `runtime/compile_engine_v8_checkpoints.db`(全新跑)或保留(断点续跑,二选一想清楚)。
- **僵尸确杀**:relaunch 前 `pgrep -f bin/infotest` 必须为空;Ctrl-C×2+Ctrl-D 不死就
  kill,kill 后终端跑 `printf '\033[?1000l\033[?1002l\033[?1003l\033[?1006l'; stty sane; clear`
  (鼠标跟踪残留会把后续键入变成 zsh 乱码——实证)。僵尸跨写事实流的取证:facts 的 `_pid`。
- **标准启动**:`LANGFUSE_TIMEOUT=30 IST_JUMPHOST_HOST=<床> infotest`(cmux send 后必须
  补 send-key enter——send 不带回车)。
- **监控三通道**:①cmux read-screen 抓屏(面板/卡片/footer);②fastlog Monitor
  (`runtime/logs/compile_evidence.<PID>.live.log`,按 TUI PID;过滤词只留**阶段级**:
  床态/呈报/采信/判例/挂起/交付/归因/问询/Traceback——emit 自纠与上机心跳是噪声,
  实证会淹没通知);③Langfuse REST(dotenv 经 `main.langchain_env` 加载,env 值可能带
  引号要剥;时间窗按 **UTC** 换算——本地 JST-9,踩过未来窗口查零条的坑)。
- **产出计数 Monitor**:`ls workspace/outputs/2036*/case.xlsx | wc -l` 轮询,每 5 案报
  一次——footer 的「产出」计数是引擎收账时点,盘上 xlsx 才是硬证据。
- **遇 ask 面板停手**,通知用户控制 pane;别替用户答题。

### 1. 取证定位(log + Langfuse)

- 事实优先序:`facts.jsonl`(引擎真理)> `last_run.json`(设备回显原文)> fastlog(过程)
  > 屏幕(展示层)。归因结论看 `_attribution`,面板原文看 `outputs/<aid>/ask_panel.json`。
- Langfuse 拿三样:fork 均价(↑tokens/latency,对照基线 run5=256k、修后目标 ≤300k)、
  编写期总账(对照上轮同时点)、工具首发成功率(参数层整调拒 vs 工具内门反馈要分开数——
  前者是通道 bug,后者是设计内自纠)。
- **人工复探**:引擎报的设备状态要上设备核实(`_do_probe` 只读),别信转述——床态误报
  (探针失败当残留)与真污染(vlan 挂错口)都靠 show 原文分辨。
- 定位判据:挖到**能解释全部现象**的根因才停(共性 vs 个案分清;是不是本次引入 git 对照)。

### 2. 理论层(THEORY_k_state_machine.md)

- 先问:**理论覆盖这个形态吗?** 三种结局:①已覆盖且机制在——找机制为什么没触发
  (枚举缺口?判断层未触发?);②理论有缺口——补公理/推论,写明实证锚;③设计误用了
  理论——记冲突点。
- 更新后**必须做反向质疑**(对抗检查):列攻击→逐条裁决(站住/修正/毙)→产出写进
  §x.x.x 对抗表(样式见 §2.6.5/§2.7.4-5)。攻击面至少含:回归风险、token/性能、
  安全边界(INV-9/沙箱)、收敛性(ask 爆炸/漂移失锚)、样本量与幸存者偏差。
- 铁律:**别发明场景检测器**——「每类新问题人加一条规则」=人写规则自动化(公理
  (22)-(25):判断开放、入库门闭合;资源规则可加,场景规则禁止)。证据索引(§10)补行。

### 3. 设计层(DESIGN_v8_engine.md)

- 对照更新后的理论做**冲突审计**:逐条「现设计→理论裁定→修订方向(落地序位置)」
  (样式见 §12.1 X1-X10)。同时维护**不动清单**(§12.2)——防修订被误读为推翻一切。
- 设计更新同样过反向质疑,产出回写(样式见 R3:X10 等价类限定/空窗期路线)。
- 落地序纪律:效率债先还→省钱构件先行→每步独立验收(Langfuse 对照数字)→**任一步
  数据不支持即停**。

### 4. 实现层(薄片纪律)

- ¥96 教训:切薄逐片,每片全量测试绿+(涉及行为时)真机小批验收后才提交;prompt/md
  改动过红线四问(零写死命令/期望值溯源/自由度分层/参考文档只写机制)。
- 触及 compile 链/agents 定义 → 派 redline-reviewer;触及沙箱/凭据 → security-reviewer。
- eval-first:要防的回归先固化成机读断言(金标准 fixtures 用真机事实流——run7/run8
  的 facts.jsonl 已入 tests/fixtures 可回放)。
- md 提示的预算:C 层每坑 ≤2 句、并入既有段不开新段(§5.5 prompt 减法纪律)。

### 5. 再实证(回到 0)

- 清理→重跑→同一监控;验收看**对照数字**(上轮同时点 token/¥/拒绝次数/归因均价),
  不只看「跑通了」。单点数字标注为单点(样本=1 不是区间)。
- 修复未生效/新问题显形→回到 1;干净通过→提交+更新任务台账+(有跨会话价值时)写
  长期记忆。

## 产物落点速查

| 层 | 文件 | 形态 |
|---|---|---|
| 理论 | docs/THEORY_k_state_machine.md | 公理/推论+对抗表+证据索引行 |
| 设计 | docs/DESIGN_v8_engine.md | 冲突审计表+落地序+验收数字 |
| 实现 | main/ + tests/ | 代码+机读断言(金标准回放) |
| 运行数据 | runtime/backups/<批>_<标签>_<日期>/ | facts/last_run/报告全量 |
| 跨会话经验 | memory/(经 /remember) | 非本仓可推导的教训 |
