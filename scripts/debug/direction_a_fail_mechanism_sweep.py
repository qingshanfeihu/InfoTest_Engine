# 方向A 决策清点 v2:多源 echo 真值(last_run + verdict signatures + 报告md引用 +
# attribution/diagnosis 散文),分类信号扩到 G层/交互/占用/marker。
# 输出:每 run 终态 fail 的机理分布 + 跨 run 复发 + s₀ 误判交叉 + 轮次成本。
import json, re
from pathlib import Path
from collections import Counter, defaultdict

MARKERS = ['Failed to execute the command', 'Failed to get the file from',
           'RTNETLINK answers: File exists', 'RTNETLINK answers: Cannot assign']
SIG_INTERACT = re.compile(r'Type\s+"?YES"?|to overwrite|Write aborted', re.I)
SIG_OCCUPY = re.compile(r'occupied|already exists|already configured|is in use', re.I)
SIG_SYNTAX_PROSE = re.compile(r'\bG\(\^\)|syntax reject|\^ marker|Invalid input|Unrecognized', re.I)

RUNS = [
    ('run2_abort', 'runtime/backups/yzg_v8_run2_aborted_20260710/yzg'),
    ('v8_accept', 'runtime/backups/yzg_v8_acceptance_20260710/yzg'),
    ('run5_final', 'runtime/backups/yzg_v8_run5_final_20260711/yzg'),
    ('run7_ask', 'runtime/backups/yzg_v8_run7_askaccept_20260711/yzg'),
    ('run8_seq1', 'runtime/backups/yzg_v8_run8_seq1_20260711/yzg'),
    ('run9_x10', 'runtime/backups/yzg_v8_run9_x10_20260711/yzg'),
    ('run10_bedl', 'runtime/backups/yzg_v8_run10_bedledger_20260712/yzg'),
    ('run11_closed', 'runtime/backups/yzg_v8_run11_closed_20260712'),
    ('run12_accept', 'runtime/backups/yzg_v8.5_run12_acceptance_20260712'),
    ('run13_accept', 'runtime/backups/yzg_v8.5_run13_acceptance_20260712'),
    ('run14_devloss', 'runtime/backups/yzg_v8.5_run14_device_loss_20260713'),
    ('run19_cur', 'workspace/outputs/yzg'),
]

def md_sections(root):
    """unsuccessful_cases.md / delivery_report.md 按 autoid 切段(引用了设备回显)。"""
    out = defaultdict(str)
    for mdn in ('unsuccessful_cases.md', 'delivery_report.md'):
        p = root / mdn
        if not p.is_file():
            continue
        txt = p.read_text(errors='ignore')
        ids = re.findall(r'20360\d{13}', txt)
        # 粗切:每个 autoid 出现位置到下一个 autoid 出现位置
        pos = sorted({(m.start(), m.group()) for m in re.finditer(r'20360\d{13}', txt)})
        for i, (st, aid) in enumerate(pos):
            en = pos[i + 1][0] if i + 1 < len(pos) else min(len(txt), st + 4000)
            out[aid] += txt[st:en]
    return out

def classify(echo, layer_hint=''):
    mech = set()
    if layer_hint == 'G' or SIG_SYNTAX_PROSE.search(echo): mech.add('syntax_G')
    if any(m in echo for m in MARKERS): mech.add('marker')
    if SIG_INTERACT.search(echo): mech.add('interactive')
    if SIG_OCCUPY.search(echo): mech.add('occupancy')
    return mech

rows = []
recur = defaultdict(list)
for name, root in RUNS:
    root = Path(root)
    facts_p = root / 'facts.jsonl'
    if not facts_p.is_file():
        continue
    verdicts, atts, diags, authored = [], defaultdict(list), defaultdict(list), Counter()
    for ln in facts_p.read_text().splitlines():
        try: e = json.loads(ln)
        except Exception: continue
        ev = e.get('ev'); aid = str(e.get('aid') or '')
        if ev == 'verdict': verdicts.append(e)
        elif ev == 'attribution': atts[aid].append(e)
        elif ev == 'diagnosis': diags[aid].append(e)
        elif ev == 'authored': authored[aid] += 1
    # 终态 verdict per aid(最后一条)
    fin = {}
    for v in verdicts:
        fin[str(v.get('aid'))] = v
    lr = {}
    lrp = root / 'last_run.json'
    if lrp.is_file():
        for r in json.loads(lrp.read_text()):
            if isinstance(r, dict): lr[str(r.get('autoid'))] = r
    mds = md_sections(root)
    for aid, v in fin.items():
        if v.get('result') != 'fail':
            continue
        r = lr.get(aid, {})
        echo = '\n'.join([
            str(r.get('device_context') or ''), str(r.get('detail_tail') or ''),
            str(r.get('causality') or ''), str(r.get('_fail_signatures') or ''),
            '\n'.join(str(s) for s in (v.get('signatures') or [])),
            mds.get(aid, ''),
            '\n'.join(str(a.get('fix_direction') or '') for a in atts[aid]),
            '\n'.join(str(a.get('evidence') or '') + str(a.get('basis') or '') for a in diags[aid]),
        ])
        layer_hint = str(r.get('_digest_layer') or '')
        if not layer_hint:
            gl = [a for a in atts[aid] if str(a.get('layer')) == 'G']
            layer_hint = 'G' if gl else ''
        mech = classify(echo, layer_hint)
        h_pos = next((str(d.get('h_position')) for d in reversed(diags[aid])
                      if d.get('h_position')), '')
        att_layer = next((str(a.get('layer')) for a in reversed(atts[aid])), '')
        rows.append((name, aid, authored[aid], '+'.join(sorted(mech)) or 'semantic',
                     att_layer, h_pos))
        recur[aid[-6:]].append((name, '+'.join(sorted(mech)) or 'semantic'))

print(f"{'run':<13}{'aid尾6':<8}{'写轮':>4}  {'机理':<30}{'归因层':<8}{'h_pos':<8}")
for name, aid, rnds, mech, layer, h in rows:
    print(f"{name:<13}{aid[-6:]:<8}{rnds:>4}  {mech:<30}{layer:<8}{h:<8}")

c = Counter(m for _, _, _, m, _, _ in rows)
print('\n== 终态 fail 机理合计 ==')
for m, n in c.most_common(): print(f"  {m}: {n}")

print('\n== 跨 run 复发(同案≥2 run 终态 fail)==')
for tail, lst in sorted(recur.items()):
    if len(lst) >= 2:
        print(f"  {tail}: " + ' | '.join(f"{n}:{m}" for n, m in lst))

# 有执行型机理但被判 s₀ 的(污点一误判类)
mis = [(n, a[-6:], m, h) for n, a, _, m, _, h in [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows]
       if m != 'semantic' and h == 'h_s0']
print(f'\n== 执行型机理 ∧ 判 s₀(误判候选)x{len(mis)} ==')
for n, t, m, h in mis: print(f"  {n} {t} {m}")
