# 合入窗口 #2 · redline/security 双扫裁定（leader 亲扫）

> 2026-07-20。评审型子 agent（redline-reviewer/security-reviewer 工具集无消息通道）报告无法回传——与 07-16 redline-check 同型陷阱，故本窗口由 leader 按同一清单亲扫 diff（`git diff HEAD`，含 4 新测试文件；ink 5 删除另经符号级验证）。

## Redline：PASS

- **零写死设备命令（产品代码）**：新增行中的 `ssl activate certificate vh1,prompt=YES` 等 5 处命令字样**全部位于 docstring 举证位**（`command_words`/`_attach_device_run`/`_strip_executor_kwargs` 的现象引证），非可执行字面量、非 LLM-facing prompt 资产、非指令性——与仓库「注释引实证」既有惯例一致。`#` 注释 0 命中。判据函数（`command_words`/`_strip_executor_kwargs`）纯形态、不认识任何具体命令（Py-Eng 预答核实）。
- **无 observe-then-assert 新面**：S2 挂载只累证据、签名以手册出处为准；歧义不挂（防「跑出来的样子」升格为语法）。
- **语言分层**：新增 LLM-facing 文本（footprint_lookup verbatim 标注行、emit 错误返回、build_source docstring）均英文；维护者注释中文。合规。

## Security：PASS

- **写落点**：唯一新增写调用为 `_write_json_atomic(ndp, …)`（needs_decision，workspace 既有白名单路径），复用 07-16 立的原子写件；无新写根、无出界。
- **日志零凭据**：新增 logger.warning 只携 autoid/path/异常摘要。
- **raw_invocation 存储面**（Theory P1-A）：worker 卷面 G 原文入 knowledge/footprints——**渲染层不展示已核实**（仅 `syntax_provenance` 标注行）；存前 apv_cmds 佐证 guard 已排下窗口规格（P1-A）。未来消费方须视其为未过证据门内容——已写入规格 v2.2。
- **脱敏机制（#58）**：新日志行不涉命令回显整段输出，不构成绕过。

## 附

- ink 5 删除：符号级零引用+模块路径串零命中+包导入自检（TUI-Eng 报告 + leader 复核双确认）。
- 权威 pytest 结果见 `runtime/logs/pytest_window2_authoritative.txt`（合入前置门）。
