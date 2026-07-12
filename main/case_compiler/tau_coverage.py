# -*- coding: utf-8 -*-
"""τ 覆盖判定器(G1 配对恢复门的判定核;理论锚=(39) 六元组/(32) 复位差集)。

判定「卷面对复位差集内分量的写,是否有配对的案内恢复步(τ)」。消费方:
① compile_emit 的配对恢复门(缺 τ → 呈报携机械派生的逆元建议,不硬拒——D5 形态);
② 引擎 G2 自污染者判定(面板出口路由)与 G3 污染者交付门。

**第一版范围(诚实分层)**:只判 **L2/L3 创建型写**(vlan/bond interface/ip address
新增——恰是 233/203 两案六次拆床的病灶族)。范围外如实不判:
- 删除型写(no ip address port2——恢复需原值,须运行时快照支持,G1 后续版);
- 持久面写(write file/memory/net——产物清理语义复杂,现有排尾+批末收敛缓解,
  L3 落地后根治);
- 流量写/管理面写((38) 声明的已知边界)。

逆元派生=(29) no 回放的机械形态:vlan X→no vlan <name>;bond interface B P→
no bond interface B;ip address IF IP MASK→no ip address IF(语法经设备 `?` 反射
与 run12 六次人工清偿实证)。形态数据后续入 domain_grammar(inverse_forms 键),
第一版随代码——三族全部有 run12 实证锚,非场景枚举((24):平台级机械闭集)。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 创建型 L2/L3 写(捕获组=实体参数区);与 bed_l23_write_forms 同族语义,
# 此处需捕获组做逆元派生故独立成表(数据合流=G1 后续版)
_CREATE_FORMS: list[tuple[re.Pattern, str]] = [
    # (识别正则, 逆元模板——{g1} 等指代捕获组)
    (re.compile(r"^vlan\s+(\S+)\s+(\S+)\s+(\d+)\s*$", re.IGNORECASE),
     "no vlan {g2}"),                                   # vlan <if> <name> <id> → no vlan <name>
    (re.compile(r"^bond\s+interface\s+(\S+)\s+(\S+)\s*$", re.IGNORECASE),
     "no bond interface {g1}"),                         # bond interface <bond> <member>
    (re.compile(r"^ip\s+address\s+(\S+)\s+(\S+)\s+(\S+)\s*$", re.IGNORECASE),
     "no ip address {g1}"),                             # ip address <if> <ip> <mask>
]


@dataclass
class TauReport:
    missing: list[dict] = field(default_factory=list)   # [{cmd, entity, suggested_inverse}]
    covered: list[dict] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)  # 差集内但第一版不判的写(persist/删除型)

    @property
    def ok(self) -> bool:
        return not self.missing


_PERSIST_RE = re.compile(r"^(?:write|config)\s+(?:all|file|memory|net|segment)\b",
                         re.IGNORECASE)
_DELETE_L23_RE = re.compile(r"^no\s+(?:vlan|ip\s+address|ip\s+route|interface|bond)\b",
                            re.IGNORECASE)


def _apv_config_lines(steps: list, init: str = "") -> list[str]:
    out: list[str] = []
    for line in (init or "").splitlines():
        if line.strip():
            out.append(line.strip())
    for s in steps or []:
        if not isinstance(s, dict):
            continue
        if str(s.get("E", "")).startswith("APV") and str(s.get("F", "")) in (
                "cmd_config", "cmds_config"):
            for line in str(s.get("G", "") or "").splitlines():
                if line.strip():
                    out.append(line.strip())
    return out


def check_tau_coverage(steps: list, init: str = "") -> TauReport:
    """卷面 τ 覆盖判定:每条创建型 L2/L3 写,其后(执行序)须有配对恢复。

    配对判据(机械):逆元命令的字面形态(模板实例化后)在**后续行**出现,
    或后续行以 `no <首关键字>` 开头且含同一实体 token(宽松侧:少误报呈报,
    漏检由 diagnose/上机兜底——方向同 D5)。"""
    lines = _apv_config_lines(steps, init)
    rep = TauReport()
    for i, line in enumerate(lines):
        if _PERSIST_RE.match(line):
            rep.out_of_scope.append(line)
            continue
        if _DELETE_L23_RE.match(line):
            # 删除型差集写:恢复需原值快照,第一版不判(如实分层)
            rep.out_of_scope.append(line)
            continue
        for pat, inv_tpl in _CREATE_FORMS:
            m = pat.match(line)
            if not m:
                continue
            groups = {f"g{k+1}": v for k, v in enumerate(m.groups())}
            inverse = inv_tpl.format(**groups)
            entity = groups.get("g2") or groups.get("g1") or ""
            # delete-then-restore 识别:**同命令族**的同宿主对象在前文被 no 删过
            # → 本写是恢复动作(把原状放回去),本身即 τ 的一部分,covered。
            # (233 真实卷面形态:no ip address port2 → …迁移… → ip address port2 恢复;
            #  同族限定防误认:no ip address port2 不背 vlan port2 新建的书)
            host = groups.get("g1") or ""
            family = inv_tpl.replace("no ", "").split("{")[0].strip()  # ip address/vlan/bond interface
            earlier = lines[:i]
            if host and any(l.lower().startswith(f"no {family}".lower()) and host in l
                            for l in earlier):
                rep.covered.append({"cmd": line, "entity": entity,
                                    "suggested_inverse": "(restore write, itself part of τ)"})
                break
            later = lines[i + 1:]
            covered = any(
                l.lower().startswith(inverse.lower())
                or (l.lower().startswith("no ") and entity and entity in l)
                for l in later)
            item = {"cmd": line, "entity": entity, "suggested_inverse": inverse}
            (rep.covered if covered else rep.missing).append(item)
            break
    return rep
