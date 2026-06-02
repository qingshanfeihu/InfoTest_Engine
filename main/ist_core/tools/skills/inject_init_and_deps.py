"""qa_inject_init_and_deps: 机械注入 init 步骤和功能依赖。

LLM 完成语义拆分后，本工具负责纯机械操作：
1. 按 group 注入 C=1 初始化前置
2. 注入功能依赖（如全域名 → zone/nameserver/record）
3. 匹配 apv_action.py 高位动作
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from langchain_core.tools import tool

_PROJECT_ROOT = Path(__file__).resolve().parents[4]

# 已注入缓存（每次调用时清空）
_INJECTED_PREREQ: set[str] = set()
_INJECTED_DEPS: set[int] = set()

G_FILL_PDF = "llm_pdf"
G_FILL_INFER = "llm_infer"
G_FILL_DIRECT = "direct"

# 功能 → 前置配置
_FEATURE_PREREQUISITES: dict[str, dict] = {
    "sdns_listener": {
        "group": "SDNS_Listener",
        "init": [
            {"actor": "APV_0", "action": "cmds_config",
             "describe": "[前置] 初始化SDNS基础环境: sdns on, sdns host name, sdns service ip, sdns pool name, sdns pool service, sdns host pool, sdns listener",
             "hint": "sdns on; sdns host name <domain>; sdns service ip <name> <ip>; sdns pool name <name>; sdns pool service <pool> <svc>; sdns host pool <host> <pool>; sdns listener <ip>"},
        ],
    },
    "sdns_persistence": {
        "group": "SDNS_Persistence",
        "init": [
            {"actor": "APV_0", "action": "cmds_config",
             "describe": "[前置] 初始化SDNS基础环境: sdns on, sdns host name, sdns service ip, sdns pool name, sdns pool service, sdns host pool, sdns listener",
             "hint": "sdns on; sdns host name <domain>; sdns service ip <name> <ip>; sdns pool name <name>; sdns pool service <pool> <svc>; sdns host pool <host> <pool>; sdns listener <ip>"},
        ],
    },
    "sdns_recursion": {
        "group": "SDNS_Recursion",
        "init": [
            {"actor": "APV_0", "action": "cmds_config",
             "describe": "[前置] 初始化SDNS递归环境: sdns on, sdns service ip, sdns pool name, sdns pool service, sdns listener",
             "hint": "sdns on; sdns service ip <name> <ip>; sdns pool name <name>; sdns pool service <pool> <svc>; sdns listener <ip>"},
        ],
    },
    "sdns_config_save": {
        "group": "SDNS_ConfigSave",
        "init": [
            {"actor": "APV_0", "action": "cmds_config",
             "describe": "[前置] 初始化SDNS基础环境: sdns on, sdns host name, sdns service ip, sdns pool name, sdns pool service, sdns host pool, sdns listener",
             "hint": "sdns on; sdns host name <domain>; sdns service ip <name> <ip>; sdns pool name <name>; sdns pool service <pool> <svc>; sdns host pool <host> <pool>; sdns listener <ip>"},
        ],
    },
    "sdns_sync": {
        "group": "SDNS_ConfigSync",
        "init": [
            {"actor": "APV_0", "action": "cmds_config",
             "describe": "[前置] 初始化HA+SDNS基础环境: ha link, ha unit, sdns on, sdns host name, sdns service ip, sdns pool, sdns listener",
             "hint": "ha link ffo <iface>; ha unit <id>; sdns on; sdns host name <domain>; sdns service ip; sdns pool name; sdns listener <ip>"},
        ],
    },
    "slb": {
        "group": "SLB",
        "init": [
            {"actor": "APV_0", "action": "cmds_config",
             "describe": "[前置] 初始化SLB+SDNS基础环境: sdns on, sdns host name, sdns service ip, sdns pool, sdns listener",
             "hint": "sdns on; sdns host name <domain>; sdns service ip; sdns pool name; sdns listener <ip>"},
        ],
    },
}

# 功能依赖
_FEATURE_DEPENDENCIES: dict[str, list[dict[str, str]]] = {
    "vip": [
        {"actor": "APV_0", "action": "cmd_config",
         "describe": "[依赖] 创建SLB虚拟服务作为VIP",
         "hint": "slb virtual <http|tcp|https> <name> <ip> <port> arp 0"},
    ],
    "ha fip": [
        {"actor": "APV_0", "action": "cmd_config",
         "describe": "[前置] 配置HA浮动IP",
         "hint": "ha fip <ip>"},
    ],
    "全域名功能": [
        {"actor": "APV_0", "action": "cmds_config",
         "describe": "[前置] 配置全域名功能: sdns zone name, sdns nameserver name, sdns record a, sdns zone record",
         "hint": "sdns zone name <domain> master; sdns nameserver name <ns_name> <ip>; sdns record a <name> <host> <server_ip>; sdns zone record <zone> <record>"},
    ],
}


def _detect_feature(module: str, steps_text: str) -> str:
    combined = (module + " " + steps_text).lower()
    if "persistence" in combined or "会话保持" in combined:
        return "sdns_persistence"
    if "递归" in combined or "forward_only" in combined or "zone forward" in combined:
        return "sdns_recursion"
    if "配置保存" in combined or "write" in combined:
        return "sdns_config_save"
    if "配置同步" in combined or "sync" in combined or "ha" in combined:
        return "sdns_sync"
    if "slb" in combined and ("vip" in combined or "virtual" in combined):
        return "slb"
    if "sdns" in combined or "listener" in combined:
        return "sdns_listener"
    return ""


def _get_prereq_info(feature: str) -> dict:
    return _FEATURE_PREREQUISITES.get(feature, {"group": feature or "default", "init": []})


@tool
def qa_inject_init_and_deps(decomposed_json_path: str) -> str:
    """Inject init steps and feature dependencies into a decomposed test case JSON.

    Call this AFTER the LLM has decomposed test cases into D/E/F steps.
    This tool does PURELY MECHANICAL work:
    1. Injects C=1 init steps per group (from _FEATURE_PREREQUISITES)
    2. Injects feature dependency steps (from _FEATURE_DEPENDENCIES)
    3. Re-numbers C column to accommodate injected steps

    Args:
        decomposed_json_path: Path to the LLM-decomposed JSON file.
            E.g. "workspace/inputs/yzg/yzg_decomposed.json"

    Returns:
        JSON string with status, output_file, total_cases, groups.
    """
    _INJECTED_PREREQ.clear()
    _INJECTED_DEPS.clear()

    p = Path(decomposed_json_path)
    candidates = [p, _PROJECT_ROOT / decomposed_json_path]
    resolved = None
    for c in candidates:
        if c.exists():
            resolved = c
            break
    if resolved is None:
        return json.dumps({
            "status": "error",
            "error": f"File not found: {decomposed_json_path}",
        }, indent=2, ensure_ascii=False)

    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except Exception as exc:
        return json.dumps({"status": "error", "error": f"Parse failed: {exc}"},
                          indent=2, ensure_ascii=False)

    cases = data.get("cases", [])
    if not cases:
        return json.dumps({"status": "error", "error": "No cases in JSON"},
                          indent=2, ensure_ascii=False)

    for case in cases:
        steps = case.get("steps", [])
        module = case.get("module", "")
        case_id = case.get("case_id", 0)
        all_steps_text = " ".join(s.get("describe", "") for s in steps)

        # 检查是否已有 C=1 init 步骤（由 qa_decompose_test_cases 注入），避免重复
        has_init = any(
            s.get("c") == 1 or "初始化" in s.get("describe", "") or "前置" in s.get("describe", "")
            for s in steps
        )

        feature = _detect_feature(module, all_steps_text)
        prereq_info = _get_prereq_info(feature) if feature else {"group": feature or "default", "init": []}
        # 使用 decomposer 设的 group（来自脑图层级），不覆盖
        # feature 检测仅用于决定是否注入 init + 注入什么 init
        group_name = case.get("group", prereq_info.get("group", feature or "default"))

        prereq_steps = prereq_info.get("init", [])
        if feature and group_name not in _INJECTED_PREREQ:
            if not has_init:
                _INJECTED_PREREQ.add(group_name)
                new_steps = []
                c_counter = 1
                for ps in prereq_steps:
                    domain = "autotest.com"
                    dm = re.search(r'["\']([\w*.-]+\.[\w]{2,})["\']', all_steps_text)
                    if not dm:
                        dm = re.search(r'([\w-]+\.[\w-]+\.[\w]{2,})', all_steps_text)
                    if dm:
                        domain = dm.group(1)
                    ip = "172.16.35.231"
                    im = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', all_steps_text)
                    if im:
                        ip = im.group(1)

                    ps_copy = dict(ps)
                    ps_copy["describe"] = ps["describe"].replace("autotest.com", domain).replace("172.16.35.231", ip)
                    new_steps.append({
                        "c": c_counter, "actor": ps["actor"], "action": ps["action"],
                        "describe": ps_copy["describe"], "g_fill": G_FILL_PDF,
                        "hint": ps.get("hint", ""),
                    })
                    c_counter += 1

                deps_check_text = all_steps_text + " " + case.get("description", "")
                for dep_key, dep_steps in _FEATURE_DEPENDENCIES.items():
                    if dep_key in deps_check_text.lower() and case_id not in _INJECTED_DEPS:
                        _INJECTED_DEPS.add(case_id)
                        for ds in dep_steps:
                            new_steps.append({
                                "c": c_counter, "actor": ds["actor"], "action": ds["action"],
                                "describe": ds["describe"], "g_fill": G_FILL_PDF,
                                "hint": ds.get("hint", ""),
                            })
                            c_counter += 1

                for s in steps:
                    s["c"] = c_counter
                    c_counter += 1

                case["steps"] = new_steps + steps
            else:
                # 已有 init（由 decomposer 注入），标记 group 防止后续 case 重复注入
                _INJECTED_PREREQ.add(group_name)

    # 输出路径 = 输入路径（原地更新，不覆写其他人的文件）
    out_path = resolved
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    groups = sorted(set(c.get("group", "default") for c in cases))
    return json.dumps({
        "status": "success",
        "output_file": str(out_path),
        "total_cases": len(cases),
        "groups": groups,
    }, indent=2, ensure_ascii=False)
