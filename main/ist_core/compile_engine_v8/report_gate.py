"""G5 报告重算门(DESIGN §17;理论锚=(42) 报告保真:Report=render(fold(facts)) 零自由度)。

独立代码路径从原始事实流重算「计数与终态陈述」,与 engine_report/delivery_report
逐项比对——**故意不复用** views.py/facts.py 的派生函数(同一套代码算两遍验不出
fold 自身的错;两条路径漂移=告警=去查,冗余是本门的设计而非疏忽)。封堵的前科:
run11 名义 26/26——报告说全过而事实台账不支持,用户信了错报告。

失配动作在 closing:告警文件+outcome 翻转+报告顶部警示条;门只产出失配清单。
issues 是用户面中文(会进报告正文),机读细节走 REPORT_MISMATCH.json。
"""

from __future__ import annotations

import re


def recount_deliverable(fs: list[dict], manifest: dict) -> dict:
    """独立重算:哪些案的「交付」陈述有事实支撑(raw dict 扫描,零派生函数)。

    对齐 fold 的优先级语义(views.case_status),但独立实现:
    escalated/未解除挂起/用户终局裁决/未答呈报 都压过交付;交付支撑=最新
    delivery 裁决 pass ∧ 卷面/卷组成双指纹匹配 ∧ 其后无 delivery_blocked。
    """
    aids = [str(c.get("autoid")) for c in (manifest.get("cases") or [])]
    # 卷指纹隔离(回归#2 修):deliverable 绑最近 **delivery** 卷,与 views.batch_view
    # 同规则(独立重算两条路径必须同口径,否则 G5 报告门自我误告警);只排除 subset 复跑卷
    merges = [f for f in fs if f.get("ev") == "merged" and f.get("ctx") != "subset"]
    vol = str(merges[-1].get("volume")) if merges else ""
    supported: set[str] = set()
    for aid in aids:
        mine = [f for f in fs if str(f.get("aid")) == aid]
        if any(f.get("ev") == "escalated" for f in mine):
            continue
        last_susp = max((i for i, f in enumerate(mine) if f.get("ev") == "suspended"),
                        default=-1)
        last_resume = max((i for i, f in enumerate(mine) if f.get("ev") == "resumed"),
                          default=-1)
        if last_susp >= 0 and last_resume < last_susp:
            continue
        if any(f.get("ev") == "attribution" and int(f.get("round") or 0) == 99
               and f.get("disposition") in ("env_blocked", "defect_candidate")
               for f in mine):
            continue
        if any(f.get("ev") == "needs_decision" for f in mine) and not any(
                f.get("ev") == "decision" for f in mine):
            continue
        authored = [f for f in mine if f.get("ev") == "authored"]
        art = str(authored[-1].get("artifact")) if authored else ""
        dv = [(i, f) for i, f in enumerate(mine)
              if f.get("ev") == "verdict" and f.get("ctx") == "delivery"]
        if not dv:
            continue
        i, v = dv[-1]
        if v.get("result") != "pass":
            continue
        if str(v.get("artifact")) != art or str(v.get("volume")) != vol:
            continue
        if any(f.get("ev") == "delivery_blocked" for f in mine[i + 1:]):
            continue
        supported.add(aid)
    return {"aids": aids, "deliverable": supported, "volume": vol}


_HEADLINE = re.compile(r"本批 (\d+) 个用例:\*\*(\d+) 个通过整卷复验")


def check_report(report: dict, md_text: str, fs: list[dict],
                 manifest: dict) -> tuple[list[str], dict]:
    """逐项比对,返回 (用户面失配清单, 机读细节)。空清单=报告可信。"""
    issues: list[str] = []
    detail: dict = {}
    rc = recount_deliverable(fs, manifest)
    cases = report.get("cases") or {}
    totals = report.get("totals") or {}
    claimed = {a for a, c in cases.items() if str(c.get("status")) == "deliverable"}

    # ① 终态陈述:报告称「通过整卷复验」的每个案,事实台账必须支撑;反向漂移同报
    unsupported = sorted(claimed - rc["deliverable"])
    unreported = sorted(rc["deliverable"] - claimed)
    if unsupported:
        tails = "、".join("…" + a[-6:] for a in unsupported[:5])
        issues.append(f"报告称 {len(unsupported)} 个用例(尾号 {tails})通过整卷复验,"
                      f"但事实台账不支撑该结论")
        detail["unsupported_claims"] = unsupported
    if unreported:
        tails = "、".join("…" + a[-6:] for a in unreported[:5])
        issues.append(f"{len(unreported)} 个用例(尾号 {tails})事实台账支持通过,"
                      f"报告却未计入——两条重算路径漂移,需人工核对")
        detail["unreported_passes"] = unreported

    # ② 计数一致:totals 与逐案状态互算必须相等(全集数/通过数/分状态计数)
    n_cases = len(rc["aids"])
    if int(totals.get("cases") or 0) != n_cases or len(cases) != n_cases:
        issues.append(f"报告的用例总数与任务清单不一致(清单 {n_cases} 个)")
        detail["cases_total"] = {"manifest": n_cases, "totals": totals.get("cases"),
                                 "report_cases": len(cases)}
    if int(totals.get("deliverable") or 0) != len(claimed):
        issues.append(f"报告汇总的通过数({totals.get('deliverable')})与逐案状态"
                      f"({len(claimed)})对不上")
        detail["deliverable_count"] = {"totals": totals.get("deliverable"),
                                       "per_case": len(claimed)}
    from collections import Counter
    per_status = Counter(str(c.get("status")) for c in cases.values())
    bad_keys = {k: (totals.get(k), n) for k, n in per_status.items()
                if int(totals.get(k) or 0) != n}
    if bad_keys:
        issues.append("报告汇总的分状态计数与逐案状态对不上")
        detail["status_counts"] = {k: {"totals": v[0], "per_case": v[1]}
                                   for k, v in bad_keys.items()}

    # ③ 人话报告头行:渲染出的数字必须等于重算值(render 篡改/漂移的最后防线)
    m = _HEADLINE.search(md_text or "")
    if not m:
        issues.append("交付报告缺少可核对的汇总头行")
        detail["headline"] = "missing"
    else:
        h_total, h_ok = int(m.group(1)), int(m.group(2))
        if h_total != n_cases or h_ok != len(rc["deliverable"]):
            issues.append(f"交付报告头行写「{h_total} 个用例/{h_ok} 个通过」,"
                          f"事实重算为 {n_cases} 个用例/{len(rc['deliverable'])} 个通过")
            detail["headline"] = {"rendered": [h_total, h_ok],
                                  "recomputed": [n_cases, len(rc["deliverable"])]}
    return issues, detail


def mismatch_banner(issues: list[str]) -> str:
    """失配警示条(插进 delivery_report.md 顶部;机械门的话,不属渲染叙事)。"""
    lines = ["> ⚠ **报告校验未通过**——以下陈述与过程事实台账不一致,本报告暂不可作为"
             "交付依据(以 `facts.jsonl` 与 `REPORT_MISMATCH.json` 为准):"]
    lines += [f"> - {i}" for i in issues]
    return "\n".join(lines) + "\n\n"
