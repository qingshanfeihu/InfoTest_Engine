"""LLM 提取产品事实 → RawFact 列表。

LLM 一次输出所有结构化字段（fact_kind/feature_path/fact_key/cli_syntax/...），
代码只做反序列化和最小校验。不做关键词判断、不做语义切分。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

from main.ist_core.memory.footprint.schema import RawFact

logger = logging.getLogger(__name__)

_THREAD_ID_RE = re.compile(r"thread_id:\s*(\S+)")

_SYSTEM_PROMPT = """\
你是 IST-Core 的产品知识提取助手。阅读给定文本（产品 CLI 文档 / agent 工作记忆），
提取**有原文证据支撑的产品事实**，调用 `emit_facts` 工具按其参数 schema 提交。
输出结构由工具 schema 强约束——你只做语义判断：抽什么、归到哪个 feature_path、引哪句证据。

## 各 fact_kind 何时用、填哪些字段

- **cli_command**（一条 CLI 命令的语法）：填 `cli_syntax` = **完整调用签名**（命令主体 + 全部参数，
  按正确顺序，用记法表示参数：必填 `<param>`、可选 `[param]`、枚举 `{a|b}`）。只写命令本身，
  禁止描述句、引号、中文标点、"用于"/"语法为"。
  - 签名要**完整规范**。文档对同一命令常分散呈现：标题行可能只列主体加个别参数，真正的参数集要
    结合紧随的参数表/说明才完整；规范定义与使用示例也常并存。综合还原出完整规范签名，不要照抄某一行
    残片，也不要把示例里选定的具体取值当成命令的一部分。
  - 参数值不是命令路径：枚举值 / 模式名 / 具体地址等是参数取值，只出现在记法里，绝不作独立命令 token。
  - 命令带命名参数且原文有参数表/说明 → 填 `parameters`（每参数一对象，`name` 必填作去重键；其余字段
    按原文如实给，如 `type`/`required`/`default`/`value_range`/`desc`，不限于此）。纯枚举开关直接写进
    `cli_syntax` 即可、`parameters` 留空。原文无参数信息就留空，不要编造或猜测取值范围。
  - **同一命令的 配置 / no / show / clear 各自是独立 cli_command**：分别给完整签名，它们 feature_path
    相同、代码会自动归到同一节点。
- **decision_rule**：`condition`（触发条件）+ `decision`（结论/默认值/限制）**两者都必填**。原文没有明确
  "条件 → 结论"两段时，**改用 behavior**。
  - **多分支条件行为必须逐条抽全**：同一命令/特性在**不同条件下有不同结论**时（按请求类型 / 查询类型 /
    模式 / 参数取值 / 命中与否 / 启用与否等分支），**每个分支各抽一条独立 decision_rule**，各带自己的
    condition 与 evidence_quote。**绝不要只抽其中一条、只抽概括句、或把多个并列分支合并成一句**——
    漏抽分支会让下游只看到片面行为、据此写错断言（例：手册"收到 CNAME 类请求→返回 CNAME 记录；
    收到 A/AAAA 类请求→用 CNAME 再解析返回 IP"是**两条** decision_rule，不是一条概括的"会重新查询"）。
- **behavior**：填 `content`（一句话功能行为）。**必须是某条 CLI 命令的行为说明**。架构概念 / 设计术语 /
  项目代号不是命令也不是命令行为，**不要提取**——知识树只收 CLI 命令及其相关事实，不收名词解释。
- **known_issue**：填 `issue_id`（BUG 编号）+ `issue_title`（**照抄 BUG title 原文，一字不改、不概括、不留空**）。
  可选 `affected_versions`。

## evidence（cli_command / decision_rule / behavior 必填；known_issue 不需要）

- `evidence_file`：这条事实在哪个文档能查到。真实路径，从所读文件的 path 获取，不要凭空构造。
- `evidence_quote`：**evidence_file 里的原文片段**，未经改写 / 合并 / 概括。merger 会用 grep 验证，
  grep 不到整条 fact 丢弃。取**最能直接证明该事实的那段原文**：cli_command 引命令定义/语法呈现那行
  （哪怕残缺）；decision_rule/behavior 引陈述该规则/行为的那句。不要用章节标题、
  泛泛导语、无关旁支句充数。
  - `cli_syntax` 是你综合还原的完整签名，`evidence_quote` 是文档原始呈现，两者不必逐字相同。
- known_issue 的 BUG 数据来自 API 而非磁盘文件，无需 evidence。
- condition / decision / content 可以是你的概括，但 `evidence_quote` 必须引用原文。
  cli/rule/behavior 找不到字面证据时，**宁可不提取**，不要用自己的话改写凑结构。

## feature_path（命令主体 token 序列）

- 剥 `no` / `show` / `clear` 操作前缀；**只放命令主体 token，不放参数值**
  （如 `show <a> <b> <c>` → `["a","b","c"]`；枚举/取值参数不进 path）。
- cli_command 的 path 代码会从 cli_syntax 兜底派生，但你仍应给对。
- known_issue 无明确命令时，从 BUG title/描述里找**真正的功能模块或命令**作锚点。注意 title 开头的
  方括号未必是模块名——可能是 OS/硬件环境标签、客户名等，这些**不是 feature_path**；要从问题描述本身
  找功能锚点（真实命令或功能模块名）。
- 找不到锚点就丢弃这条 fact，不要凭空造路径。
- 不用关心层级（leaf/trunk/branch）——代码按子节点关系自动重算，你只需给对 feature_path。

## feature_path 归一化（避免同一特性分裂成多个节点）

- **以真实 CLI 命令路径为锚**：某事实属于某条命令，就用那条命令的 token 序列，不要另造同义分组
  （不要造没有对应真实命令的路径）。
- known_issue 优先挂到命令节点；完全无法对应命令时才退化为模块名（长度=1）。
- **复用 `<existing_facts>` 里已存在的 feature_id**：上下文清单里已有语义相同的特性节点就直接用它，
  优先收敛到已有节点而非新增近义节点。
- 同义标准：描述的是**同一条命令 / 同一配置项 / 同一特性**，即使措辞不同也算同一特性。

## fact_key（决定 dedup，snake_case 描述该 fact 主题）

- cli_command 用命令核心 token；decision_rule 用规则主题；behavior 用行为主题；known_issue 直接用 issue_id。
- **复用已有 fact_key**：若 `<existing_facts>` 里某 fact 与你要提取的**语义等同**，必须复用同一 fact_key
  （哪怕措辞不同）；同一规则的不同复述映射到同一 key，否则产生重复。

## 绝对不要提取

- agent 工作计划（"接下来"/"需要找到"/"继续读取"）、评审建议（"应补充"/"建议修改"）、文件导航日志
  （"找到 N 个文件"）、等价映射（"等价于某友商型号"）、无原文证据的推测。

无可提取事实时，仍调用 emit_facts，传入空 facts 数组。
"""


# emit_facts 工具：facts[] 的完整 JSON Schema —— **结构的唯一真相源**。
def _nstr(desc: str) -> dict:
    """strict 模式可空字符串字段：不适用该 fact_kind 时填 null。"""
    return {"type": ["string", "null"], "description": desc}


# 经 function calling 作硬约束传给模型（schema 强制字段/类型/枚举）。
# **必须开 `strict: true`**：MiMo 等端点在非 strict 下不严格遵守 schema，会把 `facts` 数组
# **双重编码成 JSON 字符串**（且转义不一致）→ `_parse_llm_response` 整片静默丢弃，是 backfill
# 单遍漏命令的真根因（MiMo 官方文档 tools.function.strict）。strict 仅支持 JSON schema 子集：
# 所有对象须 `additionalProperties:false`、所有属性进 `required`、可选字段用 `["type","null"]` 表达。
# 各字段"哪个 kind 必填"的语义写在 description 里，不适用时模型填 null。
_PARAM_ITEM: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "description": "参数名。"},
        "required": {"type": ["boolean", "null"], "description": "是否必选。"},
        "type": _nstr("参数类型（string/integer/IP 地址…）。"),
        "default": _nstr("默认值。"),
        "value_range": _nstr("取值范围/约束。"),
        "desc": _nstr("参数说明（原文）。"),
    },
    "required": ["name", "required", "type", "default", "value_range", "desc"],
}

_FACT_ITEM: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "fact_kind": {
            "type": "string",
            "enum": ["cli_command", "decision_rule", "behavior", "known_issue"],
            "description": "事实类型，决定哪些字段填值（其余填 null）。",
        },
        "feature_path": {
            "type": "array", "items": {"type": "string"},
            "description": "命令主体 token 序列（剥 no/show/clear 前缀，不含参数值）。",
        },
        "fact_key": {
            "type": "string",
            "description": "同一 feature_path 下该 fact 的唯一短标识，snake_case；语义等同则复用已有 key。",
        },
        "cli_syntax": _nstr("fact_kind=cli_command 时填：完整命令调用签名（含全部参数记法），否则 null。"),
        "parameters": {
            "type": ["array", "null"], "items": _PARAM_ITEM,
            "description": "cli_command 的命名参数表（纯枚举开关填 []）；非 cli_command 填 null。",
        },
        "condition": _nstr("fact_kind=decision_rule 时填：触发条件，否则 null。"),
        "decision": _nstr("fact_kind=decision_rule 时填：结论/默认值/限制，否则 null。"),
        "content": _nstr("fact_kind=behavior 时填：一句话功能行为，否则 null。"),
        "issue_id": _nstr("fact_kind=known_issue 时填：BUG 编号，否则 null。"),
        "issue_title": _nstr("fact_kind=known_issue 时填：照抄 BUG title 原文一字不改，否则 null。"),
        "affected_versions": {
            "type": ["array", "null"], "items": {"type": "string"},
            "description": "known_issue 可选：受影响版本号列表，否则 null。",
        },
        "evidence_file": _nstr("cli/rule/behavior 必填：证据所在文档路径。"),
        "evidence_quote": _nstr("cli/rule/behavior 必填：evidence_file 中的原文片段，未经改写。"),
    },
    "required": [
        "fact_kind", "feature_path", "fact_key", "cli_syntax", "parameters",
        "condition", "decision", "content", "issue_id", "issue_title",
        "affected_versions", "evidence_file", "evidence_quote",
    ],
}

EXTRACTION_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "emit_facts",
        "strict": True,
        "description": "提交从给定文本中提取的、有原文证据支撑的结构化产品事实列表。无可提取时传空数组。",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "facts": {
                    "type": "array",
                    "description": "提取到的产品事实数组；无可提取事实时为空数组 []。",
                    "items": _FACT_ITEM,
                }
            },
            "required": ["facts"],
        },
    },
}


def _parse_thread_id(content: str) -> str:
    m = _THREAD_ID_RE.search(content)
    return m.group(1) if m else ""



_OP_PREFIXES = ("no", "show", "clear")

_NOTATION_PARAM_RE = re.compile(r"^[<\[{].*[>\]}]$")
# 整个记法参数组(从某个开括号到下一个闭括号,含内部空格/竖线):用于剥离前先整体清掉
_NOTATION_GROUP_RE = re.compile(r"[<\[{][^>\]}]*[>\]}]")

_MD_ESCAPE_RE = re.compile(r"\\([_*~])")


def _clean_token(tok: str) -> str:
    """去掉单个 token 的 markdown 噪声：转义 `\\_` + 首尾裸斜体标记 `_`/`*`。

    LLM 偶尔把命令主体连斜体标记一起回（`_ip_`/`*addr*`），不剥会产出 `_ip.address_`
    这类污染 feature_id 的影子节点。内部 `_`（如 host_name）只剥首尾不动。
    """
    return _MD_ESCAPE_RE.sub(r"\1", tok).strip("_*")


def _feature_path_from_syntax(cli_syntax: str) -> list[str]:
    """从完整 cli_syntax 派生 feature_path（命令主体 token 序列）。

    对齐 CLI legend（确定性正则，不含启发式字典）：
    - 剥前导操作子命令 no/show/clear（legend 定义的语法保留词，仅这 3 个）
    - 剥所有带记法的参数 token：<x>、[x]、{x|y}、[x|y]、含 | 的枚举段
    - 去 markdown 转义噪声
    示例：
      "show slb real http"              → ["slb","real","http"]
      "slb real http <rs_name> [port]"  → ["slb","real","http"]
      "ha synconfig bootup {on|off}"    → ["ha","synconfig","bootup"]
    """
    if not cli_syntax:
        return []
    # 先整体剥掉记法参数组(含内部空格/竖线):`<...>` `[...]` `{...}`——否则带空格的记法
    # 如 `[ipv4_netmask | ipv4_prefix]` split 后碎成 `[ipv4_netmask`/`|`/`ipv4_prefix]`,
    # 单 token 判定漏掉前两段、混进 feature_path。
    stripped = _NOTATION_GROUP_RE.sub(" ", cli_syntax)
    toks = stripped.split()
    while toks and toks[0].lower() in _OP_PREFIXES:
        toks = toks[1:]
    out: list[str] = []
    for raw in toks:
        tok = _clean_token(raw).strip()
        if not tok:
            continue
        # 跳过参数记法、含枚举竖线、以及嵌套记法剥不净残留的纯标点 token（如 `}`/`]`，
        # 否则混进 feature_id 生成 `health.check.}.json` 这类污染节点。
        if _NOTATION_PARAM_RE.match(tok) or "|" in tok or not re.search(r"[a-zA-Z0-9]", tok):
            continue
        out.append(tok.lower())
    return out


def _coerce_str_list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if x]
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    return []


def _coerce_parameters(v: Any) -> list[dict]:
    """清理 LLM 输出的参数表，不限定字段集合。

    只保证两点：每个参数有 name（merge 去重的键）；值是 JSON 标量或标量列表。
    字段名和语义完全由 LLM 决定——不做关键词→bool 映射、不做字段白名单，
    LLM 给什么就存什么（prompt 里建议常用字段，但不在代码里强制）。
    """
    if not isinstance(v, list):
        return []
    out: list[dict] = []
    for item in v:
        if not isinstance(item, dict):
            continue
        # null 兜底：strict schema 下 name 字段 required，模型对"无参/纯枚举开关"会填 JSON null；
        # item.get("name","") 因 key 存在返回 None → str(None)="None" 假参数。`or ""` 兜掉。
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        entry: dict = {"name": name}
        for k, val in item.items():
            if k == "name":
                continue
            if isinstance(val, (bool, int, float)):
                entry[k] = val
            elif isinstance(val, str):
                sval = val.strip()
                if sval:
                    entry[k] = sval
            elif isinstance(val, list):
                scalars = [
                    str(x).strip() for x in val
                    if isinstance(x, (str, int, float, bool)) and str(x).strip()
                ]
                if scalars:
                    entry[k] = scalars
        out.append(entry)
    return out


# 裸内层引号：两侧都是"内容字符"(非 JSON 结构 :,{}[]"、非空白、非反斜杠)的 `"`。
# 排除反斜杠 → 已转义的 `\"` 不会被再次转义(这是早期版本的 bug)。
_BARE_INNER_QUOTE_RE = re.compile(r'(?<=[^\s:,{}\[\]"\\])"(?=[^\s:,{}\[\]"])')


def _loads_facts_str(s: str) -> list:
    """解析被 stringify 的 facts 数组。

    ``EXTRACTION_TOOL`` 的 ``strict:true`` 已让端点**多数**把 facts 返回为真数组,但 MiMo 仍
    残留少量(~6%)把数组 stringify,且 stringify 时把描述里的全角引号转成 ASCII `"` 又漏转义
    (如 `保留字"default"`)→ json.loads 报 'Expecting , delimiter'。转义"两侧均为内容字符且
    未被转义"的裸引号后重解,可还原**完整** fact(含参数)；已转义的 `\"` 不动。修复失败才丢弃。
    """
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(_BARE_INNER_QUOTE_RE.sub(r'\\"', s))
    except json.JSONDecodeError:
        pass
    # 第三层兜底:json_repair 鲁棒修复。content/desc 里**密集裸引号 + 特殊字符**(如 `"||"`、`">"`、
    # `"$"`、`%c, %s` 列举)时,上面的边界正则覆盖不全——实测会丢 `sdns {on|off}` 总开关、
    # `sdns config write scp`、`sdns log query custom` 等关键命令。json_repair 对**合法 JSON 幂等**
    # (零破坏,已验证),且仅在前两层都失败时启用 → 只把原本要丢弃的救回,**不改变已能解析的路径**。
    try:
        import json_repair
        r = json_repair.loads(s)
        if isinstance(r, list) and r:
            return r
    except Exception:  # noqa: BLE001 — json_repair 缺失/异常 → 回退到原「丢弃」行为(零回归)
        pass
    logger.warning("footprint LLM facts 字符串修复后仍无法解析，丢弃: %s", s[:200])
    return []


def _parse_llm_response(raw: Any, thread_id: str) -> list[RawFact]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("footprint LLM 返回非 JSON: %s", raw[:200])
            return []

    if not isinstance(raw, dict):
        return []

    facts_raw = raw.get("facts", [])
    # 正常情况 facts 是数组(EXTRACTION_TOOL 开了 strict)。仅个别非 strict 端点会把它 stringify,
    # 防御性解一层(见 _loads_facts_str)。
    if isinstance(facts_raw, str):
        facts_raw = _loads_facts_str(facts_raw)
    if not isinstance(facts_raw, list):
        return []

    valid_kinds = {"cli_command", "decision_rule", "behavior", "known_issue"}
    results: list[RawFact] = []

    # strict schema 下模型对不适用字段填 JSON null → item.get 取到 None；统一 `or ""` 兜底
    # （否则 str(None) 会污染成字符串 "None"）。
    def _s(key: str) -> str:
        return str(item.get(key) or "").strip()

    for item in facts_raw:
        if not isinstance(item, dict):
            continue
        kind = _s("fact_kind")
        if kind not in valid_kinds:
            continue


        cli_syntax = _s("cli_syntax")
        if kind == "cli_command" and not cli_syntax:
            continue
        if kind == "decision_rule":
            if not item.get("condition") or not item.get("decision"):
                continue
        if kind == "behavior" and not item.get("content"):
            continue
        if kind == "known_issue" and not item.get("issue_id"):
            continue

        
        
        
        
        if kind == "cli_command":
            path = _feature_path_from_syntax(cli_syntax)
        else:
            # 非命令 fact(behavior/rule/issue)用 LLM 给的 feature_path,但要与 cli_command
            # 路径对齐剥前导操作动词 no/show/clear:LLM 常把它们写进 path(如"clear config all
            # 的行为"→ ["clear","config","all"]),不剥就生成 clear.config.all 这类动词影子节点,
            # 与规范裸节点 config.all 分裂、且每次 dream 再生。剥后为空(整条都是动词)则保留原样不丢 fact
            # (刻意设计,见 test_extract_noncommand_all_verb_path_preserved:宁留动词节点也不丢 fact)。
            raw_path = [p.lower() for p in _coerce_str_list(item.get("feature_path")) if p]
            j = 0
            while j < len(raw_path) and raw_path[j] in _OP_PREFIXES:
                j += 1
            path = raw_path[j:] if 0 < j < len(raw_path) else raw_path
        if not path:
            continue

        fact_key = _s("fact_key")
        if not fact_key:
            continue

        results.append(RawFact(
            fact_kind=kind,  # type: ignore[arg-type]
            feature_path=path,
            fact_key=fact_key,
            cli_syntax=cli_syntax,
            parameters=_coerce_parameters(item.get("parameters")),
            condition=_s("condition"),
            decision=_s("decision"),
            content=_s("content"),
            issue_id=_s("issue_id"),
            issue_title=_s("issue_title"),
            affected_versions=_coerce_str_list(item.get("affected_versions")),
            evidence_file=_s("evidence_file"),
            evidence_quote=_s("evidence_quote")[:300],
            source_thread=thread_id,
        ))

    return results


def _format_existing_facts(existing_facts: dict | None) -> str:
    """把现有 footprint 树的 fact_key 清单格式化进 LLM prompt。

    Args:
        existing_facts: {feature_id: {kind: [(fact_key, content_sample), ...]}}
    """
    if not existing_facts:
        return ""
    lines = ["<existing_facts>",
             "以下是已经存在的 footprint 节点和它们的 fact_keys（含已记录的命令参数、已知缺陷）。",
             "提取时：语义等同的事实必须复用同一 fact_key；BUG 优先挂到这里已有的命令节点；",
             "命令参数若已列出，不要重复输出。", ""]
    for feature_id in sorted(existing_facts.keys()):
        kinds = existing_facts[feature_id]
        if not any(kinds.values()):
            continue
        lines.append(f"## {feature_id}")
        for kind in ("cli_command", "decision_rule", "behavior", "known_issue"):
            entries = kinds.get(kind, [])
            if not entries:
                continue
            lines.append(f"  {kind}:")
            for fact_key, sample in entries:
                lines.append(f"    - {fact_key}: {sample[:120]}")
        lines.append("")
    lines.append("</existing_facts>")
    lines.append("")
    return "\n".join(lines)


def extract_facts(
    content: str,
    *,
    llm_chat: Callable | None = None,
    existing_facts: dict | None = None,
) -> list[RawFact]:
    """从给定文本中提取 RawFact 列表。

    Args:
        content: 源文本（产品文档 / working memory 文件全文）
        llm_chat: LLM 调用函数 ``(system_prompt, user_prompt, tool) -> dict``——经
            function calling 把 ``EXTRACTION_TOOL`` 作硬约束传入,返回解析后的 ``{"facts":[...]}``。
        existing_facts: 现有 footprint 节点的 fact_key 清单（用于 LLM 复用）
    """
    if llm_chat is None:
        return []

    thread_id = _parse_thread_id(content)

    user_prompt = _format_existing_facts(existing_facts) + content

    try:
        result = llm_chat(_SYSTEM_PROMPT, user_prompt, EXTRACTION_TOOL)
    except Exception as exc:
        logger.warning("footprint LLM 调用失败: %s", exc)
        return []

    return _parse_llm_response(result, thread_id)
