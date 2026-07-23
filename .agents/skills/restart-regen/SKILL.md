---
name: restart-regen
description: 干净重启 infotest TUI + 清理旧产物,为重新编译/重跑做准备(清鼠标跟踪咒语、清 workspace/outputs、避开脏 checkpoint 续跑)。用户通过 /restart-regen 调用。
disable-model-invocation: true
---

# restart-regen

你每轮实验前反复做的准备动作(history ×15+:「清理刚刚的数据,重新在 cmux 中测试」)。封装两个坑:退不干净留鼠标跟踪、清了 outputs 没清 checkpoint 导致脏续跑。

## 执行步骤

1. **干净退出当前 TUI**:优先 Ctrl-C + Ctrl-D 干净退出;若只能 kill,退出后清鼠标跟踪:
   ```bash
   printf '\033[?1000l\033[?1002l\033[?1003l\033[?1006l'; stty sane; clear
   ```
   (不清会残留鼠标上报序列刷屏)

2. **清产物**(按用户要重跑的范围):
   - 编译产物:`workspace/outputs/<批名>/`。
   - **脏 checkpoint**:重编同批名前清 `runtime/compile_engine_checkpoints.db`,否则读上轮 checkpoint 续跑、全局轮次带高会误判(commit c35c0726 复盘);或干脆换批名干净起跑。
   - **别动** `knowledge/`(只读)和 `workspace/inputs`(用户上传)。

3. **重启 infotest**:`infotest`(TUI)或 `infotest --server`(Web)。批量非交互跑用 `IST_LLM_STREAMING=0`(防网关空 chunk 死挂)。

4. 找当前进程的证据日志:`ls -t runtime/logs/compile_evidence.*.live.log | head -1`。

## 注意

- 这是给 `/compile-e2e` 的前置步骤;单独跑测试不需要它,走 `/run-tests`。
- 清数据前跟用户确认范围(批名),别误清别的批次产物。
