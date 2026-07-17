"""测试基座公共夹具。"""
import os
import re
from pathlib import Path

import pytest

# F-Py-9b 已系统性隔离(下方 _isolate_outputs_to_tmp 全局 fixture monkeypatch _sh.project_root→tmp
# + 写侧编译工具收敛单一根 + 读侧测试改 _sh.outputs_root() 测试时求值)——**过渡债豁免集已清零、
# 门恢复零豁免**(Design 条件2 兑现:过渡态没摆烂成永久)。门现纯断言:任何再生即某测试未隔离写生产。
@pytest.fixture(scope="session", autouse=True)
def _no_new_test_pollution_in_prod_outputs():
    """污染门(硬拒·零豁免):session 收尾扫生产 workspace/outputs/ 无**本 session 新增**的伪键
    (非 18 位 autoid、非点开头)。F-Py-9b 系统性隔离后门零豁免——任何再生即某测试未隔离写生产
    (硬编码路径回归)。只断言新增、不碰既有真产物(yzg/dongkl 在 before 集)。"""
    root = Path(__file__).resolve().parents[1] / "workspace" / "outputs"
    before = {p.name for p in root.iterdir()} if root.is_dir() else set()
    yield
    if not root.is_dir():
        return
    new = {p.name for p in root.iterdir()} - before
    bad = sorted(n for n in new if not re.fullmatch(r"\d{18}", n)
                 and not n.startswith("."))
    assert not bad, (
        f"测试污染生产 workspace/outputs/ 新增伪键: {bad} —— 某测试未隔离写生产路径(硬编码路径回归);"
        "补该测试用 _sh.outputs_root() 求路径(走全局 _isolate_outputs_to_tmp fixture 落 tmp)。")


@pytest.fixture(autouse=True)
def _isolate_outputs_to_tmp(tmp_path, monkeypatch):
    """F-Py-9b-2(D1 零豁免全局隔离):把 workspace/outputs 写隔离到 per-test tmp——monkeypatch
    `_sh.project_root`→tmp_path,则 emit_xlsx/batch_tools/引擎全部 outputs 写随之落 tmp
    (F-Py-9b-1 写侧已收敛到 `_sh.project_root()` 单一根)。

    安全依据(linchpin,F-Py-9b-2 已 de-risk):全库 33 处 `sh.project_root()` 全喂
    outputs/runtime 引擎态路径、**零喂 knowledge/data 读**(knowledge 走独立 parents[N],不经
    project_root)——故全局 patch 只隔离 outputs+runtime、不破 knowledge 读。
    真数据读者 test_fail_signatures 已快照固化读 tests/fixtures/、不经 project_root。
    既有自 patch `_sh.project_root` 的测试(如 test_batch_compile_tools):其显式 setattr 后置、
    覆盖本 autouse,兼容。测试若需在 tmp 下预置 outputs 文件,用 `_sh.outputs_root()` 求路径(测试时)。"""
    from main.ist_core.compile_engine_v8 import _shared as _sh
    monkeypatch.setattr(_sh, "project_root", lambda: tmp_path)


@pytest.fixture(autouse=True)
def _provenance_optional_for_legacy_tests(monkeypatch):
    """存量测试聚焦各自的门/结构语义,不逐个补 provenance——统一走可选模式。

    provenance 必传门(V4 步骤0)的专项覆盖在 tests/ist_core/tools/
    test_provenance_mandatory.py:那里显式 delenv 后验证拒绝/放行两侧,
    本夹具不会稀释它。
    """
    if "IST_PROVENANCE_OPTIONAL" not in os.environ:
        monkeypatch.setenv("IST_PROVENANCE_OPTIONAL", "1")
