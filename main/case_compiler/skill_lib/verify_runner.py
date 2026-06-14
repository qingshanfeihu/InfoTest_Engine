"""技能 verify_script 执行引擎（纯离线，确定性）。

每条归纳/手写技能附带一个 `verify.py`，里面有一个 `verify(payload) -> dict` 纯函数，
对技能产物做**确定性校验**（pass/fail bit）。本模块负责把那个文件**作为模块 import**
进来、调用其 `verify`、把结果与任何异常都包成**结构化** dict 返回。

设计纪律（见 plan 「verify_script 离线不可跑（禁止）」+ 四红线）：
- **只 import 文件，不 exec 任意字符串**：走 `importlib.util.spec_from_file_location`
  从磁盘文件加载，绝不 `exec(<某段字符串>)`。
- **隔离命名空间**：每次加载用唯一模块名，exec 期间临时注册 `sys.modules`，结束即移除，
  不污染全局、不返回 stale 缓存（同输入同输出，重复调用互不影响）。
- **确定性**：runner 自身输出不含时间戳 / 随机；同 `(skill_dir, payload)` → 同结果
  （结果的确定性最终取决于 verify.py 本身，runner 不引入抖动）。
- **失败结构化**：缺文件 / 加载失败 / 缺函数 / verify 抛异常 / 返回非 dict —— 一律
  返回带 `status="error"` + `error{type,message,traceback}` 的 dict，绝不向上抛裸异常，
  也绝不静默放行。

返回契约（`run_verify_script` 永远返回 dict）::

    {
      "ok":      bool,             # 脚本是否成功跑完并返回合法 dict
      "status":  "passed"|"failed"|"error",
      "result":  dict | None,      # verify() 的原始返回值（ok 时）
      "error":   None | {"type","message","traceback"},
      "skill_dir": str,            # 解析后的技能目录
      "script":  str,              # 实际加载的脚本相对名
    }

判决（status）来源：
- 任何加载/执行/契约错误 → ``"error"``（``ok=False``）。
- verify() 正常返回 dict 时，读其 ``"passed"`` 字段：True→``"passed"``、False→``"failed"``、
  缺失→``"passed"`` 并在 ``note`` 标注「无显式判决」（脚本跑通即视为信息性通过）。
"""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import sys
import traceback
from pathlib import Path
from typing import Any, Optional

# 默认脚本 / 函数名（与 plan 「skills/*/verify.py 的 verify(payload)」约定一致）
DEFAULT_SCRIPT_NAME = "verify.py"
DEFAULT_FUNC_NAME = "verify"

# 唯一模块名计数器：保证每次加载得到全新模块对象（不吃 sys.modules 缓存）。
# 仅用于命名去重，不进入返回值，故不破坏「同输入同输出」契约。
_load_counter = itertools.count()


def _error(skill_dir: str, script: str, err_type: str, message: str,
           tb: str = "") -> dict:
    """构造结构化错误返回（status=error，ok=False）。"""
    return {
        "ok": False,
        "status": "error",
        "result": None,
        "error": {"type": err_type, "message": message, "traceback": tb},
        "skill_dir": skill_dir,
        "script": script,
    }


def _verdict(result: dict) -> tuple[str, str]:
    """从 verify() 的返回 dict 推 (status, note)。

    读 ``passed`` 字段：True→passed、False→failed、缺失→passed+note（脚本跑通无显式判决）。
    """
    if "passed" not in result:
        return "passed", "verify() 未返回 passed 字段，按脚本跑通视为信息性通过"
    return ("passed" if result["passed"] else "failed"), ""


def _load_verify_callable(verify_path: Path, func_name: str):
    """把 verify.py 作为隔离模块 import，返回 (callable, None) 或 (None, 结构化错误三元组)。

    错误三元组 = (err_type, message, traceback)。只 import 文件，不 exec 字符串。
    隔离：唯一模块名 + exec 期间临时注册 sys.modules + finally 移除。
    """
    # 唯一模块名：路径 hash + 自增计数（确定性命名，仅作 sys.modules 键去重）
    digest = hashlib.sha1(str(verify_path).encode("utf-8")).hexdigest()[:12]
    mod_name = f"_skill_verify_{digest}_{next(_load_counter)}"

    spec = importlib.util.spec_from_file_location(mod_name, str(verify_path))
    if spec is None or spec.loader is None:
        return None, ("LoadError", f"无法为 {verify_path} 构造 import spec", "")

    module = importlib.util.module_from_spec(spec)
    # exec 期间需在 sys.modules 注册（部分模块在执行时自引用 / dataclass 解析需要），
    # 结束后立即移除以保持隔离、不污染全局。
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException as exc:  # noqa: BLE001 — 加载期任何错误都要结构化捕获
        return None, ("LoadError", f"{type(exc).__name__}: {exc}",
                      traceback.format_exc())
    finally:
        sys.modules.pop(mod_name, None)

    func = getattr(module, func_name, None)
    if func is None:
        return None, ("VerifyFunctionMissing",
                      f"verify.py 缺少 `{func_name}` 函数", "")
    if not callable(func):
        return None, ("VerifyFunctionMissing",
                      f"`{func_name}` 不可调用（type={type(func).__name__}）", "")
    return func, None


def run_verify_script(
    skill_dir: Any,
    payload: Any,
    *,
    script_name: str = DEFAULT_SCRIPT_NAME,
    func_name: str = DEFAULT_FUNC_NAME,
) -> dict:
    """加载 ``skill_dir/script_name`` 并调用其 ``func_name(payload)``，返回结构化结果。

    参数：
      - ``skill_dir``  技能目录（str / Path）。
      - ``payload``    传给 verify() 的输入（通常是技能产物 / case IR 片段，任意可序列化对象）。
      - ``script_name`` 脚本相对名（默认 ``verify.py``）。必须是单层文件名，不含路径分隔符 /
        ``..``（防目录穿越）。
      - ``func_name``   入口函数名（默认 ``verify``）。

    返回：见模块 docstring 的「返回契约」。**永不抛裸异常**；所有失败均落 status=error。
    """
    skill_dir_str = str(skill_dir)

    # 闸 1：script_name 必须是干净的单层文件名（不许穿越出 skill_dir）
    if not script_name or "/" in script_name or "\\" in script_name or ".." in script_name:
        return _error(skill_dir_str, script_name, "BadScriptName",
                      f"script_name 必须是 skill_dir 内的单层文件名，拒绝：{script_name!r}")

    try:
        base = Path(skill_dir).resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        return _error(skill_dir_str, script_name, "BadSkillDir",
                      f"无法解析 skill_dir：{type(exc).__name__}: {exc}")

    if not base.is_dir():
        return _error(str(base), script_name, "SkillDirNotFound",
                      f"技能目录不存在或不是目录：{base}")

    verify_path = (base / script_name).resolve()
    # 闸 2：解析后必须仍在 skill_dir 内（双保险，挡符号链接 / 残留穿越）
    if base != verify_path.parent:
        return _error(str(base), script_name, "BadScriptName",
                      f"脚本解析后逃出技能目录：{verify_path}")
    if not verify_path.is_file():
        return _error(str(base), script_name, "VerifyScriptNotFound",
                      f"verify 脚本不存在：{verify_path}")

    func, load_err = _load_verify_callable(verify_path, func_name)
    if load_err is not None:
        err_type, message, tb = load_err
        return _error(str(base), script_name, err_type, message, tb)

    # 调用 verify(payload)，捕获任何异常
    try:
        result = func(payload)
    except BaseException as exc:  # noqa: BLE001 — verify 任意异常都结构化返回
        return _error(str(base), script_name, "VerifyExecutionError",
                      f"{type(exc).__name__}: {exc}", traceback.format_exc())

    # 契约：verify 必须返回 dict
    if not isinstance(result, dict):
        return _error(str(base), script_name, "VerifyContractViolation",
                      f"verify() 必须返回 dict，实得 {type(result).__name__}")

    status, note = _verdict(result)
    out = {
        "ok": True,
        "status": status,
        "result": result,
        "error": None,
        "skill_dir": str(base),
        "script": script_name,
    }
    if note:
        out["note"] = note
    return out
