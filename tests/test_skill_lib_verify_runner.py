"""verify_runner 离线单测。

覆盖：正常 passed/failed、无显式判决、各类结构化错误（缺目录 / 缺脚本 / 缺函数 /
返回非 dict / verify 抛异常 / 脚本 import 期炸 / 路径穿越被拒）、确定性（同输入同输出）、
以及「反模式被拒绝」——逐 case 硬编码的 verify_script 应被识别为 failed（不静默放行）。

注意：技能库包 `__init__.py` 当前 import 平行开发中的 schema.py（尚未落地），直接
`import main.case_compiler.skill_lib.verify_runner` 会触发父包 __init__ 失败。故本测试
用 importlib 从文件路径**直接加载** verify_runner.py，绕开父包，保持模块独立可测。
"""

from __future__ import annotations

import importlib.util
import textwrap
from pathlib import Path

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "main" / "case_compiler" / "skill_lib" / "verify_runner.py"
)


def _load_runner():
    spec = importlib.util.spec_from_file_location("_vr_under_test", str(_MODULE_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vr = _load_runner()


def _make_skill(tmp_path: Path, body: str, name: str = "verify.py") -> Path:
    """在 tmp 下造一个技能目录，写入 verify 脚本。返回技能目录。"""
    skill_dir = tmp_path / "askill"
    skill_dir.mkdir(exist_ok=True)
    (skill_dir / name).write_text(textwrap.dedent(body), encoding="utf-8")
    return skill_dir


# ── 正常路径 ─────────────────────────────────────────────────────────

def test_passed(tmp_path):
    skill = _make_skill(tmp_path, """
        def verify(payload):
            return {"passed": payload.get("x") == 1, "x": payload.get("x")}
    """)
    out = vr.run_verify_script(skill, {"x": 1})
    assert out["ok"] is True
    assert out["status"] == "passed"
    assert out["error"] is None
    assert out["result"] == {"passed": True, "x": 1}
    assert out["script"] == "verify.py"
    assert out["skill_dir"] == str(skill.resolve())


def test_failed(tmp_path):
    skill = _make_skill(tmp_path, """
        def verify(payload):
            return {"passed": False, "reason": "mismatch"}
    """)
    out = vr.run_verify_script(skill, {"x": 999})
    assert out["ok"] is True
    assert out["status"] == "failed"
    assert out["error"] is None
    assert out["result"]["reason"] == "mismatch"


def test_no_explicit_verdict_is_informational_pass(tmp_path):
    """verify 返回 dict 但无 passed 字段 → status=passed + note 标注。"""
    skill = _make_skill(tmp_path, """
        def verify(payload):
            return {"observed": 42}
    """)
    out = vr.run_verify_script(skill, {})
    assert out["ok"] is True
    assert out["status"] == "passed"
    assert "note" in out
    assert out["result"] == {"observed": 42}


def test_custom_script_and_func_name(tmp_path):
    skill = _make_skill(tmp_path, """
        def check_it(payload):
            return {"passed": True}
    """, name="check.py")
    out = vr.run_verify_script(skill, {}, script_name="check.py", func_name="check_it")
    assert out["status"] == "passed"
    assert out["script"] == "check.py"


# ── 结构化错误：永不抛裸异常，永不静默放行 ─────────────────────────────

def test_missing_skill_dir(tmp_path):
    out = vr.run_verify_script(tmp_path / "nope", {})
    assert out["ok"] is False
    assert out["status"] == "error"
    assert out["error"]["type"] == "SkillDirNotFound"


def test_missing_verify_script(tmp_path):
    skill = tmp_path / "empty_skill"
    skill.mkdir()
    out = vr.run_verify_script(skill, {})
    assert out["ok"] is False
    assert out["error"]["type"] == "VerifyScriptNotFound"


def test_missing_verify_function(tmp_path):
    skill = _make_skill(tmp_path, """
        def something_else(payload):
            return {"passed": True}
    """)
    out = vr.run_verify_script(skill, {})
    assert out["ok"] is False
    assert out["error"]["type"] == "VerifyFunctionMissing"


def test_verify_not_callable(tmp_path):
    skill = _make_skill(tmp_path, """
        verify = 123
    """)
    out = vr.run_verify_script(skill, {})
    assert out["ok"] is False
    assert out["error"]["type"] == "VerifyFunctionMissing"


def test_verify_returns_non_dict(tmp_path):
    skill = _make_skill(tmp_path, """
        def verify(payload):
            return True
    """)
    out = vr.run_verify_script(skill, {})
    assert out["ok"] is False
    assert out["error"]["type"] == "VerifyContractViolation"


def test_verify_raises(tmp_path):
    skill = _make_skill(tmp_path, """
        def verify(payload):
            raise ValueError("boom")
    """)
    out = vr.run_verify_script(skill, {})
    assert out["ok"] is False
    assert out["status"] == "error"
    assert out["error"]["type"] == "VerifyExecutionError"
    assert "boom" in out["error"]["message"]
    assert "ValueError" in out["error"]["traceback"]


def test_script_import_time_error(tmp_path):
    """脚本 import 期就炸（顶层语句异常）→ LoadError，不向上抛。"""
    skill = _make_skill(tmp_path, """
        raise RuntimeError("import time explosion")
        def verify(payload):
            return {"passed": True}
    """)
    out = vr.run_verify_script(skill, {})
    assert out["ok"] is False
    assert out["error"]["type"] == "LoadError"
    assert "import time explosion" in out["error"]["traceback"]


def test_syntax_error_in_script(tmp_path):
    skill = _make_skill(tmp_path, """
        def verify(payload)
            return {}
    """)
    out = vr.run_verify_script(skill, {})
    assert out["ok"] is False
    assert out["error"]["type"] == "LoadError"


# ── 路径安全：穿越被拒（只 import skill_dir 内文件） ──────────────────

@pytest.mark.parametrize("bad", ["../verify.py", "sub/verify.py", "..", "a\\b.py"])
def test_path_traversal_rejected(tmp_path, bad):
    skill = _make_skill(tmp_path, "def verify(p): return {'passed': True}\n")
    out = vr.run_verify_script(skill, {}, script_name=bad)
    assert out["ok"] is False
    assert out["error"]["type"] == "BadScriptName"


# ── 确定性：同输入同输出 + 隔离（不吃缓存、互不干扰） ────────────────

def test_determinism_same_input_same_output(tmp_path):
    skill = _make_skill(tmp_path, """
        def verify(payload):
            return {"passed": payload["n"] % 2 == 0, "n": payload["n"]}
    """)
    a = vr.run_verify_script(skill, {"n": 4})
    b = vr.run_verify_script(skill, {"n": 4})
    assert a == b


def test_namespace_isolation_no_stale_module(tmp_path):
    """重写同名脚本后再跑，应反映新内容（不返回上次缓存的 stale 模块）。"""
    skill = _make_skill(tmp_path, """
        def verify(payload):
            return {"passed": True, "version": 1}
    """)
    first = vr.run_verify_script(skill, {})
    assert first["result"]["version"] == 1
    # 改写脚本
    (skill / "verify.py").write_text(
        "def verify(payload):\n    return {'passed': True, 'version': 2}\n",
        encoding="utf-8",
    )
    second = vr.run_verify_script(skill, {})
    assert second["result"]["version"] == 2


def test_no_sys_modules_pollution(tmp_path):
    """加载后不在 sys.modules 留下技能模块（隔离命名空间）。"""
    import sys
    skill = _make_skill(tmp_path, "def verify(p): return {'passed': True}\n")
    vr.run_verify_script(skill, {})
    leaked = [k for k in sys.modules if k.startswith("_skill_verify_")]
    assert leaked == []


# ── 反模式被拒绝：逐 case 硬编码的 verify_script 不静默放行 ────────────

def test_anti_pattern_hardcoded_autoid_fails_on_other_case(tmp_path):
    """红线 1：逐 case 硬编码的 verify（只对 778012 返 True）在换一批用例时必须 failed。

    runner 本身不做反模式静态检测（那是 quality_contract 的活），但它如实执行确定性
    verify：一个「只认 778012」的脆弱脚本，喂别的 autoid 就会 failed——证明 runner
    不会把「换一批用例就不成立」的伪通过静默放行。
    """
    skill = _make_skill(tmp_path, """
        def verify(payload):
            # 反模式范本（被测对象的对照组）：逐 autoid 硬编码分支
            return {"passed": payload.get("autoid") == "778012"}
    """)
    # 归纳来源那条 case：硬编码恰好命中
    hit = vr.run_verify_script(skill, {"autoid": "778012"})
    assert hit["status"] == "passed"
    # held-out 同类 case：硬编码立刻露馅 → failed，runner 如实报告不放行
    miss = vr.run_verify_script(skill, {"autoid": "593516"})
    assert miss["ok"] is True
    assert miss["status"] == "failed"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
