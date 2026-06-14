"""技能健康度看板（Phase 5 自动降级判定的纯函数核）。

A-B 闸是**晋升**时的一次性行为证据；健康度则是**晋升之后**的持续监控——
读每条技能的「首跑通过率趋势」，若连续 K 轮低于入库时的基线（admission baseline），
标记为 demote 候选（劣化退役）。对应 plan「自动降级」与循环 5 健康度看板。

设计纪律（守 4 红线）：
  1. **禁逐 case 硬编码**：本模块全程不看 autoid，也不对任何具体技能名分支。
     判定只读技能自身的 evidence / 趋势数据，换一批技能仍成立。
  2. **禁正则猜语义**：纯数值比较（通过率 vs 基线），无任何意图/语义推断。
  3. **确定性**：纯函数，无 time.time / 无随机 / 无磁盘 IO；同输入同输出，
     输出按技能名排序、浮点定点（round）以保证逐字节可复现。
  4. **证据接地**：入库基线只从技能的 `evidence.ab_test.with`（或显式
     `evidence.admission_baseline`）推导；给不出基线的技能不臆造，标 no_admission_baseline。

输入契约（duck-typed，兼容 dict 与 dataclass / 对象，故不强依赖 schema.py）：
  - registry：技能集合。支持三种形态：
      * Mapping[name -> spec]
      * 带 `.skills` 属性（Mapping）的对象（如 Registry 实例）
      * 可迭代的 spec 序列（每个 spec 自带 name 字段）
    spec 需可取 `evidence`（dict / 对象），其中：
      * `evidence.ab_test.with` = 入库首跑通过率（float / "N/M" / {passed,total}）
      * 或 `evidence.admission_baseline`（float）显式覆盖
      * `evidence.version`（int，可选，回报用）
      * spec/evidence 的 `state`/`status` == "off"（或 evidence.degraded 真）→ 已降级，跳过
  - history：Mapping[name -> list[round_record]]（或带 `.history` 属性的对象）。
    每个 round_record 是一轮的首跑通过率观测，支持：
      * float / int（直接是通过率，0..1）
      * "N/M" 字符串
      * dict：`pass_rate` / `rate`，或 (`passed`,`total`) / (`pass`,`total`) / (`with`,`total`)
    顺序即时间序（旧 → 新）；解析不了的记录被跳过。

输出（dict）：
  {
    "skills": { <name>: {version, admission_baseline, rounds, trend, latest,
                         mean, direction, consecutive_below, demote_candidate, reason}, ...},
    "demote_candidates": [<name>...],          # 排序去重
    "summary": {total_skills, with_history, demote_count, consecutive_k},
  }
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["health_report"]

_NDIGITS = 6  # 输出浮点定点位数（确定性逐字节复现）


# ── duck-typed 取值原语 ────────────────────────────────────────────────

def _get(obj: Any, key: str, default: Any = None) -> Any:
    """从 dict 或对象上取字段（兼容 dataclass / 普通对象）。"""
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _spec_name(spec: Any) -> str | None:
    """从 spec 上取技能名（dict['name'] / spec.name）。"""
    n = _get(spec, "name")
    return str(n) if n is not None else None


def _iter_skills(registry: Any) -> list[tuple[str, Any]]:
    """把 registry 归一成 [(name, spec)]，按 name 排序保证确定性。

    name 优先取 Mapping 的 key（registry 的规范 id），其次 spec 自带 name。
    """
    if registry is None:
        return []
    # 1) 带 .skills Mapping 的 registry 对象
    skills_attr = getattr(registry, "skills", None)
    if isinstance(skills_attr, Mapping):
        src: Mapping = skills_attr
    elif isinstance(registry, Mapping):
        src = registry
    else:
        # 2) 可迭代的 spec 序列
        try:
            specs = list(registry)
        except TypeError:
            return []
        out: list[tuple[str, Any]] = []
        for i, spec in enumerate(specs):
            out.append((_spec_name(spec) or f"skill_{i}", spec))
        out.sort(key=lambda kv: kv[0])
        return out
    # Mapping 形态：key 即技能名
    items = [(str(k), v) for k, v in src.items()]
    items.sort(key=lambda kv: kv[0])
    return items


def _history_for(history: Any, name: str) -> list[Any]:
    """取某技能的轮次记录列表。"""
    if history is None:
        return []
    hist_attr = getattr(history, "history", None)
    src = hist_attr if isinstance(hist_attr, Mapping) else history
    if isinstance(src, Mapping):
        recs = src.get(name, [])
    else:
        return []
    if recs is None:
        return []
    if isinstance(recs, (str, bytes, Mapping)):
        # 单条记录也包成列表（容错），但 Mapping 视为单轮
        return [recs]
    try:
        return list(recs)
    except TypeError:
        return [recs]


# ── 通过率解析（float / "N/M" / {passed,total}）────────────────────────

def _parse_rate(val: Any) -> float | None:
    """把多形态的「通过率」归一成 [0,1] 的 float；解析不了返回 None。"""
    if val is None:
        return None
    if isinstance(val, bool):  # bool 是 int 子类，先排除避免 True→1.0 误判
        return 1.0 if val else 0.0
    if isinstance(val, (int, float)):
        f = float(val)
        return f if 0.0 <= f <= 1.0 else None
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        if "/" in s:
            num, _, den = s.partition("/")
            return _ratio(num.strip(), den.strip())
        try:
            f = float(s)
        except ValueError:
            return None
        return f if 0.0 <= f <= 1.0 else None
    if isinstance(val, Mapping):
        # 直接给出比率
        for k in ("pass_rate", "rate", "first_try_pass_rate"):
            if k in val:
                return _parse_rate(val[k])
        # 分子/分母对
        for num_k, den_k in (("passed", "total"), ("pass", "total"),
                             ("with", "total"), ("hits", "total")):
            if num_k in val and den_k in val:
                return _ratio(val[num_k], val[den_k])
    return None


def _ratio(num: Any, den: Any) -> float | None:
    """num/den → [0,1] float；非法（den<=0 / 非数）返回 None。"""
    try:
        n = float(num)
        d = float(den)
    except (TypeError, ValueError):
        return None
    if d <= 0:
        return None
    r = n / d
    if r < 0:
        return None
    return min(r, 1.0)


# ── 入库基线 / 降级态 ──────────────────────────────────────────────────

def _admission_baseline(spec: Any) -> float | None:
    """从技能 evidence 推导入库时的首跑通过率基线。

    优先 evidence.admission_baseline（显式），其次 evidence.ab_test.with。
    给不出 → None（标 no_admission_baseline，不臆造）。
    """
    ev = _get(spec, "evidence")
    if ev is None:
        return None
    explicit = _parse_rate(_get(ev, "admission_baseline"))
    if explicit is not None:
        return explicit
    ab = _get(ev, "ab_test")
    if ab is None:
        return None
    return _parse_rate(_get(ab, "with"))


def _version(spec: Any) -> Any:
    ev = _get(spec, "evidence")
    v = _get(ev, "version")
    if v is None:
        v = _get(spec, "version")
    return v


def _is_off(spec: Any) -> bool:
    """技能是否已降级/退役（已 off 的不再列入 demote 候选）。"""
    for state in (_get(spec, "state"), _get(spec, "status")):
        if isinstance(state, str) and state.strip().lower() == "off":
            return True
    ev = _get(spec, "evidence")
    if ev is not None:
        st = _get(ev, "state")
        if isinstance(st, str) and st.strip().lower() == "off":
            return True
        if _get(ev, "degraded"):
            return True
    return False


# ── 趋势 / 降级判定 ────────────────────────────────────────────────────

def _trailing_below(rates: list[float], baseline: float, epsilon: float) -> int:
    """从尾部数连续低于基线（严格 < baseline-eps）的轮数。"""
    count = 0
    for r in reversed(rates):
        if r < baseline - epsilon:
            count += 1
        else:
            break
    return count


def _direction(rates: list[float], epsilon: float) -> str:
    """趋势方向：用首尾对比（确定性、无平滑随机）。"""
    if len(rates) < 2:
        return "unknown"
    delta = rates[-1] - rates[0]
    if delta > epsilon:
        return "improving"
    if delta < -epsilon:
        return "declining"
    return "flat"


def health_report(registry: Any, history: Any, *,
                  consecutive_k: int = 3, epsilon: float = 1e-9) -> dict:
    """算每技能首跑通过率趋势，标连续 K 轮低于入库基线者为 demote 候选。

    纯函数：不写任何文件、无随机、无 time。降级动作（写 .skill_overrides.json
    的 off 态）由调用方按本报告执行——本模块只产判定。

    consecutive_k：连续低于基线多少轮才算 demote 候选（默认 3，对齐 plan「连续 K 轮」）。
    epsilon：浮点比较容差，避免 0.999999 vs 1.0 的抖动误判。
    """
    k = max(1, int(consecutive_k))
    skills_out: dict[str, dict] = {}
    demote: list[str] = []
    with_history = 0

    for name, spec in _iter_skills(registry):
        raw = _history_for(history, name)
        rates = [r for r in (_parse_rate(rec) for rec in raw) if r is not None]
        rounds = len(rates)
        if rounds:
            with_history += 1

        baseline = _admission_baseline(spec)
        latest = rates[-1] if rates else None
        mean = sum(rates) / rounds if rounds else None
        direction = _direction(rates, epsilon)

        below = (_trailing_below(rates, baseline, epsilon)
                 if (baseline is not None and rates) else 0)

        # 判定降级候选 + 理由（确定性分支，全程不看技能名/autoid）
        off = _is_off(spec)
        if off:
            candidate, reason = False, "already_off"
        elif baseline is None:
            candidate, reason = False, "no_admission_baseline"
        elif rounds == 0:
            candidate, reason = False, "no_history"
        elif rounds < k:
            candidate, reason = False, "insufficient_history"
        elif below >= k:
            candidate, reason = True, f"below_baseline_for_{below}_rounds"
        else:
            candidate, reason = False, "within_baseline"

        if candidate:
            demote.append(name)

        skills_out[name] = {
            "version": _version(spec),
            "admission_baseline": (round(baseline, _NDIGITS)
                                   if baseline is not None else None),
            "rounds": rounds,
            "trend": [round(r, _NDIGITS) for r in rates],
            "latest": round(latest, _NDIGITS) if latest is not None else None,
            "mean": round(mean, _NDIGITS) if mean is not None else None,
            "direction": direction,
            "consecutive_below": below,
            "demote_candidate": candidate,
            "reason": reason,
        }

    demote_sorted = sorted(set(demote))
    return {
        "skills": skills_out,
        "demote_candidates": demote_sorted,
        "summary": {
            "total_skills": len(skills_out),
            "with_history": with_history,
            "demote_count": len(demote_sorted),
            "consecutive_k": k,
        },
    }
