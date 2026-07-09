"""观测算子代数（论文 §3.2）的客观判据 —— **单一事实源**。

`confidence_f`（compile_score 判分证据）与 `grade_extract`（缺陷① 确定性探针）原本各写一遍
observe_kind / object_tokens / 配置存在性检查；两套实现的分词/算子词表一旦漂移，会给同一个
grade 矛盾信号。本模块把这三个客观判据收敛成单一实现，两边共用。逻辑取自 `grade_extract`
（缺陷①专用脚本，更完整为权威：剥前导算子词、statistic/count 也算行为观测）。

分类逻辑（算子代数）在此闭合于论文 §3.2；**动词词面**是文法层数据——从
`knowledge/data/compile_ref/domain_grammar.json` 加载（出处标注在数据里），
产品 CLI 语言演进时改 JSON 不改本模块（三层架构，2026-07-08 P2）。
"""
from __future__ import annotations

import re

from main.case_compiler import domain_grammar as _dg

# 瞬时态动词（操作运行时状态/连接表，不改静态配置）。public：grade_extract 也复用，免双份漂移。
MUTATING_VERBS = _dg.verbs("mutating")
# 命令开头的算子词（动词）；剥掉它们后剩下的才是命令「对象」。
_LEADING_OPS = MUTATING_VERBS + _dg.verbs("observe_leading")
# 观测算子性质词（behavior/config_query 判定用，词面见文法数据 provenance）。
_BEHAVIOR_PROBES_RE = re.compile(r"\b(" + "|".join(_dg.verbs("behavior_probes")) + r")\b")
_CONFIG_QUERY_RE = re.compile(r"\b(" + "|".join(_dg.verbs("config_query_probes")) + r")\b")
_RUNTIME_STATE_RE = re.compile(r"\b(" + "|".join(_dg.verbs("runtime_state_words")) + r")\b")


def object_tokens(text: str) -> list[str]:
    """取命令/期望值的「对象」token：剥开头连续算子词(clear/no/show/dig…) + 丢参数值
    (IP/数字/引号串/含点域名/掩码…)，剩下纯字母命令主体 token（如 sdns/host/persistence）。

    客观分词，无领域词表。用于判「expect 是否只是某条前序配置命令的回显」(= 配置存在性检查)。
    """
    toks = (text or "").strip().split()
    objs: list[str] = []
    leading = True
    for t in toks:
        tl = t.strip().strip('"\'').lower()
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", tl):   # 丢 IP/数字/引号串/含点域名/掩码等参数值
            leading = False
            continue
        if leading and tl in _LEADING_OPS:              # 开头连续算子词（动词），跳过
            continue
        leading = False
        objs.append(tl)
    return objs


def observe_kind(cmd: str) -> str:
    """观测算子的性质（论文 §3.2 算子代数）：
      'behavior'     —— dig/客户端请求/show statistics/session/counter：看运行时行为/解析/计数（V 性质）
      'config_query' —— 纯 show/display 配置：看配置在不在（G 性质，配置存在性查询）
      ''             —— 非观测步
    """
    c = (cmd or "").lower()
    if not c.strip():
        return ""
    if _BEHAVIOR_PROBES_RE.search(c):
        return "behavior"          # 客户端请求/解析 = 业务行为观测
    if _CONFIG_QUERY_RE.search(c):
        # 观测面词表刻意不含 list/get（误匹配 access-list/get-config，见文法数据 provenance）。
        # show + 运行时状态/统计词 = 行为观测（V 性质）
        if _RUNTIME_STATE_RE.search(c):
            return "behavior"
        return "config_query"      # 纯 show 配置 = 配置存在性查询（G 性质）
    return ""


def is_observe_command(cmd: str) -> bool:
    """这条命令是否「产出可校验回显」的观测步（dig/curl/nslookup/ping/show/display/get/list）。

    = observe_kind 非空。用于定位 check_point 校验的前序观测步（link_assertion_to_config /
    grade_extract 原各用一条正则，且 confidence_f 那条漏了 display/get/list——收口到此免漂移）。
    """
    return bool(observe_kind(cmd))


def config_existence_check(observe_cmd: str, expect: str,
                           config_context: list[str], method: str = "found") -> tuple[bool, str]:
    """配置存在性检查（G 性质恒真）判定。返回 (是否恒真配置存在性检查, 命中的前序配置命令)。

    先客观探测「expect 是否只是某前序配置命令的回显」（观测是 show + expect token ⊆ 某前序配置）；
    命中后按 **method（F 列算子，框架结构化事实）** 定性——只看 token 子集会把下面两类混判：
      - `found(配置)`  ＝验配置**在**  ＝恒真存在性检查（配了就在、被测命令成败都恒成立）→ (True, cfg)。
      - `not_found/abs_found(配置)` ＝验配置**不在/被移除** ＝**状态变更验证**（覆盖/删除后该配置应
        消失；配置若还在则 fail、**非恒真**）→ (False, cfg)：不算恒真伪覆盖，但 cfg 非空让调用方知
        「该配置确曾配过」、据此判为真 V 覆盖（治应急池覆盖 `not_found p1`、删除配置类「只能 show 观测」）。
    """
    qset = set(object_tokens(expect))
    if not qset or observe_kind(observe_cmd) != "config_query":
        return False, ""
    matched = ""
    for c in config_context:
        if qset <= set(object_tokens(c)):
            matched = c
            break
    if not matched:
        return False, ""
    if (method or "found").strip().lower() != "found":   # not_found/abs_found = 验移除 = 非恒真存在性
        return False, matched   # cfg 非空让调用方知「配过」→ 判状态变更真 V；is_check=False（非恒真）
    return True, matched
