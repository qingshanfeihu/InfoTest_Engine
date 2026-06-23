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
你是 IST-Core 的产品知识提取助手。阅读 agent 的工作记忆（含 tool 调用、AI 思考），
提取**已被 CLI 文档或 BUG 数据验证过的产品事实**，按下列严格 JSON 输出。

## 输出契约

```json
{
  "facts": [
    {
      "fact_kind": "cli_command | decision_rule | behavior | known_issue",
      "feature_path": ["http","rewrite","body"],
      "fact_key": "<同一 feature_path 下该 fact 的唯一短标识，雪花式 snake_case>",

      "cli_syntax": "http rewrite body {on|off}",
      "parameters": [],
      "condition": "不配置 http rewrite body limit",
      "decision": "默认可改写 HTTP 内容长度上限为 5120KB",
      "content": "HTTP 内容改写功能基于规则改写后台响应",
      "issue_id": "BUG-70233",
      "issue_title": "[Http rewrite body] Fail to rewrite a 1024KB file",
      "affected_versions": ["10.4.2","10.4.3"],

      "evidence_file": "knowledge/data/markdown/product/10.5_cli__part2_p201-400.md",
      "evidence_quote": "http rewrite body {on|off}"
    }
  ]
}
```

## 字段填写规则（按 fact_kind 二选一，其他字段留空字符串/空数组）

- **cli_command**: 必填 `cli_syntax` = 这条命令的**完整调用签名**——命令主体 + 全部参数，按正确顺序，用记法表示参数（必填 `<param>`、可选 `[param]`、枚举 `{a|b}`）。只写命令本身，禁止描述句、引号、中文标点、"用于"/"语法为"。
  - 签名应**完整且规范**。文档对同一命令的呈现常不完整：标题行可能只列命令主体加个别参数，真正的参数集要结合紧随的参数表/说明才完整；同一命令也常并存规范定义（`ha synconfig bootup {on|off}`）和使用示例（`ha synconfig bootup on`）。综合这些信息还原出完整规范签名，而不是照抄某一行残片或把示例里选定的具体值当命令的一部分。
  - 参数值不是命令路径。`on`/`off`/mode 名/具体 IP 等是参数取值，只出现在记法里（`{on|off}`），绝不作为独立命令 token。
  - 命令若带命名参数且原文有参数表/参数说明，填 `parameters` 数组（每参数一对象，`name` 必填作去重键；其余字段按原文如实给，常见 `type`/`required`/`default`/`value_range`/`desc`，不限于此）。纯枚举开关（`{on|off}`）直接写进 cli_syntax 即可、`parameters` 留空。原文没有参数信息就留空 `[]`，不要编造或猜测取值范围。
  - **同一命令的 no/show/clear/配置 是不同的 cli_command 各自提取**：`slb real http <rs>`、`no slb real http`、`show slb real http` 是三条命令，cli_syntax 各填完整签名，它们会自动归到同一节点
- **decision_rule**: `condition`（触发条件）+ `decision`（结论/默认值/限制）**两边都必填**。如果原文没有明确"条件 → 结论"两段，**改用 behavior**。
- **behavior**: 必填 `content`（一句话功能行为）。**注意：behavior 必须是某条 CLI 命令的行为说明**。如果内容是架构概念/设计术语/项目代号（如"Ustack 是 XX 堆栈的代号"），它**不是 CLI 命令也不是命令行为，不要提取为 fact**——产品知识树只收 CLI 命令及其相关事实，不收架构名词解释
- **known_issue**: 必填 `issue_id`（BUG-XXXXX 格式）+ **必填 `issue_title`**。`issue_title` 直接照抄 `kb_bug_search` 返回的 `title` 字段原文，**一字不改、不要概括、不要留空**。可选 `affected_versions`

## evidence 字段（cli_command / decision_rule / behavior 必填，known_issue 不需要）

- `evidence_file`: cli/rule/behavior 必填。这条事实在哪个产品文档中能查到。必须是真实路径（如 `knowledge/data/markdown/product/10.5_cli__part2_p201-400.md`），从 tool 调用的 path 参数中获取，不要凭空构造
- `evidence_quote`: cli/rule/behavior 必填。**必须是 evidence_file 里的原文片段**，未经任何改写、合并、概括。merger 会用 grep 验证：如果 evidence_quote 在 evidence_file 里 grep 不到，整条 fact 会被丢弃
  - 取**最能直接证明这条事实的那段原文**，而不是任意能 grep 到的文字。对 cli_command，引命令定义/语法呈现的那一行（哪怕它在文档里是残缺形态）；对 decision_rule/behavior，引陈述该规则或行为的那句。不要用章节标题、泛泛的导语或不相关的旁支句来充数。
  - cli_syntax 与 evidence_quote 角色不同：cli_syntax 是你综合还原的完整签名，evidence_quote 是文档里支撑它的原始呈现，两者不必逐字相同。
- **known_issue 类型不需要 evidence_file / evidence_quote**：有 issue_id 就够了。BUG 数据来自 kb_bug_search API 而非磁盘文件，无需提供文件路径
- 对于 cli/rule/behavior：如果原文找不到对应字面证据，宁可不提取这条 fact，也不要为了凑结构化用自己的话改写

注意：condition / decision / content 这三个字段可以是你的概括，但 evidence_quote 必须是引用原文。

## feature_path 填写规则

- 写命令的完整路径 token，剥离 `no` / `show` / `clear` 操作前缀
- 例：`show http rewrite body limit` → `["http","rewrite","body","limit"]`
- **只放命令主体 token，不放参数值**：`ha synconfig bootup {on|off}` → `["ha","synconfig","bootup"]`，`on`/`off` 是参数值不进 path
- cli_command 的 path 由代码从 cli_syntax 自动派生兜底，但你仍应给出正确的 path
- known_issue 没有明确命令时，从 BUG title / description 里识别**真正的功能模块或命令**来定 path。
  注意：title 开头的方括号未必是模块名——`【中标麒麟】`/`【飞腾】`是 OS/硬件环境标签，`[佛山农商行]`是客户名，
  这些**不是 feature_path**。要从问题描述本身找功能锚点：如"HA 同步无法同步 accessgroup 配置"→ 锚点是 `accessgroup`（真实命令）或 `ha`（功能模块），不是 `中标麒麟`
- 不要给 facts 凭空捏造路径——找不到就丢弃这条 fact
- **不用关心层级（leaf/trunk/branch）**：节点在树里的层级由代码按子节点关系自动重算，你只需给对 feature_path

## feature_path 归一化（避免同一特性分裂成多个节点）

同一个产品特性必须落到**唯一一条** feature_path，不要因为措辞不同而拆散：

- **以真实 CLI 命令路径为锚**。某事实如果属于某条命令，feature_path 就用那条命令的 token 序列，不要另造同义分组。
  例：cookie 会话保持加密由 `slb mode ircookie` 命令配置 → 所有相关 fact（含 BUG）都归到 `["slb","mode","ircookie"]`，
  不要新造 `["cookie","encryption"]` / `["slb","cookie"]` / `["slb","ircookie"]` 这些没有对应真实命令的路径
- **known_issue 优先挂到命令节点**。BUG 若涉及某条已知命令，用该命令的 feature_path；
  只有当 BUG 完全无法对应任何命令时，才退化为 trunk（长度=1）的模块名
- **复用 `<existing_facts>` 里已存在的 feature_id**。如果上下文清单里已有语义相同的特性节点，
  直接用它的 feature_path，不要新建近义节点。优先收敛到已有节点而非新增
- 同义判断标准：两条 fact 描述的是**同一条命令 / 同一个配置项 / 同一个特性**，
  即使用词不同（"cookie加密" vs "ircookie enc 模式" vs "会话保持加密"）也算同一特性

## fact_key 填写规则（决定 dedup）

- snake_case，描述这条 fact 的"主题"
- cli_command: 用命令的核心 token，例 `syntax`、`limit_syntax`
- decision_rule: 用规则主题，例 `default_limit_5120kb`、`group_name_default_global`
- behavior: 用行为主题，例 `rewrite_response_body`、`encryption_aes_cbc_256`
- known_issue: 直接用 issue_id

## 复用已有 fact_key（重要）

如果 user prompt 顶部出现 `<existing_facts>` 块，里面列出了某个 feature_path 已经存在的 fact_keys 和它们对应的内容样例。

- 当你提取的事实**语义上等同于**清单中某条已有事实时，**必须复用同一个 fact_key**（哪怕措辞不同）
- 例：清单已有 `feature_path=["slb","mode","ircookie"]` 的 `rules.group_name_default_global`，
  你又看到原文说"未指定 group_name 时使用 global"，应该用 fact_key=`group_name_default_global`，不要起 `default_group_global` / `group_name_default` 这类同义新 key
- 同一规则的不同复述必须映射到同一个 key，否则会产生重复

## 负面约束（绝对不要提取）

- agent 工作计划（"接下来"、"需要找到"、"继续读取"）
- 评审建议（"应补充"、"缺少"、"建议修改"）
- 文件导航日志（"找到 N 个文件"）
- 等价映射（"等价于 F5/A10"）
- 没有原文证据的推测

## 输出

只输出 JSON。无可提取事实时输出 `{"facts": []}`。
"""


def _parse_thread_id(content: str) -> str:
    m = _THREAD_ID_RE.search(content)
    return m.group(1) if m else ""



_OP_PREFIXES = ("no", "show", "clear")

_NOTATION_PARAM_RE = re.compile(r"^[<\[{].*[>\]}]$")

_MD_ESCAPE_RE = re.compile(r"\\([_*~])")


def _clean_token(tok: str) -> str:
    """去掉单个 token 的 markdown 转义噪声。"""
    return _MD_ESCAPE_RE.sub(r"\1", tok)


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
    toks = cli_syntax.split()
    while toks and toks[0].lower() in _OP_PREFIXES:
        toks = toks[1:]
    out: list[str] = []
    for raw in toks:
        tok = _clean_token(raw).strip()
        if not tok:
            continue
        if _NOTATION_PARAM_RE.match(tok) or "|" in tok:
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
        name = str(item.get("name", "")).strip()
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
    if not isinstance(facts_raw, list):
        return []

    valid_kinds = {"cli_command", "decision_rule", "behavior", "known_issue"}
    results: list[RawFact] = []

    for item in facts_raw:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("fact_kind", "")).strip()
        if kind not in valid_kinds:
            continue

        
        cli_syntax = str(item.get("cli_syntax", "")).strip()
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
            path = [p.lower() for p in _coerce_str_list(item.get("feature_path")) if p]
        if not path:
            continue

        fact_key = str(item.get("fact_key", "")).strip()
        if not fact_key:
            continue

        results.append(RawFact(
            fact_kind=kind,  # type: ignore[arg-type]
            feature_path=path,
            fact_key=fact_key,
            cli_syntax=str(item.get("cli_syntax", "")).strip(),
            parameters=_coerce_parameters(item.get("parameters")),
            condition=str(item.get("condition", "")).strip(),
            decision=str(item.get("decision", "")).strip(),
            content=str(item.get("content", "")).strip(),
            issue_id=str(item.get("issue_id", "")).strip(),
            issue_title=str(item.get("issue_title", "")).strip(),
            affected_versions=_coerce_str_list(item.get("affected_versions")),
            evidence_file=str(item.get("evidence_file", "")).strip(),
            evidence_quote=str(item.get("evidence_quote", "")).strip()[:300],
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
    """从 working memory 文本中提取 RawFact 列表。

    Args:
        content: working memory 文件完整文本
        llm_chat: LLM 调用函数 (system_prompt, user_prompt) -> str|dict
        existing_facts: 现有 footprint 节点的 fact_key 清单（用于 LLM 复用）
    """
    if llm_chat is None:
        return []

    thread_id = _parse_thread_id(content)

    user_prompt = _format_existing_facts(existing_facts) + content

    try:
        result = llm_chat(_SYSTEM_PROMPT, user_prompt)
    except Exception as exc:
        logger.warning("footprint LLM 调用失败: %s", exc)
        return []

    return _parse_llm_response(result, thread_id)
