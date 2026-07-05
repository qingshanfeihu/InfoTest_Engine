"""组合子构造层(V4 步骤2,命题3.18 correct-by-construction)。

worker 的输出语言从「五列步骤表」升到「语义组合子」:它只做语义决策(测什么、
用什么命令观测、选哪种断言形态、期望什么),底层表示(寄存器分配、捕获比较三步式、
E/F/H 列语义、观测-断言排序)全部由本展开器保证——悬空断言、未定义寄存器引用、
带 H 步后直接断言这些必崩形态在组合子语言下**不可表达**。

文法来源(2026-07-04 实证,docs/PLAN_v4_engine.md 调研 E/J):34 个已验证成品卷反解
为 5 种组合子再展开,33/34 字节级等价;唯一失败卷恰是上机 fail 的坏形态卷。

组合子 schema(原生数组,每元素一个 dict,kind 必填):
- ``{"kind":"CONFIG", "cmds":[...], "desc":..., "host":"APV_0"}``
  设备配置。cmds 为命令列表(每条一个元素——多条命令的换行由展开器拼,双转义病
  在此表示下不存在);单条→cmd_config,多条→cmds_config。
- ``{"kind":"OBSERVE_ASSERT", "host":..., "cmd":..., "desc":...,
   "asserts":[{"op":"found"|"not_found"|"abs_found", "pattern":..., "desc":...}]}``
  观测一次(不带 H)+ 对该回显断言 1..n 条。
- ``{"kind":"CAPTURE_COMPARE", "host":..., "capture_cmd":..., "cmd":...,
   "relation":"same"|"differs", "desc":...}``
  捕获比较:第一次观测存寄存器,第二次观测产 result,断言两次相同(same→found)
  或不同(differs→not_found)。cmd 省略=与 capture_cmd 相同。寄存器名自动分配。
- ``{"kind":"OBSERVE_ONLY", "host":..., "cmd":..., "desc":...}``
  只观测不断言(轮转填充/发流量)。
- ``{"kind":"SLEEP", "seconds":N}``

host 语义:``APV_0``/``APV_1``=被测设备第一/二台(观测走 cmd_config;双机场景 CONFIG
也可带 host 指定下发目标,默认 APV_0);其余=测试机主机名(E=test_env,
F=主机名,须在网络事实源中)。
"""

from __future__ import annotations

from typing import Any

_ASSERT_OPS = ("found", "not_found", "abs_found")

# ref 前缀 → provenance source.kind(与 provenance_ir._VALID_SOURCE_KINDS 对齐)。
# worker 在组合子上标 ref(如 "footprint:sdns.pool.method"/"manual:cli_10.5_Chapter20:415"/
# "config_derived"),展开器据此**自动组装** provenance——worker 不再手拼 IR JSON
# (实证 2026-07-05:provenance 形态摩擦占 emit 打回的主体,打回率 48-52%)。
_REF_KINDS = ("footprint", "manual", "precedent", "env_facts", "intent",
              "config_derived", "skeleton", "device_runtime", "distribution_derived",
              "membership_derived", "captured_relation")


def _parse_ref(ref: Any) -> dict:
    """`"<kind>:<体>"` 或裸 kind → {kind, ref};无/不认识 → emit_auto(fail-open,不拒)。"""
    s = str(ref or "").strip()
    if not s:
        return {"kind": "emit_auto", "ref": ""}
    head, _, tail = s.partition(":")
    if head in _REF_KINDS:
        return {"kind": head, "ref": tail.strip()}
    return {"kind": "emit_auto", "ref": s}


def _err(i: int, kind: str, msg: str) -> str:
    return f"blocks[{i}]({kind}): {msg}"


_DUT_HOSTS = ("APV_0", "APV_1")   # 框架双设备槽(test_xlsx.py 原生支持;APV_1=拓扑第二台 …71)


def _observe_step(host: str, cmd: str, desc: str, save_as: str = "") -> dict:
    host = (host or "").strip()
    if host in _DUT_HOSTS:
        st = {"E": host, "F": "cmd_config", "G": cmd, "desc": desc}
    else:
        st = {"E": "test_env", "F": host, "G": cmd, "desc": desc}
    if save_as:
        st["H"] = save_as
    return st


def expand_blocks(blocks: list, provenance_steps: list | None = None
                  ) -> tuple[list[dict] | None, list[dict] | None, str | None]:
    """组合子 → 五列步骤表(+ 按 block 粒度的 provenance 同步展开)。

    Returns:
        (steps, expanded_provenance_steps, err)。err 非 None 时前两者为 None。
        provenance_steps 传入时须与 blocks 等长(一个组合子一条 layer/source),
        展开器把每条复制到该组合子的每个 step;**不传时自动组装**——layer 由
        kind 机械映射(命令步→G、断言步→V、SLEEP→E),source 从各 block 的
        ref/cmd_ref/asserts[].ref 前缀解析(见 _parse_ref)——worker 只标来源,
        不拼 IR 结构。两种情况返回值都与 steps 逐位对齐(backfill_efg 契约)。
    """
    if not isinstance(blocks, list) or not blocks:
        return None, None, "blocks 必须是非空数组"
    if provenance_steps is not None and len(provenance_steps) != len(blocks):
        return None, None, (f"provenance steps 数({len(provenance_steps)}) 必须等于 blocks 数"
                            f"({len(blocks)})——**按组合子粒度**标注,不是按展开后的步数:"
                            f"你有 {len(blocks)} 个组合子,provenance.steps 就写 {len(blocks)} 条"
                            f"(每条 {{layer, source}} 对应一个组合子,展开成几行由工具管)。")
    steps: list[dict] = []
    prov_out: list[dict] = []
    reg_n = 0
    for i, b in enumerate(blocks):
        if not isinstance(b, dict):
            return None, None, _err(i, "?", "每个组合子必须是对象")
        kind = str(b.get("kind", "")).strip().upper()
        desc = str(b.get("desc", "") or "")
        pv = provenance_steps[i] if provenance_steps is not None else None
        produced = 0
        block_auto: list[dict] = []   # 自动组装通道:本组合子展开各步的 {layer, source}
        if kind == "CONFIG":
            cmds = b.get("cmds")
            if not isinstance(cmds, list) or not cmds or not all(isinstance(c, str) for c in cmds):
                return None, None, _err(i, kind, "cmds 必须是非空命令字符串列表(每条命令一个元素)")
            # 碎片检测(在 strip/滤空之前):>2 个原始元素多数 ≤2 字符=命令被逐字符拆成了
            # 列表(worker 把 "sdns on" 传成 ["s","d","n","s"," ","o","n"])。展开后每个
            # "命令"是单字,strict 门报"命令 's' 不在 allowlist"——在源头拦更清楚。
            _short = [c for c in cmds if len(c.strip()) <= 2]
            if len(cmds) > 2 and len(_short) > len(cmds) // 2:
                return None, None, _err(i, kind,
                    f"cmds 看起来被逐字符拆开了({len(_short)}/{len(cmds)} 个元素≤2字符)"
                    "——每个数组元素应是**一整条命令**(如 \"sdns on\"),不是单个字符。"
                    "把整条命令作为一个字符串元素。")
            cmds = [c.strip() for c in cmds if c.strip()]
            if not cmds:
                return None, None, _err(i, kind, "cmds 全为空——填真实命令(每条一个元素)")
            # 双机:CONFIG 可带 host 指定第二台(默认 APV_0)。2026-07-05 yzg 双机递归
            # 实证:旧版写死 APV_0,组合子语言表达不了 APV_1 配置,worker 被迫退 steps 通道。
            _dut = str(b.get("host") or "APV_0").strip()
            if _dut not in _DUT_HOSTS:
                return None, None, _err(i, kind, f"CONFIG.host 只能是 {_DUT_HOSTS} 之一(被测设备),收到 {_dut!r}")
            if len(cmds) == 1:
                steps.append({"E": _dut, "F": "cmd_config", "G": cmds[0], "desc": desc})
            else:
                steps.append({"E": _dut, "F": "cmds_config", "G": "\n".join(cmds), "desc": desc})
            produced = 1
            block_auto.append({"layer": "G", "source": _parse_ref(b.get("ref"))})
        elif kind == "OBSERVE_ASSERT":
            cmd = str(b.get("cmd", "") or "").strip()
            host = str(b.get("host", "") or "").strip()
            asserts = b.get("asserts")
            if not cmd or not host:
                return None, None, _err(i, kind, "host 与 cmd 必填")
            if not isinstance(asserts, list) or not asserts:
                return None, None, _err(i, kind, "asserts 必须是非空断言列表;只观测不断言用 OBSERVE_ONLY")
            steps.append(_observe_step(host, cmd, desc))
            produced = 1
            block_auto.append({"layer": "G", "source": _parse_ref(b.get("cmd_ref") or b.get("ref"))})
            for j, a in enumerate(asserts):
                if not isinstance(a, dict):
                    return None, None, _err(i, kind, f"asserts[{j}] 必须是对象")
                op = str(a.get("op", "") or "").strip()
                pattern = a.get("pattern")
                if op not in _ASSERT_OPS:
                    return None, None, _err(i, kind, f"asserts[{j}].op 必须是 {_ASSERT_OPS} 之一,收到 {op!r}")
                if not isinstance(pattern, str) or not pattern.strip():
                    return None, None, _err(i, kind, f"asserts[{j}].pattern 必须是非空文本/正则")
                steps.append({"E": "check_point", "F": op, "G": pattern,
                              "desc": str(a.get("desc", "") or "")})
                produced += 1
                block_auto.append({"layer": "V", "source": _parse_ref(a.get("ref"))})
        elif kind == "CAPTURE_COMPARE":
            host = str(b.get("host", "") or "").strip()
            cap = str(b.get("capture_cmd", "") or "").strip()
            cmd = str(b.get("cmd", "") or "").strip() or cap
            relation = str(b.get("relation", "") or "").strip().lower()
            if not host or not cap:
                return None, None, _err(i, kind, "host 与 capture_cmd 必填")
            if relation not in ("same", "differs"):
                return None, None, _err(i, kind, f"relation 必须是 same(两次相同) 或 differs(两次不同),收到 {relation!r}")
            reg_n += 1
            reg = f"v{reg_n}"
            steps.append(_observe_step(host, cap, desc + "(第一次观测,捕获基线)", save_as=reg))
            steps.append(_observe_step(host, cmd, desc + "(第二次观测,产生被比较输出)"))
            op = "found" if relation == "same" else "not_found"
            steps.append({"E": "check_point", "F": op, "G": "", "H": reg,
                          "desc": desc + ("(两次相同)" if relation == "same" else "(两次不同)")})
            produced = 3
            _src = _parse_ref(b.get("ref"))
            block_auto.extend([{"layer": "G", "source": dict(_src)},
                               {"layer": "G", "source": dict(_src)},
                               {"layer": "V", "source": {"kind": "captured_relation", "ref": ""}}])
        elif kind == "OBSERVE_ONLY":
            cmd = str(b.get("cmd", "") or "").strip()
            host = str(b.get("host", "") or "").strip()
            if not cmd or not host:
                return None, None, _err(i, kind, "host 与 cmd 必填")
            steps.append(_observe_step(host, cmd, desc))
            produced = 1
            block_auto.append({"layer": "G", "source": _parse_ref(b.get("ref"))})
        elif kind == "SLEEP":
            try:
                sec = int(b.get("seconds"))
            except (TypeError, ValueError):
                return None, None, _err(i, kind, "seconds 必须是整数秒")
            if sec <= 0 or sec > 300:
                return None, None, _err(i, kind, f"seconds 须在 1..300,收到 {sec}")
            steps.append({"E": "time", "F": "sleep", "G": str(sec), "desc": desc})
            produced = 1
            block_auto.append({"layer": "E", "source": {"kind": "emit_auto", "ref": ""}})
        else:
            _keys = list(b.keys())
            return None, None, _err(i, kind or "缺kind",
                                    "每个组合子必须有 kind 字段,取 CONFIG/OBSERVE_ASSERT/"
                                    f"CAPTURE_COMPARE/OBSERVE_ONLY/SLEEP 之一。本组合子的键={_keys}"
                                    + ("——你可能漏了 kind,或用了别名。" if "kind" not in b
                                       else f",kind 值={b.get('kind')!r} 不在允许集。"))
        if provenance_steps is not None:
            base = pv if isinstance(pv, dict) else {}
            for _ in range(produced):
                prov_out.append(dict(base))
        else:
            # 自动组装:block_auto 与本组合子的 produced 逐位对齐(展开器自身保证;
            # 不齐=展开器 bug,用 emit_auto 补齐兜底而非崩)
            while len(block_auto) < produced:
                block_auto.append({"layer": "G", "source": {"kind": "emit_auto", "ref": ""}})
            prov_out.extend(block_auto[:produced])
    return steps, prov_out, None
