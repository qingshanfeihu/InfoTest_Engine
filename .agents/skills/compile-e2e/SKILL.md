---
name: compile-e2e
description: 用 cmux 驱动 infotest TUI 把一批用例完整编译成 excel 并抓屏核验全过程,CUT/有异议的诚实报原因,达标才提交。用户通过 /compile-e2e 调用。
disable-model-invocation: true
---

# compile-e2e

复刻你反复手打的那条闭环(history 里逐字重复 ≥6 次):**清数据 → cmux 驱动 infotest TUI 实跑 → 完整喂用例 → 抓屏看过程+结果 → CUT/有异议诚实报原因 → 通过才提交**。重点不是跑个命令看终态,是**看着它跑、抓每一步证据**。

## 何时用

要真机全流程验证一批用例(不是改代码后的窄测)。改了 ink/TUI 显示也走这个抓屏核验。

## 完成目标(Definition of Done)

1. 目标目录下**每一份**用例都产出 case.xlsx(不是大部分)。
2. CUT / 有异议 / 上机不通过的,**逐个诚实给原因**(脑图与手册冲突 / 疑似产品缺陷 / 断言无法溯源…),不粉饰、不声称通过。
3. 只有 1+2 都达到才认为可提交(提交走 `/ship-it`)。

## 执行步骤

前置:确认用例目录(默认 `workspace/inputs/automatic_case/`,或用户指定)。venv 见 `/run-tests`。

1. **清数据 + 重启**:走 `/restart-regen`(清 `workspace/outputs` 旧产物 + 干净重启 infotest)。不清会读脏 checkpoint 续跑(`runtime/compile_engine_checkpoints.db` 清 outputs 清不掉)。

2. **cmux 驱动 TUI**(遵 AGENTS.md「优先 cmux 直接抓屏,勿后台轮询」):
   - `cmux read-screen --surface <id>` 实时抓屏;`cmux send` / `cmux send-key` 输入。
   - 流式开(交互看过程);模型按当前 `IST_MODEL`。
   - 把用例喂给 istcore,让它跑 V6 编译引擎(`compile_engine_run` 一次到底:编写→欠定问用户→合并→上机→归因→只重编 fail 子集→不动点)。

3. **抓过程证据**(边跑边看,不只看终态):
   - 明细全量在 `runtime/logs/compile_evidence.<pid>.live.log`——`ls -t runtime/logs/compile_evidence.*.live.log | head -1` 找当前的,`tail -f` 看。
   - 结构化事件在同 stem 的 `.events.jsonl`(fork/tool/engine_tick/progress)。
   - 欠定问用户(interrupt 挂起)时如实转达、带用户决策 resume。

4. **核验产物**:每份 case.xlsx 走 `/excel-spotcheck` 抽查断言质量(observe-then-assert / 溯源)。

5. **诚实结账**:逐份报状态(PASS / CUT+原因 / 疑似缺陷)。达标才提示可 `/ship-it`。

## 注意

- **别只看终态就下结论**——你多次要求「看过程有没有问题」,draft/grade 会带偏(实证 prompt「不要被 draft 和 grade 带偏,就是找他们俩的问题」)。
- **别后台轮询抓屏**——不可靠、易看漏看错(AGENTS.md 明令 + 记忆 cmux-drive-interactive-tui)。
- **上机互斥**:别同 turn 连发多次 digest,设备床会并发互踩(记忆 verify-loop-convergence-stoploss);引擎已有锁,别绕。
- CUT 不是失败要藏,是要**诚实归类**;连续同签名 fail 走确定性止损/escalate,不硬试。
