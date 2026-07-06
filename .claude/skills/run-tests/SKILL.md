---
name: run-tests
description: 用本机正确的 venv 跑 pytest,自动规避两个本地坑(venv 不在仓库内、smoke_test 目录收集报错)。可只跑与改动相关的窄子集。用户通过 /run-tests 调用。
disable-model-invocation: true
---

# run-tests

在本机正确地运行 InfoTest Engine 的测试。封装两个本地约定:

1. **venv 在仓库外** —— 必须用 `~/.venvs/infotest-engine/bin/python`,不是 `.venv/bin/python`(SynologyDrive 云盘存不了 venv,详见项目记忆 venv-location)。
2. **跳过坏目录** —— `knowledge/framework/mirror/smoke_test` 收集会 `ModuleNotFoundError`,用 `--ignore` 排除,否则整轮 collection 中断。
3. **云盘 I/O 慢** —— 全量收集要 ~5 分钟。**默认优先按改动文件跑窄子集**,只有用户明确要全量时才全跑。

## 用法

- `/run-tests` —— 跑与当前 git 改动相关的测试(默认,快)。
- `/run-tests <路径或表达式>` —— 跑指定文件/目录/`-k` 表达式。
- `/run-tests all` —— 全量(慢,~5min+,确认用户真的要)。

## 执行步骤

设 `PYBIN="$HOME/.venvs/infotest-engine/bin/python"`。

1. **确定范围**
   - 有参数 → 直接作为 pytest 目标。
   - 无参数 → `git status --porcelain` 找改动的 `*.py`;若改的是 `tests/` 下文件直接跑它们;若改的是 `main/` 源码,映射到 `tests/` 下对应路径(如 `main/case_compiler/confidence_f.py` → `tests/case_compiler/test_confidence_f.py`),找不到对应就跑该模块所在的 `tests/<子包>/` 目录。
   - `all` → 跑整个 `tests/`。

2. **运行**(始终带 `--ignore` 和 `-p no:cacheprovider`):
   ```bash
   "$PYBIN" -m pytest <目标> \
     --ignore=knowledge/framework/mirror/smoke_test \
     -p no:cacheprovider -q
   ```
   - 标了 `slow` / `e2e` 的真调测试默认不主动跑,除非用户要求(需对应 API key)。

3. **报告**:passed/failed 数 + 失败用例的简短定位。失败时给出最小复跑命令。

## 注意

- 不要用裸 `pytest`:`pytest.ini` 的 `testpaths=main/tests` 与实际测试目录 `tests/` 不一致,裸跑会跑错地方。
- 不要把测试产物写进 `knowledge/`(只读)。
