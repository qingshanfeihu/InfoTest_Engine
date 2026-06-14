"""R2 验证（一次性）：统计跳板机各模块 .py 用例的 fixture(obj) 命名分布。

命门问题：corpus._parse_py_case 的 eobj map 只认 {APV0,APV1,check_point,test_env,time}，
其余 obj 的调用行被静默 continue 丢弃。本脚本量化"会被丢多少、漏哪些 fixture"。

只读：远端只跑 find + python3 文本扫描，不改任何文件。
"""
import os
import sys

sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("IST_JUMPHOST_PASS", os.environ.get("JUMPHOST_PASS", ""))

from main.case_compiler.device_mcp_client import _connect

# 远端只读统计脚本：扫 smoke_test 下数字命名 .py，按模块 tally obj.method( 的 obj 名。
REMOTE = r'''
import os, re, json, collections
ROOT = "/home/test/apv_src/smoke_test"
KNOWN = {"APV0","APV1","check_point","test_env","time"}
call_re = re.compile(r"^\s*(\w+)\.(\w+)\(")
num_re = re.compile(r"^\d{7,}$")
per_module = {}            # module -> {files, num_files, parsed_files(有>=1 known行), obj_counts, unknown_obj_files}
global_obj = collections.Counter()
global_unknown = collections.Counter()
for module in sorted(os.listdir(ROOT)):
    mdir = os.path.join(ROOT, module)
    if not os.path.isdir(mdir):
        continue
    files = 0; num_files = 0; parsed = 0
    objc = collections.Counter()
    unknown_files = collections.Counter()   # unknown obj -> 文件数
    for dp, dn, fn in os.walk(mdir):
        for f in fn:
            if not f.endswith(".py"):
                continue
            files += 1
            stem = f[:-3]
            if not num_re.match(stem):
                continue
            num_files += 1
            try:
                src = open(os.path.join(dp, f), encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            objs_in_file = set()
            has_known = False
            for line in src.splitlines():
                m = call_re.match(line)
                if not m:
                    continue
                obj = m.group(1)
                objc[obj] += 1
                global_obj[obj] += 1
                objs_in_file.add(obj)
                if obj in KNOWN:
                    has_known = True
            if has_known:
                parsed += 1
            for o in objs_in_file:
                if o not in KNOWN:
                    unknown_files[o] += 1
                    global_unknown[o] += 1
    if files == 0:
        continue
    per_module[module] = {
        "py_files": files,
        "numeric_named": num_files,
        "parseable(has_known_obj)": parsed,
        "top_objs": objc.most_common(12),
        "unknown_objs_byfiles": unknown_files.most_common(15),
    }
out = {
    "per_module": per_module,
    "global_obj_top": global_obj.most_common(30),
    "global_unknown_top": global_unknown.most_common(30),
    "KNOWN": sorted(KNOWN),
}
print(json.dumps(out, ensure_ascii=False))
'''

def main():
    c = _connect()
    try:
        # 优先用框架自带 .python3.8，回退系统 python3
        cmd = ("cd /home/test/apv_src && "
               "(.python3.8/bin/python - <<'PYEOF'\n" + REMOTE + "\nPYEOF\n) "
               "2>/dev/null || (python3 - <<'PYEOF'\n" + REMOTE + "\nPYEOF\n)")
        stdin, stdout, stderr = c.exec_command(cmd, timeout=180)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
    finally:
        c.close()
    # 取最后一行 JSON（前面可能有 warning）
    line = ""
    for ln in out.splitlines():
        if ln.strip().startswith("{"):
            line = ln.strip()
    if not line:
        print("NO JSON. stdout head:", out[:2000], "\nstderr:", err[:1000])
        return
    import json
    data = json.loads(line)
    print("=" * 70)
    print("R2 fixture 分布 — 各模块 .py 用例可解析率")
    print("=" * 70)
    print("KNOWN(写死可识别):", data["KNOWN"])
    print()
    print(f"{'module':<16}{'py文件':>8}{'数字命名':>10}{'可解析':>8}{'可解析率':>10}")
    print("-" * 60)
    for mod, s in sorted(data["per_module"].items(), key=lambda kv: -kv[1]["numeric_named"]):
        nn = s["numeric_named"]; pr = s["parseable(has_known_obj)"]
        rate = f"{(pr/nn*100):.0f}%" if nn else "—"
        print(f"{mod:<16}{s['py_files']:>8}{nn:>10}{pr:>8}{rate:>10}")
    print()
    print("全局 obj(fixture) 调用 Top30（含已知+未知）:")
    for obj, cnt in data["global_obj_top"]:
        mark = "" if obj in data["KNOWN"] else "  ← 未识别(丢行)"
        print(f"  {obj:<22}{cnt:>8}{mark}")
    print()
    print("全局【未识别 fixture】按出现文件数 Top30（这些行会被静默丢）:")
    if not data["global_unknown_top"]:
        print("  (无 — 所有 obj 都在 KNOWN 内)")
    for obj, files in data["global_unknown_top"]:
        print(f"  {obj:<22}{files:>6} 个文件")

if __name__ == "__main__":
    main()
