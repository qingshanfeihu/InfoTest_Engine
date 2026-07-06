"""命中归属锚点断言辅助（pool/成员归属的确定性锚定判定）。

为什么要它：负载均衡/域名解析类用例里，"这次命中了哪个 pool"本身不是纯运行时不可知——
每个 pool 配了哪些成员 IP 是静态已知的（`sdns pool service` 写死了），"输出 ∈ 某 pool 的
成员集合"就能确定判出命中了哪个 pool，不需要靠"两次输出同/异"去猜。

这条映射一旦缺失，断言会在两类场景失真：
- 分布类（rr/wrr）：pool 内多成员时，"输出不同"可能只是同一 pool 内部轮到了另一个成员，
  不代表命中了不同 pool。
- 顺序类（new_member_last）：新增 pool 后"冒出一个新 IP"不代表命中了新 pool——它可能只是
  原 pool 里此前没轮到过的成员；只用 H 捕获比"两次输出同/异"，也分辨不出命中的到底是不是
  那个新 pool。

案例 778012 实测过这条链路缺失的后果：worker 全程只用"两次输出同/异"猜命中关系，从未用过
"输出落在哪个 pool 的成员集合里"这条本可离线确定的判据，导致断言在 pool 内多成员的场景下
证不出目标行为（详见 compile-worker.md / EXCEL_FUNCTIONS.md「命中归属」节）。

框架 check_point 的 found/not_found 本就接受任意正则（G 列），"输出 ∈ 成员集合"能直接落成
`found(成员1|成员2|...)`；但手写成员集合的 alternation 正则脆弱（IPv4 点位转义、词边界防止
`1.1.1.1` 误配 `1.1.1.10`、IPv6 写法多样），故本模块**确定性生成**这条正则，agent 只声明
{成员 IP 集合, 这次该不该命中}。

红线：本模块只做「IP 集合→正则」这类与意图无关的确定性变换；**不判断该查哪个 pool、不决定
该在哪几步之间插入声明、不写死"覆盖原 pool 一轮需要几次"**——pool 归哪些成员、该在哪个位置
声明命中/不命中，全部由查过配置/footprint/先例的 agent 提供（设备命中规律因算法/设备而异）。
"""

from __future__ import annotations

import re


# 粗校验用（挡"填了 pool 名/变量名"这类明显误用），不追求完整 RFC 校验。
_IPV4_STRICT_RE = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)$")
# 字符集限定于十六进制 + 冒号，且至少含一个冒号（IPv4 走上面那条，这里只兜 IPv6 形态）。
_IPV6_LOOSE_RE = re.compile(r"^[0-9a-fA-F:]*:[0-9a-fA-F:]*$")


def _looks_like_ip(s: str) -> bool:
    """粗校验：是否像一个 IP 地址字面量（挡明显误用，非完整 RFC 校验）。"""
    s = s.strip()
    if not s:
        return False
    if _IPV4_STRICT_RE.match(s):
        return True
    return bool(_IPV6_LOOSE_RE.match(s))


def _escape_ip_for_regex(ip: str) -> str:
    """IP 字面量 → 正则可用形式：IPv4 转义点号（`.`→`\\.`，`.` 是正则元字符）；
    IPv6 的冒号不是正则元字符，不需转义。"""
    return ip.strip().replace(".", r"\.")


def member_regex_for_ips(ips: list[str]) -> str:
    """成员 IP 集合 → 带词边界、可直接拼进 G 列的 alternation 正则。

    例：["172.16.35.226","172.16.35.232"] → `\\b(?:172\\.16\\.35\\.226|172\\.16\\.35\\.232)\\b`。
    `\\b` 边界防止 `226` 误配 `2264` 这类前缀重叠——IPv4/IPv6 地址字符均为 `\\w`（数字/十六进制
    字母），两侧的点/冒号/空白都是非 `\\w`，`\\b` 天然卡在地址整体的首尾，与本项目既有 IP 词
    边界惯例一致（`\\b…\\b`，见 quality_contract._IPV4_LITERAL / compile-worker.md）。
    """
    escaped = [_escape_ip_for_regex(ip) for ip in ips]
    return r"\b(?:" + "|".join(escaped) + r")\b"


def validate_membership(ips, present) -> str | None:
    """校验一个命中归属声明。返回 None=通过，否则返回**可读打回原因**（emit 据此拒绝）。

    结构性、与意图无关的确定性约束：
    - ips 非空列表，每项都得像一个 IP 字面量。
    - present 必须是 bool（这次该不该命中，由 agent 判断，不是本模块猜）。
    """
    if not isinstance(ips, list) or not ips:
        return f"命中归属断言 ips（成员 IP 集合）须为非空列表，实际 {ips!r}"
    for i, ip in enumerate(ips):
        if not isinstance(ip, str) or not _looks_like_ip(ip):
            return (f"ips[{i}]={ip!r} 不像一个 IP 地址字面量"
                    "（应是该 pool 配置里的成员 IP，不是 pool 名/变量名）")
    if not isinstance(present, bool):
        return f"命中归属断言 present（这次该不该命中该成员集合）须为 bool，实际 {present!r}"
    return None


def expand_membership_step(step: dict) -> tuple[dict | None, str | None]:
    """把一个命中归属声明步 → 1 条锚定成员集合正则的 found/not_found check_point（1:1，非 1:N）。

    声明形态（F="member"，member 见下）::

        {"E":"check_point","F":"member","member":{
            "ips":["<member_ip1>","<member_ip2>", ...], "present": true|false}}

    - `present=true`  → 展开 `found`（这次观测的输出该落在这个成员集合里）。
    - `present=false` → 展开 `not_found`（这次观测的输出不该落在这个成员集合里）。
    返回 (step, None) 或 (None, 打回原因)。
    """
    member = step.get("member") or {}
    ips = member.get("ips")
    present = member.get("present")
    err = validate_membership(ips, present)
    if err:
        return None, err

    g = member_regex_for_ips([str(ip) for ip in ips])
    mode = "found" if present else "not_found"
    desc = str(member.get("desc") or
               (f"输出命中成员集合{ips}（命中归属锚点）" if present
                else f"输出不落在成员集合{ips}（命中归属锚点）"))
    return {"E": "check_point", "F": mode, "G": g, "desc": desc}, None


def _is_member_step(step) -> bool:
    return (isinstance(step, dict) and str(step.get("F", "")).strip() == "member"
            and bool(step.get("member")))


def expand_membership_steps(steps: list) -> tuple[list | None, str | None]:
    """展开 steps 里所有 member 声明。返回 (new_steps, error)。

    member 是 1 步 → 1 条 check_point（1:1），与原 steps 逐位天然对齐——不像 dist（1:N）
    需要额外 plan 同步 provenance；provenance 按位置对应即可，emit 接线不用管展开量。
    """
    new_steps: list = []
    for s in steps:
        if _is_member_step(s):
            expanded, err = expand_membership_step(s)
            if err:
                return None, err
            new_steps.append(expanded)
        else:
            new_steps.append(s)
    return new_steps, None
