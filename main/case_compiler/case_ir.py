"""测试用例编译器 IR（Intermediate Representation）。

single source of truth：脑图自然语言用例 → CaseIR → xlsx 行。

DSL 列语义（实证自跳转机框架 lib/test_xlsx.py，见 memory project_framework_dsl_contracts）：
  A=自动化ID(case 首行) B=优先级(首行) C=语句类型 D=描述 E=测试对象 F=方法
  G=数据 H=临时保存期望结果(输出存变量) I=输入变量

C 语句类型：0=不执行(说明)、1=通用前置(文件级)、2=赋值/普通起始、3=循环、≥4 递增。
同一步骤多行共享一个 C：仅首行写 C/D，后续行 C/D 留空。

一个 Step 对应一个逻辑步骤，含 1+ 个 Row（多 Row=同步骤多行，如一个配置步骤跟多个 check_point）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# E 列合法测试对象（实证 sdns_listener.xlsx 字典区 Q-U 列）
VALID_TEST_OBJECTS = {
    "APV_0", "APV_1", "check_point", "test_env", "time",
    "Seg0_tmp", "server231", "server232", "server213", "http_server_231",
}

# E=test_env 时 F 列合法主机名（conftest fixture）
VALID_TEST_ENV_HOSTS = {
    "routera", "routerb", "clientc", "clientd", "cliente",
    "server231", "server232", "server213", "console",
}

# E=check_point 时 F 列合法断言类型（lib/check_point.py）
VALID_CHECK_METHODS = {"found", "abs_found", "not_found", "found_times"}

# E=APV_* 时 F 列通用反射方法（APV_SSH 普通 method）
VALID_APV_METHODS = {
    "cmd_config", "cmds_config", "cmd_enable", "cmd", "array_config",
    "clear", "global_init",
}


@dataclass
class Row:
    """xlsx 一行（九列 A-I）。A/B 仅 case 首行有值；C/D 仅步骤首行有值。"""

    test_object: str = ""          # E
    method: str = ""               # F
    data: str = ""                 # G
    save_as: Optional[str] = None  # H（输出存变量名）
    input_var: Optional[str] = None  # I（引用变量名 / found_times 的 times）
    # 断言期望值溯源（red line：check_point 的 G 必须可溯源，不得 LLM 凭空编造）。
    # 取值：passthrough / author_intent / spec:rr|settle|loop / llm_unsourced / None（非断言行）。
    # 非 xlsx 列，只在 IR 内传递，供 W6 闸 + provenance.json 消费，emit 时丢弃。
    provenance: Optional[str] = None

    def is_check_point(self) -> bool:
        return self.test_object == "check_point"


@dataclass
class Step:
    """一个逻辑步骤：共享一个 C 语句类型 + 描述，含 1+ Row。"""

    stmt_type: int          # C：2/3/≥4（前置用 PreConfig）
    description: str        # D（仅首行）
    rows: list[Row] = field(default_factory=list)


@dataclass
class CaseIR:
    """单个测试用例。"""

    autoid: str                       # A（脑图原始 autoid；新用例由平台分配）
    priority: str = "P1"              # B
    title: str = ""                   # case 标题（来自脑图 module/描述）
    steps: list[Step] = field(default_factory=list)
    # provenance / 诊断
    source_module: str = ""           # 脑图模块路径
    source_text: str = ""             # 原文步骤
    expected: list[str] = field(default_factory=list)  # 脑图期望结果原文
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)
    # 精确 autoid 命中框架既验证语料的直转产物（最高保真）。
    # 为 True 时，三确定性变换（assertion-fix / rr-rewrite / settle）一律跳过——
    # 框架原件断言已上机验证，任何重写都是破坏（实证：rr_stats 拆散 IP-Hit 配对断言致 fail）。
    is_passthrough: bool = False

    def check_point_count(self) -> int:
        return sum(1 for st in self.steps for r in st.rows if r.is_check_point())


@dataclass
class FileIR:
    """单 feature 单 xlsx：一个文件级 C=1 通用前置 + N 个 case。"""

    feature: str                       # 输出文件名 stem
    author: str = "IST-Core"
    init_rows: list[Row] = field(default_factory=list)   # C=1 文件级前置
    cases: list[CaseIR] = field(default_factory=list)
    module: str = ""                   # smoke_test 子模块归属
    rejected: list[dict] = field(default_factory=list)   # 不可自动化清单
    questions: list[dict] = field(default_factory=list)  # 原始用例质疑


def _effective_whitelists(snapshot=None) -> tuple[set, set, set]:
    """解析生效白名单 (check_methods, test_env_hosts, generic_methods)。

    FIX-6 单一源收口：有 KP2 快照时**以快照为准**（框架真实能力），缺则回退本地默认。
    避免 case_ir 与框架四份重复白名单漂移。
    """
    if snapshot is not None:
        check = set(snapshot.check_methods) or set(VALID_CHECK_METHODS)
        hosts = set(snapshot.test_env_hosts) or set(VALID_TEST_ENV_HOSTS)
        generic = set(snapshot.generic_methods) or set(VALID_APV_METHODS)
        return check, hosts, generic
    return set(VALID_CHECK_METHODS), set(VALID_TEST_ENV_HOSTS), set(VALID_APV_METHODS)


def validate_row(row: Row, snapshot=None) -> list[str]:
    """良构校验单行（W5/F 值域）。返回违规说明列表（空=合法）。

    snapshot（KP2 CapabilitySnapshot）非空时，断言/主机/通用方法白名单以框架快照为准。
    """
    errs: list[str] = []
    e = row.test_object
    f = row.method
    check_methods, env_hosts, _generic = _effective_whitelists(snapshot)
    if e not in VALID_TEST_OBJECTS:
        errs.append(f"E={e!r} is not a valid test object")
        return errs
    if e == "check_point":
        if f not in check_methods:
            errs.append(f"E=check_point: F={f!r} is not a valid assertion type {sorted(check_methods)}")
        if f == "found_times" and not row.input_var:
            errs.append("found_times requires column I to specify times")
    elif e == "test_env":
        if f not in env_hosts:
            errs.append(f"E=test_env: F={f!r} is not a valid hostname {sorted(env_hosts)}")
    elif e == "time":
        if f != "sleep":
            errs.append(f"E=time: F must be sleep, got {f!r}")
    elif e in ("APV_0", "APV_1"):
        # 通用反射方法 或 中文意图（command_function_mapping）——意图由能力快照校验
        pass
    return errs


def validate_case(case: CaseIR, snapshot=None) -> list[str]:
    """良构校验单 case（W4 断言完备 + 行级）。snapshot 透传给行级校验（KP2 单一源）。"""
    errs: list[str] = []
    if case.check_point_count() == 0:
        errs.append(f"case {case.autoid} has no check_point — guaranteed fail on device (pass requires success>0)")
    for st in case.steps:
        for r in st.rows:
            for e in validate_row(r, snapshot):
                errs.append(f"case {case.autoid} step C={st.stmt_type}: {e}")
    return errs
