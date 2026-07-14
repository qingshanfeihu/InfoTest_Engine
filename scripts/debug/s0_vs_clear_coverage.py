# s₀ 判据 vs 框架 clear.py 覆盖 机械对照。
# 问:引擎历史上判 s₀ 时指认的"持久写"命令,框架 clear.py 到底清不清得掉?
# 清得掉 = 误判(该撤);清不掉 = 真 s₀ 候选(该留)。
import re, json, glob
from collections import Counter

CLEAR = open('knowledge/framework/mirror/lib/apv/clear.py').read()
# clear.py CMD_RULES 的 (前缀, 清理命令列表) —— 机械解析(源码闭集,非硬编码)
RULES = []
for m in re.finditer(r"cmd\.startswith\('([^']+)'\)(?:\s+or\s+cmd\.startswith\('([^']+)'\))?\s*,\s*\[([^\]]*)\]", CLEAR):
    prefixes = [p for p in (m.group(1), m.group(2)) if p]
    cleans = re.findall(r'"([^"]*)"', m.group(3))
    for p in prefixes:
        RULES.append((p, cleans))
# 已知漏洞标记
TGZ_BLIND = True  # clear conf file 的正则只认 .cfg,漏 .tgz(clear.py:178)

def framework_clears(cmd):
    """返回 (verdict, reason):cleanable / leftover_file / restore_noop / uncovered。"""
    cmd = cmd.strip().lower()
    hit = None
    for pre, cleans in RULES:  # 首匹配即 break(复刻 clear.py 语义)
        if cmd.startswith(pre.lower()):
            hit = (pre, cleans); break
    if hit is None:
        # config 恢复类(config memory/file/net/all/segment):读磁盘写运行,非污染源本身;
        # 恢复进运行区的对象靠该案其他命令的 clear 覆盖(本对照不追那层)
        if re.match(r'config\s+(memory|file|net|all|segment)\b', cmd):
            return "restore_noop", "恢复类(读):非持久残留源,恢复的运行对象靠同案 clear 覆盖"
        if re.match(r'write\s+net\b', cmd):
            return "uncovered", "write net:备份到远端服务器,本机不留(远端撞名属设计)"
        return "uncovered", "clear.py 98 前缀表未覆盖此命令"
    pre, cleans = hit
    # write file/all file → clear conf file → .cfg 正则盲区
    if "clear conf file" in cleans and TGZ_BLIND:
        return "leftover_file", f"{pre}→clear conf file,但正则 \\.cfg 漏 .tgz 备份包(clear.py:178)"
    if "write memory" in cleans:
        return "cleanable", f"{pre}→先clear运行再write memory覆盖磁盘(时序对,除非中途clear失败)"
    return "cleanable", f"{pre}→{cleans}"

# 引擎判 s₀ 时指认的持久写命令(全 run facts.jsonl 的 diagnosis.polluters[].cmds)
paths = glob.glob('runtime/backups/*/facts.jsonl') + \
        glob.glob('runtime/backups/*/*/facts.jsonl') + \
        ['workspace/outputs/yzg/facts.jsonl']
cmd_counter = Counter()
s0_diag = 0
for p in paths:
    try: lines = open(p).read().splitlines()
    except Exception: continue
    for ln in lines:
        try: e = json.loads(ln)
        except Exception: continue
        if e.get('ev') != 'diagnosis' or not str(e.get('h_position','')).startswith('h_s0'):
            continue
        s0_diag += 1
        for pol in (e.get('polluters') or []):
            for c in (pol.get('cmds') or []):
                # 规整:取命令前两三词(去参数值)
                cmd_counter[str(c).strip()] += 1

print(f"扫描 s₀ 诊断事实: {s0_diag} 条(跨所有 run)")
print(f"指认的持久写命令(去重 {len(cmd_counter)} 种,总计 {sum(cmd_counter.values())} 次):\n")
buckets = Counter()
for cmd, n in cmd_counter.most_common():
    v, reason = framework_clears(cmd)
    buckets[v] += n
    print(f"  [{v:14}] ×{n:3}  {cmd[:50]:50} — {reason}")
print("\n== 按框架能否清理归桶(按出现次数)==")
label = {"cleanable":"框架清得掉→引擎判 s₀ 是误判", "leftover_file":".tgz 残留(真,但需后案 config 恢复才污染)",
         "restore_noop":"恢复类(非污染源)", "uncovered":"表外(远端/未覆盖)"}
tot = sum(buckets.values())
for v, n in buckets.most_common():
    print(f"  {label.get(v,v):45} {n:4} 次 ({n/tot*100:.0f}%)")
