---
name: excel-spotcheck
description: 用 openpyxl(仓库外 venv)抽查已编译 case.xlsx 的 check_point 断言质量——是否真覆盖目标行为、有没有 observe-then-assert、期望值是否溯源。只读。用户说「抽查/检查 excel 断言质量」时用,也可 /excel-spotcheck 调用。
---

# excel-spotcheck

复刻你的断言质量抽查模板(history 完整例)。只读,不改 xlsx。

## 三查(每个抽查 case 都过)

1. **真覆盖目标行为?** 断言是否命中脑图要验的那件事(如 rr/wrr/ga 命中第几权重 pool、会话保持是否真建条目),而不是只验「命令没报错」。
2. **有没有 observe-then-assert?**(项目铁红线)把设备 show 回显照抄成断言期望值 = 假验证。看期望值是不是从设备当次输出抄来的。
3. **期望值溯源了吗?** 溯源脑图预期或产品手册,不是 LLM 现编。

## 执行步骤

设 `PYBIN="$HOME/.venvs/infotest-engine/bin/python"`(云盘存不了仓库内 venv,详见记忆 venv-location)。

1. `"$PYBIN"` + openpyxl 读目标 case.xlsx,列出每行触发步 / 观测步 / check_point 断言。
2. 重点抽查:**wrr / ga 算法类**、**会话保持类**(你反复点名这两类最容易写坏)。
3. 对照**已知必崩/恒真断言族**——别自己重造判据,读 `main/case_compiler/structural_gate.py` 的 `lint_xlsx_case` / 崩溃门(锚点断言恒假、pattern 在来源步命令原文上恒真、零 check_point 恒 fail…)作为「坏断言长什么样」的权威闭集。
4. 每个抽查 case 打质量分 + 一句结论;总结整卷,可选写报告到 `docs/`。

## 注意

- 别把「命令/断言性质判定」退化成关键字白名单去 grep 命令文本——读 F 列方法(cmd_config/cmds_config)+ found/not_found 算子这类**结构化事实**判(记忆 compile-judgment-structural-not-strongdict;强字典会误杀金标准,GA-CUT 回归即此)。
- 上机才能回答的疑虑(回显格式/计数器行为/轮转起点)是 caveats,不等于断言坏(记忆 zhaiyq-run2-gates-effect)。
