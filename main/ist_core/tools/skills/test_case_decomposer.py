"""qa_decompose_cases: Step 2 — 用例 → D/E/F 步骤骨架。

将 Step 1 提取的结构化用例拆解为原子步骤序列，标记每步的 G 列填充策略。
可扩展：新增 g_fill 类型、actor/action 映射、推断规则只需改配置常量。
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_KEYWORDS_MD = Path(__file__).parent / "decomposer_keywords.md"


# ==========================================================================
# 关键词配置解析
# ==========================================================================

def _extract_backtick_patterns(text: str) -> list[str]:
    """从文本中提取反引号中的模式。"""
    return [m.group(1) for m in re.finditer(r'`([^`]+)`', text)]


def _extract_keywords_from_cell(text: str) -> list[str]:
    """从单元格中提取关键词（反引号分隔或顿号分隔）。"""
    backtick = _extract_backtick_patterns(text)
    if backtick:
        return backtick
    return [k.strip() for k in text.split("、") if k.strip()]


def _parse_md_table(text: str) -> list[dict[str, str]]:
    """解析 markdown 表格，返回列表。"""
    rows = []
    lines = text.strip().split("\n")
    headers = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("---"):
            continue
        if "|" in line:
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if not headers:
                headers = cells
            elif len(cells) >= 2:
                row = {}
                for i, h in enumerate(headers):
                    if i < len(cells):
                        row[h] = cells[i]
                rows.append(row)
    return rows


def _load_keywords_from_md() -> dict[str, Any]:
    """从 decomposer_keywords.md 加载关键词配置。"""
    content = _KEYWORDS_MD.read_text(encoding="utf-8")
    result = {
        "phase_type_rules": [],
        "actor_rules": [],
        "action_rules": {},
        "neg_keywords": [],
        "assert_keywords": [],
    }

    sections = re.split(r'^## \d+\.\s+', content, flags=re.MULTILINE)

    for section in sections:
        if not section.strip():
            continue
        lines = section.strip().split("\n")
        title = lines[0].strip() if lines else ""

        # 0. Phase + Type 推断关键词
        if "Phase + Type" in title:
            current_phase = None
            current_type = None
            current_actor = None
            for line in lines:
                if "Setup phase" in line and "device_config" in line:
                    current_phase, current_type, current_actor = "Setup", "device_config", "APV_0"
                elif "Trigger phase" in line and "client_action" in line:
                    current_phase, current_type, current_actor = "Trigger", "client_action", "test_env"
                elif "Verify phase" in line and "capture_verify" in line:
                    current_phase, current_type, current_actor = "Verify", "capture_verify", "APV_0"
                elif "Verify phase" in line and "device_query" in line:
                    current_phase, current_type, current_actor = "Verify", "device_query", "APV_0"
                elif current_phase and "|" in line and "关键词" not in line and "---" not in line:
                    cells = [c.strip() for c in line.split("|") if c.strip()]
                    if len(cells) >= 1 and cells[0] not in ("关键词模式", "-------"):
                        patterns = _extract_keywords_from_cell(cells[0])
                        if patterns:
                            combined = "|".join(patterns)
                            result["phase_type_rules"].append((combined, current_phase, current_type, current_actor))

        # 1. Actor 分类关键词
        elif "Actor 分类" in title:
            for row in _parse_md_table("\n".join(lines)):
                kw_cell = row.get("关键词模式", "")
                actor = row.get("Actor", "")
                if kw_cell and actor and actor not in ("Actor", "-------"):
                    patterns = _extract_keywords_from_cell(kw_cell)
                    combined = "|".join(patterns)
                    if combined:
                        result["actor_rules"].append((combined, actor))

        # 2. Action 推断关键词
        elif "Action 推断" in title:
            current_actor = None
            for line in lines:
                if "APV_0 的 Action" in line:
                    current_actor = "APV_0"
                elif "APV_1 的 Action" in line:
                    current_actor = "APV_1"
                elif "test_env 的 Action" in line:
                    current_actor = "test_env"
                elif "check_point 的 Action" in line:
                    current_actor = "check_point"
                elif current_actor and "|" in line and "关键词" not in line and "---" not in line:
                    cells = [c.strip() for c in line.split("|") if c.strip()]
                    if len(cells) >= 2 and cells[0] not in ("关键词模式", "-------"):
                        patterns = _extract_keywords_from_cell(cells[0])
                        action = cells[1].strip()
                        if patterns and action:
                            if current_actor not in result["action_rules"]:
                                result["action_rules"][current_actor] = []
                            combined = "|".join(patterns)
                            result["action_rules"][current_actor].append((combined, action))

        # 8. check_point 判断关键词
        elif "check_point 判断" in title:
            in_neg = False
            in_assert = False
            for line in lines:
                if "负向断言" in line:
                    in_neg = True
                    in_assert = False
                elif "正向断言" in line:
                    in_neg = False
                    in_assert = True
                elif line.strip().startswith("```") or line.strip().startswith("---"):
                    continue
                elif in_neg and line.strip() and not line.strip().startswith("#"):
                    kws = [k.strip() for k in line.split("、") if k.strip() and k.strip() != "---"]
                    result["neg_keywords"].extend(kws)
                elif in_assert and line.strip() and not line.strip().startswith("#"):
                    kws = [k.strip() for k in line.split("、") if k.strip() and k.strip() != "---"]
                    result["assert_keywords"].extend(kws)

    return result


# 加载配置
_keywords_config = _load_keywords_from_md()

# check_point 判断关键词：从 decomposer_keywords.md 加载
_NEG_KW = _keywords_config.get("neg_keywords", [])
_ASSERT_KW = _keywords_config.get("assert_keywords", [])

# ==========================================================================
# apv_action.py 高位动作映射（步骤描述匹配到 → F 列直接用关键字，G 列留空）
# ==========================================================================
# 从 yzg/input/apv_action.py 的 command_function_mapping 提取
# 格式：{触发关键词: (action_keyword, actor, 描述)}
_HIGH_LEVEL_ACTIONS: dict[str, tuple[str, str, str]] = {
    "满配": ("配满16条sdns listener", "APV_0", "批量配置16条sdns listener"),
    "16条": ("配满16条sdns listener", "APV_0", "批量配置16条sdns listener"),
    "检查16条sdns listener": ("检查16条sdns listener配置结果", "check_point", "批量检查16条listener配置"),
    # SDNS 高位动作
    "dnssec": ("配置DNSSEC", "APV_0", "配置DNSSEC密钥和签名"),
    # 健康检查
    "等待健康检查up": ("等待健康检查up", "APV_0", "等待指定类型健康检查变为UP"),
    "健康检查up": ("指定类型健康检查UP", "APV_0", "等待指定类型健康检查变为UP"),
    "健康检查down": ("指定类型健康检查DOWN", "APV_0", "等待指定类型健康检查变为DOWN"),
    "service健康检查down": ("指定Service健康检查DOWN", "APV_0", "等待指定Service健康检查DOWN"),
    "service健康检查up": ("指定Service健康检查UP", "APV_0", "等待指定Service健康检查UP"),
    # HA
    "ha link状态up": ("等待ha link状态up", "APV_0", "等待HA link变为UP"),
    "ha domain状态up": ("等待ha domain状态up", "APV_0", "等待HA domain变为UP"),
    # 白名单
    "白名单规则": ("配置白名单规则为", "APV_0", "配置白名单ACL规则"),
    "检查白名单permit": ("检查白名单permit一次", "check_point", "检查白名单permit计数为1"),
    # 区域传输
    "区域传输axfr": ("检查区域传输AXFR同步成功", "check_point", "检查AXFR区域传输同步成功"),
    "区域传输ixfr": ("检查区域传输IXFR同步成功", "check_point", "检查IXFR区域传输同步成功"),
    "stub.*axfr": ("检查STUB区域传输AXFR同步成功", "check_point", "检查STUB AXFR同步成功"),
    "stub.*ixfr": ("检查STUB区域传输IXFR同步成功", "check_point", "检查STUB IXFR同步成功"),
}

def _match_high_level_action_verify(config_keyword: str) -> str | None:
    """返回高位动作对应的验证动作关键字。"""
    _VERIFY_MAP = {
        "配满16条sdns listener": "检查16条sdns listener配置结果",
        "检查16条sdns listener配置结果": None,  # 本身已是验证
    }
    return _VERIFY_MAP.get(config_keyword)


def _match_high_level_action(step_text: str, module: str) -> tuple[str, str, str] | None:
    """匹配 apv_action.py 的高位动作。返回 (action_keyword, actor, describe) 或 None。"""
    combined = (module + " " + step_text).lower()
    for trigger, (keyword, actor, desc) in _HIGH_LEVEL_ACTIONS.items():
        if re.search(trigger, combined):
            return (keyword, actor, desc)
    return None

# ==========================================================================
# 可扩展配置（新增类型只需加到这里）
# ==========================================================================

# 功能关键词 → 前置基础配置
# 测试工程一般只写关键步骤，基础配置作为隐含前置需要自动补充
# 每个 entry 包含: init (前置步骤), group (分组名, 同组case共用一个init)
_FEATURE_PREREQUISITES: dict[str, dict] = {
    "SDNS": {
        "init": [
            {"actor": "APV_0", "action": "cmds_config",
             "describe": "[前置] 初始化SDNS基础环境: sdns on, sdns host name, sdns service ip, sdns pool name, sdns pool service, sdns host pool, sdns listener",
             "hint": "sdns on; sdns host name <domain>; sdns service ip <name> <ip>; sdns pool name <name>; sdns pool service <pool> <svc>; sdns host pool <host> <pool>; sdns listener <ip>"},
        ],
    },
    "SLB": {
        "init": [
            {"actor": "APV_0", "action": "cmds_config",
             "describe": "[前置] 初始化SLB+SDNS基础环境: sdns on, sdns host name, sdns service ip, sdns pool, sdns listener",
             "hint": "sdns on; sdns host name <domain>; sdns service ip; sdns pool name; sdns listener <ip>"},
        ],
    },
    "HA": {
        "init": [
            {"actor": "APV_0", "action": "cmds_config",
             "describe": "[前置] 初始化HA基础环境: ha on, ha link, ha unit",
             "hint": "ha on; ha link ffo <iface>; ha unit <id>"},
        ],
    },
    "LLB": {"init": []},
    "GSLB": {"init": []},
    "SSL": {"init": []},
    "DPI": {"init": []},
    "QoS": {"init": []},
    "Cluster": {"init": []},
    "LinkAggr": {"init": []},
    "VPN": {"init": []},
    "Routing": {"init": []},
    "Firewall": {"init": []},
    "IPv6": {"init": []},
}

# 功能依赖链：当一个步骤涉及多个功能时，自动注入前置功能步骤
# key: 触发关键词组合, value: 需要先执行的步骤列表
_FEATURE_DEPENDENCIES: dict[str, list[dict[str, str]]] = {
    # sdns listener on slb vip → 先创建 slb virtual
    "vip": [
        {"actor": "APV_0", "action": "cmd_config",
         "describe": "[依赖] 创建SLB虚拟服务作为VIP: 选择协议类型、IP和端口",
         "hint": "slb virtual <http|tcp|https> <name> <ip> <port> arp 0"},
    ],
    # sdns on ha fip → 先配置 ha fip
    "ha fip": [
        {"actor": "APV_0", "action": "cmd_config",
         "describe": "[前置] 配置HA浮动IP",
         "hint": "ha fip <ip>"},
    ],
    # 全域名功能 → 需要 zone + nameserver + record 前置
    "全域名功能": [
        {"actor": "APV_0", "action": "cmds_config",
         "describe": "[前置] 配置全域名功能: sdns zone name, sdns nameserver name, sdns record a, sdns zone record",
         "hint": "sdns zone name <domain> master; sdns nameserver name <ns_name> <ip>; sdns record a <name> <host> <server_ip>; sdns zone record <zone> <record>"},
    ],
}

# IP 选择策略：不同 IP 类型对应拓扑中不同设备的真实 IP
# 接口类 IP（port/bond/vlan/系统）→ APV 真实接口 IP
# 虚拟服务类（VIP/listener 默认）→ 生成的未占用 IP
_IP_POOL: dict[str, str] = {
    # 接口类IP（长关键字优先，避免"非系统ip"被"系统ip"误匹配）
    "port接口ip": "172.16.34.70",      # APV0 业务接口IP
    "port ip": "172.16.34.70",
    "bond接口ip": "172.16.34.70",
    "bond ip": "172.16.34.70",
    "vlan ip": "172.16.34.70",
    "ha fip": "172.16.34.70",
    "非系统ip": "10.0.0.1",           # 非法IP，必须在"系统ip"之前
    "系统ip": "172.16.34.70",         # APV0 业务接口IP
    "slb vip": "172.16.34.100",       # SLB 虚拟服务VIP
    "default": "172.16.34.50",        # 默认VIP（.50起，未占用）
}

def _pick_listener_ip(module: str, step_text: str) -> str:
    """根据用例的 IP 类型选择合适的 listener IP。"""
    combined = (module + " " + step_text).lower()
    for key, ip in _IP_POOL.items():
        if key in combined:
            return ip
    return _IP_POOL["default"]

# 已注入前置的模块（同级模块只注入一次）
_INJECTED_PREREQ: set[str] = set()

# 已注入依赖的 group+dep_key（同 group 内同依赖只注入一次，跨 case 共享）
_INJECTED_DEPS: set[tuple] = set()


def _detect_module_and_group(module: str, steps_text: str) -> tuple[str, str]:
    """推断大模块名和 group 名。group = 大模块_子功能。"""
    combined = (module + " " + steps_text).lower()

    # 大模块推断（关键词来自 CLI 手册 10.5 章节目录）
    big = "SDNS"  # 默认
    if "slb" in combined or "virtual-server" in combined or "real-server" in combined or "后台服务" in combined:
        big = "SLB"
    elif ("ha" in combined and "sdns" not in combined) or "高可用" in combined:
        big = "HA"
    elif "firewall" in combined or "acl" in combined or "安全策略" in combined or "访问规则" in combined:
        big = "Firewall"
    elif "llb" in combined or "链路负载" in combined:
        big = "LLB"
    elif "gslb" in combined:
        big = "GSLB"
    elif "ssl" in combined or "ssl " in combined:
        big = "SSL"
    elif "dpi" in combined or "深度报文" in combined:
        big = "DPI"
    elif "qos" in combined or "服务质量" in combined:
        big = "QoS"
    elif "cluster" in combined or "集群" in combined:
        big = "Cluster"
    elif "link-aggregation" in combined or "链路聚合" in combined or "bond" in combined:
        big = "LinkAggr"
    elif "ipsec" in combined or "ike" in combined or "vpn" in combined or "tunnel" in combined:
        big = "VPN"
    elif "route" in combined or "bgp" in combined or "ospf" in combined or "路由" in combined:
        big = "Routing"
    elif "dns64" in combined or "nat64" in combined:
        big = "IPv6"
    elif "http" in combined and "proxy" in combined:
        big = "SLB"  # HTTP 代理是 SLB 的子功能（rewrite/compression/cache 等）

    # 子功能从 module 路径取倒数第二段（feature 层），末段通常是太细的叶节点
    # 例: "功能 > 配置会话保持 > 指定域名" → sub = "配置会话保持"
    #     "功能 > 配置会话保持"          → sub = "配置会话保持"
    #     "功能 > 删除会话保持"          → sub = "删除会话保持"
    parts = [p.strip() for p in module.split(">") if p.strip()]
    # 去掉"测试"/"功能"無意义的词
    parts = [p for p in parts if p not in ("测试", "功能")]
    if not parts:
        sub = "default"
    elif len(parts) >= 2:
        sub = parts[-2]  # 倒数第二段 = feature 层
    else:
        sub = parts[-1]
    sub = sub.replace("测试", "").replace("功能", "").strip() or sub

    group = f"{big}_{sub}" if sub != big else big
    return big, group


def _get_prereq_info(feature: str) -> dict:
    """获取功能领域的前置配置信息，包含 group 名和 init 步骤。"""
    return _FEATURE_PREREQUISITES.get(feature, {"group": feature or "default", "init": []})

# G 列填充策略
G_FILL_PDF = "llm_pdf"       # LLM 查 PDF 手册拿精确 CLI 命令
G_FILL_INFER = "llm_infer"   # LLM 根据上下文推断，无需 PDF
G_FILL_DIRECT = "direct"     # 直接填，固定值

# Actor 识别规则：从 decomposer_keywords.md 加载
# 格式：[(regex_pattern, actor), ...]
_ACTOR_RULES_FROM_MD = _keywords_config.get("actor_rules", [])
ACTOR_RULES: list[tuple[str, str, str]] = [
    (pattern, actor, f"从配置文件加载: {actor}")
    for pattern, actor in _ACTOR_RULES_FROM_MD
]
ACTOR_DEFAULT = 'APV_0'

# Action 推断规则：从 decomposer_keywords.md 加载
# 格式：{actor: [(regex_pattern, action), ...]}
_ACTION_RULES_FROM_MD = _keywords_config.get("action_rules", {})

# Step 文本预处理：分离 [check] 标记
_CHECK_MARKER_RE = re.compile(r'\s*\[check\d*\]\s*', re.IGNORECASE)

# 显式前置条件标签（步骤文本以这些标签开头 = 用例级前置，需生成为独立步骤）
_PREREQ_LABEL_RE = re.compile(
    r'^(?:前提条件|前置条件|前置步骤|前置)[：:]\s*', re.IGNORECASE
)

# 时间延迟模式：从步骤文本中提取延迟秒数和剩余动作
# 支持三种形式：
#   1. 开头时间: "N秒后/之后xxx" / "Ns后xxx"
#   2. sleep: "sleep N" / "sleep Ns" （无单位默认秒）
#   3. 等待中置: "等待N秒xxx" / "等N分钟xxx"
_TIME_START_RE = re.compile(
    r'(\d+(?:\.\d+)?)\s*'
    r'(秒|s|sec|秒钟|分钟|min|minute|ms|毫秒)'
    r'(?:后|之后|以后)?'
    r'[，,\s]*'
    r'(.*)',
    re.IGNORECASE
)
_TIME_SLEEP_RE = re.compile(
    r'(?:sleep)\s+(\d+(?:\.\d+)?)\s*'
    r'(秒|s|sec|秒钟|分钟|min|minute|ms|毫秒)?',
    re.IGNORECASE
)
_TIME_WAIT_RE = re.compile(
    r'(?:等待|等)\s*(\d+(?:\.\d+)?)\s*'
    r'(秒|s|sec|秒钟|分钟|min|minute|ms|毫秒)'
    r'(?:后|之后|以后)?'
    r'[，,\s]*'
    r'(.*)',
    re.IGNORECASE
)


def _parse_time_seconds(value_str: str, unit_str: str | None) -> int:
    """将时间值和单位转为整数秒。unit 为 None 时默认秒。"""
    value = float(value_str)
    if unit_str is None:
        return max(1, int(value))
    unit = unit_str.lower()
    if unit in ('ms', '毫秒'):
        return max(1, int(value / 1000))
    if unit in ('分钟', 'min', 'minute'):
        return int(value * 60)
    return max(1, int(value))  # 秒/s/sec/秒钟


def _strip_check_marker(text: str) -> str:
    """移除 step 文本中的 [checkN] 标记，返回纯动作描述。"""
    return _CHECK_MARKER_RE.sub('', text).strip()


def _has_check_marker(text: str) -> bool:
    """检查 step 文本是否包含 [checkN] 标记。"""
    return bool(_CHECK_MARKER_RE.search(text))


def _match_expected_by_check(step_text: str, expected: list[str]) -> str:
    """根据 step 文本中的 [checkN] 编号匹配对应的预期结果。

    有编号则精确匹配（[check1]→"配置添加成功"），无编号取第一个。
    """
    check_match = re.search(r'\[check(\d*)\]', step_text, re.IGNORECASE)
    if check_match:
        check_num = check_match.group(1)
        marker = f'[check{check_num}]' if check_num else '[check'
        for e in expected:
            if marker.lower() in e.lower():
                return _CHECK_MARKER_RE.sub('', e).strip()
    # 兜底：取第一个预期结果
    for e in expected:
        clean = _CHECK_MARKER_RE.sub('', e).strip()
        if clean:
            return clean
    return expected[0] if expected else ""


def _split_compound_actions(text: str) -> list[str] | None:
    """拆分复合动作步骤。

    识别并拆分用逗号、顿号、"并且"、"然后"连接的多个独立动作。

    示例：
    "配置vh1协议为TLSv1.1，创建sdns service sdnsdc1 43.43.43.9将其与hc1绑定,rs配置为双向认证，并且发送certificate request报文"
    → ["配置vh1协议为TLSv1.1", "创建sdns service sdnsdc1 43.43.43.9将其与hc1绑定",
       "rs配置为双向认证", "发送certificate request报文"]
    """
    if not text:
        return None

    # 配置/触发动作关键词（这些动作应该被拆分为独立步骤）
    _CONFIG_TRIGGER_START = (
        r'(?:配置|创建|添加|新增|设置|删除|启用|禁用|开启|关闭|导入|导出|绑定|解绑|'
        r'激活|取消激活|修改|重启|保存|发送|抓包|'
        r'客户端|dig\s|ping\s|curl\s|wget\s|tcpdump|debug\s|trace\s|show\s|'
        r'rs\s|再次|将|把|使)'
    )

    # 验证动作关键词（这些动作通常是前一个动作的延续，不单独拆分）
    _VERIFY_START = r'(?:查看|验证|检查|确认|显示|查询|断言|预期)'

    # 分隔符：逗号、顿号、"并且"、"然后"、"同时"
    _SEPARATOR = r'[,，、]\s*(?:并且|然后|同时)?\s*|(?:并且|然后|同时)\s*'

    # 按分隔符拆分
    parts = re.split(_SEPARATOR, text)
    parts = [p.strip() for p in parts if p.strip()]

    if len(parts) < 2:
        return None

    # 检查每个部分是否应该被拆分
    action_parts = []
    for part in parts:
        if re.match(_CONFIG_TRIGGER_START, part, re.IGNORECASE):
            # 配置/触发动作，拆分为独立步骤
            action_parts.append(part)
        elif re.match(_VERIFY_START, part, re.IGNORECASE):
            # 验证动作，检查前一个动作是否是触发动作
            if action_parts and re.search(r'(?:发送|请求|访问|dig|ping|curl|发包)', action_parts[-1], re.IGNORECASE):
                # 前一个动作是触发动作，验证动作作为延续
                action_parts[-1] += "，" + part
            else:
                # 前一个动作不是触发动作，拆分为独立步骤
                action_parts.append(part)
        elif action_parts:
            # 其他情况，作为前一个动作的延续
            action_parts[-1] += "，" + part
        else:
            # 第一个部分不是动作关键词，整个不拆分
            return None

    # 只有当拆分出 2 个以上动作时才返回
    if len(action_parts) >= 2:
        return action_parts

    return None


def _split_numbered_sub_steps(text: str) -> list[str] | None:
    """检测并拆分合并的步骤。

    覆盖三种模式：
    1. 编号子步骤：1.配置xxx\\n2.使用dig请求tcp [check1]
    2. 单行多个编号：1.配置xxx 2.使用dig请求tcp
    3. \\n分隔的配置+客户端动作：在bapv上配置sdns\\ndig访问aapv tcp

    拆分后剥离编号前缀（如 "3.10s后再次请求"→"10s后再次请求"），避免编号
    干扰下游的时间检测/actor分类。
    """
    _STRIP_NUM_PREFIX = re.compile(r'^\d+[\.\、\)]\s*')
    if not text:
        return None
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(lines) >= 2:
        # 模式1：编号子步骤
        numbered = [l for l in lines if re.match(r'\d+[\.\、\)]', l)]
        if len(numbered) >= 2 and len(numbered) >= len(lines) * 0.6:
            return [_STRIP_NUM_PREFIX.sub('', l) for l in lines]
        # 模式3：\\n分隔的配置+客户端动作（如"在bapv上配置sdns\\ndig访问aapv"）
        _CONFIG_SIG = r'配置|添加|删除|修改|设置|启用|禁用|开启|关闭|no\s|sdns\s|slb\s|ha\s|fw\s|listener|host\s|pool\s|service\s|zone\s'
        _CLIENT_SIG = r'dig\s|ping\s|curl\s|wget\s|发包|打流量|访问|请求|客户端|tcpdump|telnet|nc\s|nslookup'
        has_config = any(re.search(_CONFIG_SIG, l, re.IGNORECASE) for l in lines)
        has_client = any(re.search(_CLIENT_SIG, l, re.IGNORECASE) for l in lines)
        if has_config and has_client:
            config_lines = [l for l in lines if re.search(_CONFIG_SIG, l, re.IGNORECASE)]
            client_lines = [l for l in lines if re.search(_CLIENT_SIG, l, re.IGNORECASE)]
            if config_lines and client_lines:
                return lines
    # 模式2：单行但含多个编号子步骤
    # 先排除 IP 地址（如 43.43.43.9），避免误拆
    _IP_PATTERN = re.compile(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')
    # 移除 IP 地址后再检测编号
    text_no_ip = _IP_PATTERN.sub('IP_PLACEHOLDER', text)
    parts = re.split(r'(?=\d+[\.\、\)])', text_no_ip)
    parts = [p.strip() for p in parts if p.strip()]
    numbered_parts = [p for p in parts if re.match(r'\d+[\.\、\)]', p)]
    if len(numbered_parts) >= 2:
        # 有编号子步骤，但需要恢复 IP 地址
        # 重新对原文进行拆分，但只在非 IP 位置拆分
        result_parts = []
        current = text
        for np in numbered_parts:
            # 找到编号在原文中的位置（跳过 IP 中的数字）
            idx = current.find(np)
            if idx > 0:
                result_parts.append(current[:idx])
            current = current[idx:] if idx >= 0 else current
        if current:
            result_parts.append(current)
        return [_STRIP_NUM_PREFIX.sub('', p).strip() for p in result_parts if p.strip()]
    return None


# ==========================================================================
# Phase + Type 框架
# ==========================================================================

# Phase（阶段）：Setup / Trigger / Verify
PHASE_SETUP = "Setup"        # 配置阶段，顺序执行
PHASE_TRIGGER = "Trigger"    # 触发阶段，执行测试动作
PHASE_VERIFY = "Verify"      # 验证阶段，必须有 expected

# Type（类型）：步骤类型
TYPE_DEVICE_CONFIG = "device_config"      # 在设备上下发配置
TYPE_CLIENT_ACTION = "client_action"      # 客户端发包/请求
TYPE_CAPTURE_VERIFY = "capture_verify"    # 抓包/日志/命令行验证
TYPE_DEVICE_QUERY = "device_query"        # 在设备上查询状态

# Phase + Type 推断规则：从 decomposer_keywords.md 加载
# 格式：[(pattern, phase, type, actor)]
_PHASE_TYPE_RULES_FROM_MD = _keywords_config.get("phase_type_rules", [])
_PHASE_TYPE_RULES: list[tuple[str, str, str, str]] = [
    (pattern, phase, type_, actor)
    for pattern, phase, type_, actor in _PHASE_TYPE_RULES_FROM_MD
]


def _infer_phase_type(text: str, is_expected: bool = False) -> tuple[str, str, str]:
    """推断步骤的 phase 和 type。返回 (phase, type, actor)。"""
    text_lower = text.lower()

    # 如果是 expected，直接归为 Verify phase
    if is_expected:
        return PHASE_VERIFY, TYPE_CAPTURE_VERIFY, "check_point"

    # 按规则匹配
    for pattern, phase, type_, actor in _PHASE_TYPE_RULES:
        if re.search(pattern, text_lower):
            return phase, type_, actor

    # 默认：Setup phase, device_config
    return PHASE_SETUP, TYPE_DEVICE_CONFIG, "APV_0"


# Action 推断规则：从 decomposer_keywords.md 加载（保留兼容）
# 格式：{actor: [(regex_pattern, action, description), ...]}
ACTION_RULES: dict[str, list[tuple[str, str, str]]] = {}
for actor, rules in _ACTION_RULES_FROM_MD.items():
    ACTION_RULES[actor] = [(pattern, action, f"从配置文件加载: {action}") for pattern, action in rules]
ACTION_DEFAULT: dict[str, str] = {
    'APV_0': 'cmd_config',
    'APV_1': 'cmd_config',
    'test_env': 'routera',
    'check_point': 'found',
}

# G 列填充策略推断
G_FILL_RULES: dict[str, str] = {
    'APV_0': G_FILL_PDF,
    'APV_1': G_FILL_PDF,
    'test_env': G_FILL_INFER,
    'check_point': G_FILL_INFER,
}

# 前置条件推断：根据模块和步骤描述，补充隐含的前置依赖
_PREREQUISITE_RULES: dict[str, str] = {
    "sdns listener": "需要先启用SDNS功能(sdns on)并配置基础环境: sdns host name定义域名, sdns service ip定义后端服务, sdns pool name创建服务池, sdns pool service关联服务到池, sdns host pool关联域名到池",
    "sdns host name": "需要先启用SDNS功能(sdns on)",
    "sdns service ip": "需要先启用SDNS功能(sdns on)",
    "sdns pool": "需要先启用SDNS功能(sdns on)并定义sdns service",
    "sdns zone forward": "需要先启用SDNS功能(sdns on)",
    "slb virtual": "需要确保SLB功能已启用, 相关接口IP已配置",
    "slb real": "需要先定义slb group",
    "slb group": "需要确保SLB功能已启用",
    "ha synconfig": "需要先配置HA基本环境(ha on, ha link, ha unit等)",
    "ha 运行时同步": "需要先配置HA基本环境(ha on, ha link, ha unit等)",
    "ha 启动时同步": "需要先配置HA基本环境(ha on, ha link, ha unit等)",
    "synconfig from": "需要先配置HA基本环境, 且启动时配置同步为禁用状态",
    "synconfig to": "需要先配置HA基本环境, 且启动时配置同步为禁用状态",
    "write memory": "需要先完成配置变更",
    "write file": "需要先完成配置变更",
    "write all": "需要先完成配置变更",
    "write net": "需要先完成配置变更",
    "reboot": "需要先保存配置(write memory)",
    "全域名": "需要先配置sdns listener, 启用SDNS功能",
    "递归": "需要先配置sdns listener, 启用SDNS功能",
    "dig": "需要目标设备上已配置SDNS监听, 客户端网络可达",
    "删除sdns": "需要该配置已存在",
    "no sdns": "需要该配置已存在",
}

# CLI command pattern (starts with known device command prefix)
_CLI_CMD_RE = re.compile(
    r'^(?:no\s+)?(?:sdns|slb|ha\s|firewall|ip\s|show\s|clear\s|write\s|reboot|'
    r'sync(?:onfig)?\s|config\s|system\s|interface\s|vlan\s|bond\s)',
    re.IGNORECASE
)

# 步骤意图推断：根据原始描述推断该步的目的
# 描述格式: (actor, action) → "谁做什么"
_DESCRIBE_FORMAT: dict[tuple, str] = {
    ("APV_0", "cmds_config"): "APV0 批量下发配置",
    ("APV_0", "cmd_config"): "APV0 下发配置",
    ("APV_0", "execute"): "APV0 执行操作",
    ("APV_1", "cmds_config"): "APV1 批量下发配置",
    ("APV_1", "cmd_config"): "APV1 下发配置",
    ("APV_1", "execute"): "APV1 执行操作",
    ("test_env", "routera"): "客户端发起DNS请求",
    ("test_env", "clientc"): "客户端发起HTTP请求",
    ("test_env", "clientd"): "客户端发起请求",
    ("test_env", "server213"): "后端服务器操作",
    ("test_env", "server231"): "后端服务器操作",
    ("test_env", "server232"): "后端服务器操作",
    ("check_point", "found"): "断言应出现",
    ("check_point", "not_found"): "断言不应出现",
    ("check_point", "found_times"): "断言出现次数",
}
_DESCRIBE_DEFAULT = {
    "APV_0": "APV0 操作",
    "APV_1": "APV1 操作",
    "test_env": "客户端操作",
    "check_point": "断言检查",
}


def _infer_intent(describe: str, module: str, is_first: bool, has_prereq: bool) -> str:
    """原文完整保留，不截断，不加工。Skill 中有格式规则。"""
    return describe.strip()

    return " | ".join(parts)

# check_point 的 infer_from 模板
CHECK_INFER_TEMPLATES = {
    "配置添加成功": "上一步 show 输出中包含刚配置的内容",
    "配置成功": "上一步 show 输出中包含刚配置的内容",
    "配置下发成功": "上一步 show/查看输出中包含配置的关键参数",
    "配置失败": "上一步输出中提示错误或配置未生效",
    "删除成功": "上一步 show 输出中不包含被删除的配置项",
    "访问成功": "上一步客户端输出中包含期望的响应/解析结果",
    "可以访问成功": "上一步客户端输出中包含期望的响应/解析结果",
    "访问失败": "上一步客户端输出中不包含期望的响应/解析结果",
    "无法同步": "备机 show 输出中不包含主机配置的内容",
    "配置未被保存": "重启后 show 输出中不包含之前配置的参数",
    "正常响应": "上一步客户端输出中包含期望的响应数据",
    "可以使用且正常": "上一步操作输出中功能表现正常",
    "不可以使用": "上一步操作输出中功能不可用或报错",
    "配置下发成功，访问成功": "配置命令无报错，且客户端输出中包含期望结果",
    # 通用后缀匹配
    "全域名功能可以使用且正常": "上一步操作输出中功能表现正常",
    "全域名功能不可以使用": "上一步操作输出中功能不可用",
    "监听配置添加成功": "上一步 show 输出中包含刚配置的监听地址",
}


def _classify_step(text: str) -> tuple[str, str]:
    """根据 step 文本推断 actor 和基础意图。"""
    text_lower = text.lower()
    for pattern, actor, _desc in ACTOR_RULES:
        if re.search(pattern, text_lower):
            return actor, _desc
    return ACTOR_DEFAULT, '通用操作'


def _infer_action(actor: str, step_text: str) -> tuple[str, str]:
    """根据 actor 和 step 文本推断 action。"""
    text_lower = step_text.lower()
    rules = ACTION_RULES.get(actor, [])
    for pattern, action, desc in rules:
        if re.search(pattern, text_lower):
            return action, desc
    return ACTION_DEFAULT.get(actor, 'cmd_config'), '默认操作'


def _infer_g_fill(actor: str, step_text: str, is_check: bool) -> str:
    """推断 G 列填充策略。"""
    # execute action on APV is direct (reboot, write mem)
    if actor in ('APV_0', 'APV_1'):
        if re.search(r'write\s|保存|save|reboot|重启|升级|降级', step_text.lower()):
            return G_FILL_DIRECT
    return G_FILL_RULES.get(actor, G_FILL_INFER)


def _build_check_infer_from(expected_text: str, prev_step: dict | None) -> dict:
    """为 check_point 步骤构建 infer_from 上下文。"""
    # Try to match known templates
    clean_expected = expected_text.strip()
    for template_key, template_desc in CHECK_INFER_TEMPLATES.items():
        if template_key in clean_expected:
            prev_desc = prev_step.get('describe', '未知操作') if prev_step else '上一步操作'
            prev_data = prev_step.get('data', '') if prev_step else ''
            return {
                "prev_step": prev_desc,
                "expected_meaning": template_desc,
                "concrete_example": prev_data if prev_data else "(需根据上下文推断具体匹配字符串)",
            }
    # Fallback: generic
    return {
        "prev_step": prev_step.get('describe', '上一步操作') if prev_step else '上一步操作',
        "expected_meaning": clean_expected,
        "concrete_example": "(需根据上下文推断具体匹配字符串)",
    }


def _build_prereq_hint(prereq_text: str, module: str = "") -> str:
    """从用例前置条件文本中提取 CLI 命令 hint。"""
    text_lower = (module + " " + prereq_text).lower()
    hints = []

    # 提取括号中的 CLI 命令
    cmd_match = re.findall(r'\(([^)]+)\)', prereq_text)
    for cmd in cmd_match:
        if re.search(r'sdns|slb|ha\s|firewall|ip\s|show|write|reboot|no\s', cmd, re.IGNORECASE):
            hints.append(cmd.strip())

    # 关键词→命令映射
    if 'sdns on' in text_lower or '启用sdns' in text_lower:
        hints.append('sdns on')
    if 'host name' in text_lower or '域名' in text_lower:
        hints.append('sdns host name <domain> <ttl>')
    if 'service ip' in text_lower:
        hints.append('sdns service ip <name> <ip> [port]')
    if 'pool name' in text_lower or '服务池' in text_lower:
        hints.append('sdns pool name <name> [max] [min]')
    if 'pool service' in text_lower:
        hints.append('sdns pool service <pool> <service>')
    if 'host pool' in text_lower:
        hints.append('sdns host pool <host> <pool>')
    if 'listener' in text_lower:
        hints.append('sdns listener <ip> [port]')
    if 'slb virtual' in text_lower or '虚拟服务' in text_lower:
        hints.append('slb virtual <type> <name> <ip> <port> arp 0')
    if 'slb group' in text_lower:
        hints.append('slb group method <name> ...')
    if 'slb real' in text_lower:
        hints.append('slb real <type> <name> <ip> <port> ...')
    if 'ha link' in text_lower or 'ha unit' in text_lower or 'ha on' in text_lower:
        hints.append('ha link ffo <iface>; ha unit <id>; ha on')
    if 'ha fip' in text_lower:
        hints.append('ha fip <ip>')
    if 'zone name' in text_lower or 'nameserver' in text_lower or 'record' in text_lower:
        hints.append('sdns zone name <domain> master; sdns nameserver name <ns> <ip>; sdns record a <name> <host> <ip>')

    if not hints:
        hints.append(prereq_text[:80])

    return '; '.join(hints[:5])


def _infer_verify_hint(prev_steps: list[dict], module: str, check_desc: str) -> tuple[str | None, str | None]:
    """@deprecated 职责已移至主 agent（SKILL.md Step 2.5 LLM 推断）。

    此函数仅处理 show 命令，不处理 trigger（dig/ping/curl），已被主 agent
    LLM 推断替代。保留供未来回退参考。
    """
    combined = (module + " " + check_desc).lower()
    client_kw = ["访问", "dig ", "ping ", "curl", "wget", "响应", "解析", "请求", "发包", "客户端", "打流量"]

    # 检查点本身描述就含客户端关键词 → 客户端验证，不需要 show
    if any(kw in combined for kw in client_kw):
        return None, None

    # 往前找最近的设备配置步骤
    for s in reversed(prev_steps):
        actor = s.get("actor", "")
        action = s.get("action", "")
        if actor in ("APV_0", "APV_1") and action in ("cmd_config", "cmds_config", "execute"):
            # 从上一个设备步骤的 hint/describe 推断 show 命令
            hint = s.get("hint", "")
            desc = s.get("describe", "")
            step_text = (hint + " " + desc).lower()

            # 按 hint 关键词推断对应的 show 命令
            if "persistence" in step_text or "会话保持" in step_text:
                return "APV_0", "show sdns host persistence"
            if "forward_only" in step_text or "zone forward" in step_text:
                return "APV_0", "show sdns host name"
            if "host name" in step_text:
                return "APV_0", "show sdns host name"
            if "service ip" in step_text:
                return "APV_0", "show sdns service ip"
            if "pool" in step_text:
                return "APV_0", "show sdns pool name"
            if "zone" in step_text:
                return "APV_0", "show sdns zone name"
            if "listener" in step_text:
                return "APV_0", "show sdns listener"
            if "slb" in step_text or "virtual" in step_text:
                return "APV_0", "show slb virtual-server"
            if "ha" in step_text:
                return "APV_0", "show ha status"
            if "dps" in step_text:
                return "APV_0", "show sdns dps path"
            if "rewrite" in step_text or "http" in step_text:
                return "APV_0", "show http rewrite response"
            # 默认
            return "APV_0", "show sdns listener"

    return None, None


def _build_hint(actor: str, action: str, describe: str, step_text: str) -> str:
    """为 APV/test_env 步骤构建 LLM 查询 hint。"""
    text_lower = step_text.lower()

    # Extract key command hints from step text
    hints = []

    # 数量提取：满配N条 / 配置N条 / N条 / 批量N个
    qty_match = re.search(r'(?:满配|配满|配置|批量)\s*(\d+)\s*(?:条|个)', text_lower)
    if not qty_match:
        qty_match = re.search(r'(?:共\s*)?(\d+)\s*(?:条|个)\s*(?:sdns|listener|rule|policy)', text_lower)
    if qty_match:
        hints.append(f'[数量: {qty_match.group(1)}条/个]')

    if 'listener' in text_lower:
        hints.append('sdns listener <ip> [port]')
    if '全域名' in text_lower or '域名功能' in text_lower:
        hints.append('sdns host name <domain> <ttl>  — 开启全域名解析功能')
    if 'host' in text_lower and 'forward' in text_lower:
        hints.append('sdns host name <name> <ttl> forward_only')
    if 'host' in text_lower and 'pool' in text_lower:
        hints.append('sdns host pool <host> <pool>')
    if 'service' in text_lower:
        hints.append('sdns service ip <name> <ip> [port]')
    if 'pool' in text_lower and 'service' in text_lower:
        hints.append('sdns pool service <pool> <service>')
    if 'pool' in text_lower:
        hints.append('sdns pool name <name> [max] [min]')
    if 'virtual' in text_lower or 'slb' in text_lower:
        hints.append('slb virtual <type> <name> <ip> <port> arp 0')
    if 'real' in text_lower:
        hints.append('slb real <type> <name> <ip> <port> <maxconn> <proto> <hc> <interval>')
    if 'group' in text_lower:
        hints.append('slb group method/member <name> ...')
    if 'policy' in text_lower:
        hints.append('slb policy default <vs> <group>')
    if 'show' in text_lower:
        if 'listener' in text_lower:
            hints.append('show sdns listener')
        elif 'sdns' in text_lower:
            hints.append('show sdns <subcommand>')
        elif 'slb' in text_lower:
            hints.append('show slb <subcommand>')
    if 'write mem' in text_lower:
        hints.append('write mem')
    if 'write file' in text_lower:
        hints.append('write file')
    if 'write all' in text_lower:
        hints.append('write all')
    if 'write net' in text_lower:
        hints.append('write net')
    if 'reboot' in text_lower or '重启' in text_lower:
        hints.append('system reboot noninteractive')
    if 'ha' in text_lower or '同步' in text_lower:
        hints.append('ha runtime-sync enable / sync to / sync from')
    if 'dig' in text_lower:
        hints.append('dig @<dns_ip> <domain> [+tcp]')
    if 'ping' in text_lower:
        hints.append('ping <target_ip>')
    if '访问' in text_lower and 'dig' not in text_lower:
        hints.append('dig @<ip> <domain> 或 curl <url>')

    if not hints:
        # Fallback: use describe text but strip numbering
        clean = re.sub(r'^\d+[\.\、\)]\s*', '', describe)
        hints.append(clean[:80])

    return '; '.join(hints[:5])


@tool
def qa_decompose_test_cases(extracted_json_path: str) -> str:
    """Decompose extracted test cases into E/F/G step skeletons.

    Takes the output of qa_extract_test_cases (Step 1) and decomposes each
    test case into a sequence of atomic steps. Each step specifies:
    - D (describe): what this step does in plain language
    - E (actor): which device/role executes (APV_0, test_env, check_point, ...)
    - F (action): which method to call (cmd_config, found, routera, ...)
    - g_fill: how to fill the G column (llm_pdf / llm_infer / direct)
    - hint or infer_from: context for LLM to generate the actual G value

    Extensible: new actors, actions, g_fill strategies can be added by
    extending the config constants at the top of this module.

    Args:
        extracted_json_path: Path to the Step 1 output JSON file
            (e.g. "yzg/input/yzg_extracted.json").

    Returns:
        JSON string with: status, file_name, total_cases,
        cases (list of decomposed cases with steps).
    """
    p = Path(extracted_json_path)
    candidates = [p, _PROJECT_ROOT / extracted_json_path]
    resolved = None
    for c in candidates:
        if c.exists():
            resolved = c
            break
    if resolved is None:
        return json.dumps({
            "status": "error",
            "error": f"File not found: {extracted_json_path}",
        }, indent=2, ensure_ascii=False)

    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "error": f"Failed to parse JSON: {exc}",
        }, indent=2, ensure_ascii=False)

    # 每次调用重置注入缓存，确保依赖和前置正确注入
    _INJECTED_PREREQ.clear()
    _INJECTED_DEPS.clear()

    if data.get("status") != "success":
        return json.dumps({
            "status": "error",
            "error": f"Input file is not a valid Step 1 output: {data.get('status')}",
        }, indent=2, ensure_ascii=False)

    test_cases = data.get("test_cases", [])
    # 读取模块级前置（新格式：modules 是字典）
    modules_info = data.get("modules", {})
    if isinstance(modules_info, list):
        # 兼容旧格式：modules 是列表
        modules_info = {mod: {} for mod in modules_info}

    results: list[dict[str, Any]] = []

    for case in test_cases:
        case_id = case.get("id", 0)
        module = case.get("module", "")
        steps = case.get("steps", [])
        expected = case.get("expected", [])
        level = case.get("level", "")
        priority = case.get("priority", 2)
        # 统一生成 577 开头 20 位随机 autoid（覆盖脑图中的原始值）
        autoid = "577" + str(random.randint(10**16, 10**17 - 1))
        cid_prefix = case_id

        decomposed_steps: list[dict[str, Any]] = []
        case_group = "default"  # init group for xlsx splitting
        all_steps_text = " ".join(steps) if steps else ""

        # === Step order: C=1 init → C=2,3... deps → C=n case steps ===

        # 1. Inject prerequisite (C=1) — only for first case in group
        big_module, group_name = _detect_module_and_group(module, all_steps_text)
        case_group = group_name

        # 优先使用 extracted.json 中的模块级前置，fallback 到硬编码的 _FEATURE_PREREQUISITES
        module_prereqs = modules_info.get(module, {}).get("module_prerequisites", [])
        if module_prereqs:
            # 使用从脑图提取的模块级前置
            if group_name not in _INJECTED_PREREQ:
                _INJECTED_PREREQ.add(group_name)
                for prereq_text in module_prereqs:
                    decomposed_steps.append({
                        "c": 1,
                        "phase": PHASE_SETUP,
                        "type": TYPE_DEVICE_CONFIG,
                        "actor": "APV_0", "action": "cmds_config",
                        "describe": f"[前置] {prereq_text}",
                        "g_fill": G_FILL_PDF,
                        "hint": _build_prereq_hint(prereq_text, module),
                    })
        else:
            # Fallback: 使用硬编码的 _FEATURE_PREREQUISITES
            prereq_info = _get_prereq_info(big_module)
            prereq_steps = prereq_info.get("init", [])
            if group_name not in _INJECTED_PREREQ:
                _INJECTED_PREREQ.add(group_name)
                for ps in prereq_steps:
                    domain = "autotest.com"
                    dm = re.search(r'["\']([\w*.-]+\.[\w]{2,})["\']', all_steps_text)
                    if not dm: dm = re.search(r'([\w-]+\.[\w-]+\.[\w]{2,})', all_steps_text)
                    if dm: domain = dm.group(1)
                    ip = "172.16.35.231"
                    im = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', all_steps_text)
                    if im: ip = im.group(1)
                    describe = ps["describe"].replace("autotest.com", domain).replace("172.16.35.231", ip)
                    decomposed_steps.append({
                        "c": 1,
                        "phase": PHASE_SETUP,
                        "type": TYPE_DEVICE_CONFIG,
                        "actor": ps["actor"], "action": ps["action"],
                        "describe": describe, "g_fill": G_FILL_PDF,
                        "hint": ps.get("hint", ""), "_domain": domain, "_ip": ip,
                    })

        # 2. Inject feature dependencies (C=2,3,...) after init, before case steps
        c_counter = 2
        # Also check expected text for dependency keywords
        deps_check_text = all_steps_text + " " + " ".join(expected)
        for dep_key, dep_steps in _FEATURE_DEPENDENCIES.items():
            if dep_key in deps_check_text.lower() and (group_name, dep_key) not in _INJECTED_DEPS:
                _INJECTED_DEPS.add((group_name, dep_key))
                for ds in dep_steps:
                    # Customize show hint based on module
                    hint = ds.get("hint", "")
                    if "listener" in module.lower() or "listenser" in module.lower():
                        hint = "show sdns listener"
                    elif "persistence" in module.lower():
                        hint = "show sdns host persistence"
                    elif "递归" in module:
                        hint = "show sdns host name"
                    decomposed_steps.append({
                        "c": c_counter,
                        "phase": PHASE_SETUP,
                        "type": TYPE_DEVICE_CONFIG,
                        "actor": ds["actor"], "action": ds["action"],
                        "describe": ds["describe"], "g_fill": G_FILL_PDF, "hint": hint,
                    })
                    c_counter += 1

        # 3. Inject case-level prerequisites (from extractor) — after deps, before case steps
        # 每个 case 独立的前置条件步骤，与 C=1 共享 init 不同
        case_prereqs = case.get("case_prerequisites", [])
        _injected_case_prereqs: set[str] = set()  # 本 case 内去重
        for prereq_text in case_prereqs:
            prereq_text = prereq_text.strip()
            if not prereq_text or prereq_text in _injected_case_prereqs:
                continue
            _injected_case_prereqs.add(prereq_text)
            decomposed_steps.append({
                "c": c_counter,
                "phase": PHASE_SETUP,
                "type": TYPE_DEVICE_CONFIG,
                "actor": "APV_0",
                "action": "cmds_config" if ";" in prereq_text or "、" in prereq_text else "cmd_config",
                "describe": f"[用例前置] {prereq_text}",
                "g_fill": G_FILL_PDF,
                "hint": _build_prereq_hint(prereq_text, module),
            })
            c_counter += 1

        # 4. Case description + steps
        # 用例描述优先用 extracted JSON 的 description 字段（脑图 priority=2 节点文本）
        case_desc = case.get("description", "") or (steps[0][:60] if steps else module.split(" > ")[-1])

        # 获取 step_expected_map（步骤拆分前）
        step_expected_map = case.get("step_expected", {})

        # ── 拆分步骤：先拆编号子步骤，再拆复合动作 ──
        # 记录原始索引到新索引的映射（expected 应该对应拆分后的最后一个步骤）
        old_to_new_idx: dict[int, int] = {}
        _flat_steps: list[str] = []
        new_idx = 0
        for old_idx, s in enumerate(steps):
            # 先尝试拆分编号子步骤
            split_s = _split_numbered_sub_steps(s.strip())
            if split_s:
                _flat_steps.extend(split_s)
                old_to_new_idx[old_idx] = new_idx + len(split_s) - 1  # 最后一个拆分步骤
                new_idx += len(split_s)
            else:
                # 再尝试拆分复合动作（逗号、顿号、"并且"连接的多个动作）
                split_c = _split_compound_actions(s.strip())
                if split_c:
                    _flat_steps.extend(split_c)
                    old_to_new_idx[old_idx] = new_idx + len(split_c) - 1  # 最后一个拆分步骤
                    new_idx += len(split_c)
                else:
                    _flat_steps.append(s)
                    old_to_new_idx[old_idx] = new_idx
                    new_idx += 1
        steps = _flat_steps

        # 更新 step_expected_map 的索引（步骤拆分后，expected 对应最后一个拆分步骤）
        if step_expected_map:
            new_step_expected_map: dict[int, list[str]] = {}
            for old_idx_str, exps in step_expected_map.items():
                old_idx = int(old_idx_str)
                if old_idx in old_to_new_idx:
                    new_step_expected_map[old_to_new_idx[old_idx]] = exps
            step_expected_map = new_step_expected_map

        # Decompose each step
        for i, step_text in enumerate(steps):
            text = step_text.strip()
            if not text:
                continue

            # Strip [check] marker for classification, but remember if it had one
            has_check = _has_check_marker(text)
            clean_text = _strip_check_marker(text)

            # ── 检测显式前置条件标签（"前提条件: xxx" / "前置: xxx"）──
            prereq_label_match = _PREREQ_LABEL_RE.match(clean_text)
            if prereq_label_match:
                prereq_content = clean_text[prereq_label_match.end():].strip()
                if prereq_content and prereq_content not in _injected_case_prereqs:
                    _injected_case_prereqs.add(prereq_content)
                    decomposed_steps.append({
                        "c": c_counter,
                        "actor": "APV_0",
                        "action": "cmds_config" if (";" in prereq_content or "、" in prereq_content) else "cmd_config",
                        "describe": f"[用例前置] {prereq_content}",
                        "g_fill": G_FILL_PDF,
                        "hint": _build_prereq_hint(prereq_content, module),
                    })
                    c_counter += 1
                continue  # 前置标签行本身不作为常规步骤

            # ── 检测时间延迟（"N秒后xxx" / "sleep N" / "等待N秒xxx"）──
            time_seconds: int | None = None
            time_remaining: str = ""

            # 形式1: sleep N
            sleep_m = _TIME_SLEEP_RE.match(clean_text)
            if sleep_m:
                time_seconds = _parse_time_seconds(sleep_m.group(1), sleep_m.group(2))
                time_remaining = ""

            # 形式2: 等待N秒xxx
            if time_seconds is None:
                wait_m = _TIME_WAIT_RE.match(clean_text)
                if wait_m:
                    time_seconds = _parse_time_seconds(wait_m.group(1), wait_m.group(2))
                    time_remaining = wait_m.group(3).strip()

            # 形式3: N秒后xxx（开头数字+单位）
            if time_seconds is None:
                num_m = _TIME_START_RE.match(clean_text)
                if num_m:
                    time_seconds = _parse_time_seconds(num_m.group(1), num_m.group(2))
                    time_remaining = num_m.group(3).strip()

            if time_seconds is not None:
                # 推断 actor：剩余文本是客户端动作 → test_env，否则 APV_0
                rem_lower = time_remaining.lower()
                # 注入 sleep 步骤（等待在动作之前）
                decomposed_steps.append({
                    "c": c_counter,
                    "actor": "time",
                    "action": "sleep",
                    "describe": f"等待{time_seconds}秒",
                    "g_fill": G_FILL_DIRECT,
                    "data": f"sleep {time_seconds}",
                })
                c_counter += 1

                # 如果有剩余文本，继续处理；纯等待则跳过
                if time_remaining:
                    clean_text = time_remaining
                else:
                    continue

            # ── 检测"配置+客户端动作"合并步骤 → 拆为两步 ──
            # 例: "配置http rewrite response https端口，打流量" → 配置 + 打流量
            _CLIENT_ACTION_KW = r'(?:打流量|发送?(?:请求|流量|包)|客户端|连续.*?(?:请求|访问|dig|ping)|dig\s|ping\s|curl\s|wget\s|发包)'
            _SPLIT_RE = re.compile(
                r'^(.+)[，,]\s*(' + _CLIENT_ACTION_KW + r'.*)$',
                re.IGNORECASE
            )
            split_m = _SPLIT_RE.match(clean_text)
            if split_m:
                config_part = split_m.group(1).strip()
                client_part = split_m.group(2).strip()
                # 第一步：设备配置
                decomposed_steps.append({
                    "c": c_counter,
                    "actor": "APV_0",
                    "action": "cmd_config",
                    "describe": f"APV0 下发配置: {config_part}",
                    "g_fill": G_FILL_PDF,
                    "hint": _build_hint("APV_0", "cmd_config", config_part, config_part),
                })
                c_counter += 1
                # 第二步：客户端动作（继续走后面的分类逻辑处理）
                clean_text = client_part

            # 优先匹配 apv_action.py 高位动作 — F 列用关键字，G 列留空由执行引擎处理
            hl_match = _match_high_level_action(clean_text, module)
            if hl_match:
                hl_keyword, hl_actor, hl_desc = hl_match
                decomposed_steps.append({
                    "c": c_counter,
                    "actor": hl_actor,
                    "action": hl_keyword,
                    "describe": f"[高位动作] {hl_desc} | 原文: {clean_text[:60]}",
                    "g_fill": G_FILL_DIRECT,
                    "data": "",
                })
                c_counter += 1

                # 高位动作也需要注入验证步骤和 check_point
                if has_check:
                    # 注入验证步骤（如检查16条配置结果）
                    verify_keyword = _match_high_level_action_verify(hl_keyword)
                    if verify_keyword:
                        decomposed_steps.append({
                            "c": c_counter, "actor": "APV_0",
                            "action": verify_keyword,
                            "describe": f"[高位动作] 验证配置结果 | 原文: {clean_text[:40]}",
                            "g_fill": G_FILL_DIRECT, "data": "",
                        })
                        c_counter += 1

                    # 注入 check_point
                    exp_text = _match_expected_by_check(text, expected)

                    check_action = "found"
                    if any(kw in (exp_text or "") for kw in ["失败", "不能", "无法", "不支持", "错误", "未被保存", "未生效", "不存在", "不命中"]):
                        check_action = "not_found"

                    prev = decomposed_steps[-1] if decomposed_steps else None
                    decomposed_steps.append({
                        "c": c_counter, "actor": "check_point", "action": check_action,
                        "describe": f"断言应出现: {exp_text or clean_text[:30]}" if check_action == "found" else f"断言不应出现: {exp_text or clean_text[:30]}",
                        "g_fill": G_FILL_INFER,
                        "infer_from": _build_check_infer_from(exp_text or clean_text, prev),
                    })
                    c_counter += 1

                continue  # 高位动作已处理，跳过常规分类

            # 使用 phase + type 框架推断
            phase, type_, actor = _infer_phase_type(clean_text)
            action, action_desc = _infer_action(actor, clean_text)
            g_fill = _infer_g_fill(actor, clean_text, bool(expected))

            skip_entry = False

            # If step is already a raw CLI command, keep as standalone step (don't merge into init)
            if _CLI_CMD_RE.match(clean_text):
                actor = "APV_0"
                action = "cmd_config"
                g_fill = G_FILL_DIRECT
                # Don't merge — create a standalone cmd_config step with the CLI command as data
                enriched_describe = f"APV0 下发配置: {clean_text.strip()[:60]}"
                decomposed_steps.append({
                    "c": c_counter, "actor": actor, "action": action,
                    "describe": enriched_describe, "g_fill": g_fill,
                    "data": clean_text.strip(),
                })
                c_counter += 1
                skip_entry = True
                # Fall through — has_check block below still needs to process [checkN] markers

            # Detect prerequisites for this step
            has_prereq = any(
                kw in clean_text.lower() or kw in module.lower()
                for kw in _PREREQUISITE_RULES
            )
            prereq_desc = ""
            for kw, desc in _PREREQUISITE_RULES.items():
                if kw in clean_text.lower() or kw in module.lower():
                    prereq_desc = desc
                    break

            # Build enriched describe — actor/action 查表 + 原文
            # 注意：前置条件已作为独立步骤注入（case_prerequisites / 前置标签），
            # 不再在 describe 中重复添加"前提:"文本前缀
            who_what = _DESCRIBE_FORMAT.get((actor, action), _DESCRIBE_DEFAULT.get(actor, "操作"))
            enriched_describe = f"{who_what}: {clean_text.strip()}"
            # Build action step entry (skip pure expected-result lines)
            # 只跳过极短的状态词（<5字且无实质内容），保留完整断言描述
            is_pure_expected = (
                not clean_text or
                (len(clean_text) < 5 and actor == "check_point" and not has_check)
            )

            if not is_pure_expected and clean_text and not skip_entry:
                entry: dict[str, Any] = {
                    "c": c_counter,
                    "phase": phase,
                    "type": type_,
                    "actor": actor,
                    "action": action,
                    "describe": enriched_describe,
                    "g_fill": g_fill,
                }
                if prereq_desc:
                    entry["prerequisite"] = prereq_desc

                if g_fill == G_FILL_PDF:
                    entry["hint"] = _build_hint(actor, action, enriched_describe, clean_text)
                elif g_fill == G_FILL_INFER:
                    if actor == "check_point":
                        exp_text = _match_expected_by_check(text, expected)
                        prev = decomposed_steps[-1] if decomposed_steps else None
                        entry["infer_from"] = _build_check_infer_from(
                            exp_text or clean_text, prev
                        )
                    else:
                        entry["hint"] = _build_hint(actor, action, enriched_describe, clean_text)
                elif g_fill == G_FILL_DIRECT:
                    has_reboot = "reboot" in clean_text.lower() or "重启" in clean_text.lower()
                    reboot_cmd = "\nsystem reboot noninteractive" if has_reboot else ""
                    if "write mem" in clean_text.lower():
                        entry["data"] = f"write memory{reboot_cmd}"
                    elif "write file" in clean_text.lower():
                        entry["data"] = f"write file{reboot_cmd}"
                    elif "write all" in clean_text.lower():
                        entry["data"] = f"write all{reboot_cmd}"
                    elif "write net" in clean_text.lower():
                        entry["data"] = f"write net{reboot_cmd}"
                    elif has_reboot:
                        entry["data"] = "system reboot noninteractive"

                # check_point → 标记 need_verify，由主 agent 在 Step 2.5 用 LLM 推断 trigger/verify 步骤
                if actor == "check_point":
                    entry["need_verify"] = True

                decomposed_steps.append(entry)
                c_counter += 1

            # If step had [check] marker, add a separate check_point row
            # (outside entry creation block — also fires for CLI_CMD_RE steps that set skip_entry)
            if has_check and actor != "check_point":
                exp_text = _match_expected_by_check(text, expected)

                check_action = "found"
                # Determine check action from expected result + step context
                if any(kw in (exp_text or "") for kw in ["失败", "不能", "无法", "不支持", "错误", "未被保存", "未生效", "不存在", "不命中"]):
                    check_action = "not_found"
                # Delete/remove steps: verify the thing is GONE
                if any(kw in clean_text for kw in ["删除", "no ", "移除", "清除", "清空"]):
                    check_action = "not_found"

                prev = decomposed_steps[-1] if decomposed_steps else None
                exp_text_final = exp_text or f"验证{clean_text[:30]}"

                # Enriched describe for check_point
                check_describe = f"断言应出现: {exp_text_final}" if check_action == "found" else f"断言不应出现: {exp_text_final}"
                check_entry: dict[str, Any] = {
                    "c": c_counter,
                    "phase": PHASE_VERIFY,
                    "type": TYPE_CAPTURE_VERIFY,
                    "actor": "check_point",
                    "action": check_action,
                    "describe": check_describe,
                    "g_fill": G_FILL_INFER,
                    "infer_from": _build_check_infer_from(exp_text_final, prev),
                    "need_verify": True,  # 主 agent Step 2.5 LLM 推断 trigger/verify
                }
                decomposed_steps.append(check_entry)
                c_counter += 1

        # 5. 结构+内容双驱动创建 check_point
        # _NEG_KW 和 _ASSERT_KW 从 decomposer_keywords.md 加载（全局变量）

        # 5a. 结构驱动：step_expected 中有关联的步骤 → 插入 check_point
        # 只有实际步骤（非注入步骤）才消耗 orig_idx，expected 在对应步骤之后立即注入
        step_exp_map = {str(k): v for k, v in step_expected_map.items()}  # 转换为 str 键
        result_steps = []
        orig_idx = 0
        for ds in decomposed_steps:
            result_steps.append(ds)
            # 注入步骤不消耗原始步骤索引
            is_injected = (ds.get("c", 0) == 1 or
                          ds.get("action") == "sleep" or
                          "[用例前置]" in ds.get("describe", "") or
                          "[前置]" in ds.get("describe", ""))
            if is_injected:
                continue
            str_idx = str(orig_idx)
            if str_idx in step_exp_map:
                # 在当前步骤之后立即注入 check_point
                for exp_text in step_exp_map[str_idx]:
                    exp_clean = re.sub(r'\[check\d*\]', '', exp_text).strip()
                    if not exp_clean:
                        continue
                    # Skip if already covered by has_check injection (avoid duplicates)
                    if any(s.get("actor") == "check_point" and exp_clean[:20] in s.get("describe", "")
                           for s in decomposed_steps):
                        continue
                    ca = "not_found" if any(kw in exp_clean for kw in _NEG_KW) else "found"
                    cd = f"断言应出现: {exp_clean}" if ca == "found" else f"断言不应出现: {exp_clean}"
                    c_counter += 1
                    result_steps.append({
                        "c": c_counter,
                        "phase": PHASE_VERIFY,
                        "type": TYPE_CAPTURE_VERIFY,
                        "actor": "check_point", "action": ca,
                        "describe": cd, "g_fill": G_FILL_INFER,
                        "infer_from": _build_check_infer_from(exp_clean, ds),
                        "need_verify": True,
                    })
            orig_idx += 1
        decomposed_steps = result_steps

        # 5b. 内容兜底：未被覆盖的 expected 结果（无条件注入）
        for exp_text in expected:
            exp_clean = re.sub(r'\[check\d*\]', '', exp_text).strip()
            if not exp_clean:
                continue
            if any(s.get("actor") == "check_point" and exp_clean[:20] in s.get("describe", "")
                   for s in decomposed_steps):
                continue
            # 无条件注入 check_point，不依赖关键词过滤
            prev = decomposed_steps[-1] if decomposed_steps else None
            ca = "not_found" if any(kw in exp_clean for kw in _NEG_KW) else "found"
            cd = f"断言应出现: {exp_clean}" if ca == "found" else f"断言不应出现: {exp_clean}"

            # check_point 标记需要验证步骤（由主 agent 推断）
            c_counter += 1
            decomposed_steps.append({
                "c": c_counter,
                "phase": PHASE_VERIFY,
                "type": TYPE_CAPTURE_VERIFY,
                "actor": "check_point", "action": ca,
                "describe": cd, "g_fill": G_FILL_INFER,
                "infer_from": _build_check_infer_from(exp_clean, prev),
                "need_verify": True,
            })

        # Final C renumbering: after 5a/5b inject steps in the middle,
        # C values may be out of order. Renumber based on list position.
        # C=1 is reserved for file-level shared prerequisites (only first case
        # in each group). Non-first cases start from C=2 so their first step
        # isn't mistaken for a shared init when the xlsx generator skips C=1.
        has_init = any(ds.get("c") == 1 for ds in decomposed_steps)
        start_c = 1 if has_init else 2
        for i, ds in enumerate(decomposed_steps, start_c):
            ds["c"] = i

        # Build case result
        case_result: dict[str, Any] = {
            "case_id": case_id,
            "module": module,
            "level": level,
            "priority": f"P{priority}" if isinstance(priority, int) else str(priority),
            "autoid": autoid,
            "description": case_desc,
            "group": case_group,  # which init group this case belongs to
        }

        case_result["steps"] = decomposed_steps
        results.append(case_result)

    output = {
        "status": "success",
        "file_name": resolved.name,
        "total_cases": len(results),
        "g_fill_legend": {
            G_FILL_PDF: "LLM查询PDF手册获取精确CLI命令语法",
            G_FILL_INFER: "LLM根据上下文推断，无需PDF",
            G_FILL_DIRECT: "直接填充，固定值",
        },
        "cases": results,
    }

    return json.dumps(output, indent=2, ensure_ascii=False)
