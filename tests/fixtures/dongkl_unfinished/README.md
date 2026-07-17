# dongkl unfinished attr_evidence 快照 fixture

**快照自** `workspace/outputs/dongkl/unfinished/<autoid>/attr_evidence.json`，**2026-07-18 固化**（F-Py-9b-2）。

3 案（203031753342778012 / 203031753342778072 / 203031753781593573）是 `_fail_signatures` 提取逻辑的**活标本**——778072 为主标本（唯一真 Fail 汇总形态被收、节头假行/Success not_found 出局的病灶实证）。

**为何固化**：`test_fail_signatures.py::test_real_dongkl_cases_reextraction_equals_fail_lines` 原读生产区 `workspace/outputs/dongkl/`（不入 git），依赖「生产数据在盘」——这次 outputs 清理/隔离一旦清掉 dongkl 即崩（或误进 tmp）。固化为提交进 git 的 fixture 后，测试恒读本目录、脱离生产数据存在性依赖（消灭脆弱耦合）。

每个 `attr_evidence.json` 含 `causality` + `device_context`（设备逐步执行回显），测试对其做 `_fail_signatures` == 参照实现的逐案等值校验。**字节保真自生产**（未改内容）。
