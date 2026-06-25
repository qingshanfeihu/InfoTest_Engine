"""框架级黑盒 tool（跳转机侧，Py3.8 纯标准库）。

把跳转机 apv_src pytest 框架当黑盒，暴露窄动作：
  list_capabilities / read_case_xlsx / write_case / run_cases_submit /
  run_cases_status / promote_case / probe_show

边界：不改框架 .py、不调 run.sh（git 冲突会挂）、直调 .python3.8 -m pytest。
CWD 硬约束：所有 pytest/import 框架库都在 cwd=APV_SRC 下跑。
全局单跑锁 + task 落盘（镜像 kms 模式）。
"""

import json
import os
import re
import shutil
import subprocess
import time

APV_SRC = os.environ.get("IST_APV_SRC", "/home/test/apv_src")
PY38 = os.environ.get("IST_JUMPHOST_PY38", APV_SRC + "/.python3.8/bin/python")
_STAGING_MODULE = os.environ.get("IST_STAGING_MODULE", "sdns")
STAGING_PARENT = os.environ.get(
    "IST_STAGING_PARENT", APV_SRC + "/smoke_test/" + _STAGING_MODULE
)   # ist_staging_<module> 落这里
# run 清单目录（case_id↔autoid 关联，conftest --list 读这里），与 framework_sync lists/ 镜像同源
LISTS_DIR = os.environ.get("IST_LISTS_DIR", APV_SRC + "/lists")
# 晋升登记表（autoid 命名空间防撞 + 来源溯源），落 STAGING_PARENT 下隐藏文件
PROMOTE_MANIFEST = ".ist_promote_manifest.json"
TASK_DIR = os.environ.get("IST_MCP_TASK_DIR", "/home/test/mcp_server/tasks")
LOCK_FILE = os.environ.get("IST_MCP_LOCK_FILE", "/home/test/mcp_server/run.lock")



def _ensure_dirs():
    for d in (TASK_DIR, os.path.dirname(LOCK_FILE)):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass


def _conf_name():
    """复刻 get_conf_name：本机 10.4 IP 末段 + .conf。"""
    out = subprocess.run(["ip", "add"], capture_output=True, text=True).stdout
    m = re.search(r"10\.4\.\d+\.(\d+)/\d+", out)
    return ("%s.conf" % m.group(1)) if m else "103.conf"


def _read_conf_text():
    path = os.path.join(APV_SRC, "conf", _conf_name())
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


# ── list_capabilities ────────────────────────────────────────────────

def list_capabilities():
    """读 lib/apv/apv_action.py 的 command_function_mapping + synonyms + 通用方法。"""
    action_py = os.path.join(APV_SRC, "lib/apv/apv_action.py")
    intents = {}
    with open(action_py, "r", encoding="utf-8", errors="replace") as f:
        txt = f.read()
    for m in re.finditer(r"'([^']+)'\s*:\s*self\.(func_\d+)", txt):
        intents[m.group(1)] = m.group(2)
    syn_path = os.path.join(APV_SRC, "lib/apv/apv_synonyms")
    synonyms = ""
    if os.path.exists(syn_path):
        with open(syn_path, "r", encoding="utf-8", errors="replace") as f:
            synonyms = f.read()
    return {
        "command_function_mapping": intents,
        "synonyms": synonyms,
        "generic_methods": [
            "cmd_config", "cmds_config", "cmd_enable", "cmd", "array_config",
        ],
        "check_methods": ["found", "abs_found", "not_found", "found_times"],
        "test_env_hosts": ["routera", "routerb", "server231", "server232", "server213", "console"],
    }


# ── read_case_xlsx ───────────────────────────────────────────────────

def read_case_xlsx(path):
    """复用框架 lib/test_xlsx.read_excel_with_openpyxl 读 cell-grid。"""
    import sys
    if APV_SRC not in sys.path:
        sys.path.insert(0, APV_SRC)
    from lib.test_xlsx import read_excel_with_openpyxl
    grid = read_excel_with_openpyxl(path)
    return {"path": path, "grid": grid}


# ── write_case ───────────────────────────────────────────────────────

def write_case(module, autoid, xlsx_b64):
    """落每用例子目录 ist_staging_<module>/<autoid>/，原子写 .tmp→rename + 软链 test_xlsx.py。"""
    import base64
    stg = os.path.join(STAGING_PARENT, "ist_staging_%s" % module, str(autoid))
    os.makedirs(stg, exist_ok=True)
    data = base64.b64decode(xlsx_b64)
    final = os.path.join(stg, "case.xlsx")
    tmp = final + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.rename(tmp, final)
    # symlink test_xlsx.py → ../../../../lib/test_xlsx.py (depth: sdns/ist_staging_x/autoid/ → apv_src/lib)
    link = os.path.join(stg, "test_xlsx.py")
    target = "../../../../lib/test_xlsx.py"
    if os.path.lexists(link):
        os.remove(link)
    os.symlink(target, link)
    return {"staging_dir": stg, "xlsx": final, "bytes": len(data)}


# ── run_cases (submit/status) ────────────────────────────────────────

def _staging_node(module, autoid):
    """返回 staging 下要跑的 pytest 目标：显式 test_xlsx.py，否则整目录（仅声明式 xlsx 用例）。"""
    stg = os.path.join(STAGING_PARENT, "ist_staging_%s" % module, str(autoid))
    xnode = os.path.join(stg, "test_xlsx.py")
    if os.path.exists(xnode):
        return xnode
    if os.path.isdir(stg):
        return stg
    return None

def run_cases_submit(module, autoid, build):
    """完全脱离父进程跑 pytest（setsid 守护），写 task 状态。全局单跑文件锁。返回 task_id。

    关键：stdio server 进程随 stdin 关闭即退出，故不能用 daemon thread 守 Popen——
    必须 setsid 双 fork 脱离，让 pytest 在 server 退出后继续。单跑锁用文件锁（跨进程）。
    """
    stg = os.path.join(STAGING_PARENT, "ist_staging_%s" % module, str(autoid))
    node = _staging_node(module, autoid)
    if not node:
        return {"error": "staging not found: %s" % stg}
    return _submit_pytest(module, str(autoid), build, node)


def _read_lock():
    """返回 (task_id, pid) 或 None。锁文件内容格式 '<task_id>:<pid>'。"""
    try:
        with open(LOCK_FILE) as f:
            old = f.read().strip()
        if not old:
            return None
        parts = old.split(":")
        pid = int(parts[-1])      # pid 是最后一段（task_id 内含下划线但无冒号）
        return (":".join(parts[:-1]), pid)
    except Exception:
        return None


def _acquire_lock(task_id):
    """原子获取单跑锁。成功返回锁 fd（调用方写入真实 pid 后 close）；失败返回 None。

    用 O_CREAT|O_EXCL 在 server 进程内同步建锁，消除"检查-写入"TOCTOU 窗口。
    若锁已存在但持有者进程已死（stale），回收后重试一次。
    """
    for attempt in (0, 1):
        try:
            return os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            held = _read_lock()
            if held and _pid_alive(held[1]):
                return None        # 真有进程在跑
            # stale（持有者已死或锁内容损坏）→ 回收重试
            try:
                os.unlink(LOCK_FILE)
            except FileNotFoundError:
                pass
    return None


def _busy_info(held):
    """撞锁时构造结构化 busy 信息：正在验证哪个 autoid、已跑多少秒。

    held = (task_id, pid)。task_id 形如 ``ist_<module>_<autoid>_<epoch>``，
    autoid 与起始 epoch 都能从中解析；起始时间优先用 status 文件的 ts（更准），
    缺失则回退 task_id 尾段 epoch。让 ist 端 agent 知道"环境正在验证上一个用例"
    并能估算还要等多久，自行决定等/跳/上报。
    """
    task_id = held[0] if held else ""
    autoid, started = "", None
    if task_id:
        parts = task_id.split("_")
        # ist_<module>_<autoid>_<epoch>：尾段 epoch、倒数第二段 autoid
        if len(parts) >= 4 and parts[-1].isdigit():
            autoid = parts[-2]
            started = int(parts[-1])
        # status 文件的 ts 更准（实际起跑时刻）
        try:
            with open(os.path.join(TASK_DIR, task_id + ".status.json")) as f:
                st = json.load(f)
            started = st.get("ts", started)
            autoid = st.get("autoid", autoid)
        except Exception:
            pass
    elapsed_s = int(time.time() - started) if started else None
    msg = "环境忙：正在验证用例 %s" % (autoid or "?")
    if elapsed_s is not None:
        msg += "，已运行 %ds" % elapsed_s
    msg += "。同一时刻只能跑一个上机任务，请等上一个验证完成后重试。"
    return {
        "error": "device_busy",
        "busy": True,
        "running_autoid": autoid,
        "running_task_id": task_id,
        "elapsed_s": elapsed_s,
        "message": msg,
    }


def _submit_pytest(module, autoid, build, node):
    """setsid 脱离跑 pytest 目标 node（文件或目录）。共享给单用例/整目录批量。"""
    _ensure_dirs()

    task_id = "ist_%s_%s_%d" % (module, autoid, int(time.time()))
    lock_fd = _acquire_lock(task_id)
    if lock_fd is None:
        return _busy_info(_read_lock())

    log_path = os.path.join(TASK_DIR, task_id + ".log")
    status_path = os.path.join(TASK_DIR, task_id + ".status.json")
    junit = os.path.join(TASK_DIR, task_id + ".xml")

    # setsid 完全脱离：wrapper 跑 pytest，结束后写 done 状态 + 释放锁（rm）。
    # 锁已由 server 原子建好，wrapper 不再建锁，只负责结束时删除。
    runner = os.path.join(TASK_DIR, task_id + ".sh")
    script = (
        "#!/bin/bash\n"
        "cd '%s'\n" % APV_SRC +
        "'%s' -m pytest -s '%s' --build '%s' --junitxml '%s' > '%s' 2>&1\n"
        % (PY38, node, build, junit, log_path) +
        "RC=$?\n"
        "python3 -c \"import json,time;json.dump({'task_id':'%s','state':'done','rc':$RC,'build':'%s','module':'%s','autoid':'%s','ts':time.time()},open('%s','w'))\"\n"
        % (task_id, build, module, autoid, status_path) +
        "rm -f '%s'\n" % LOCK_FILE
    )
    with open(runner, "w") as f:
        f.write(script)
    os.chmod(runner, 0o755)

    _write_status(status_path, task_id, "running", build=build, module=module, autoid=autoid)
    proc = subprocess.Popen(
        ["setsid", "bash", runner],
        cwd=APV_SRC, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    # 把真实子进程 pid 写入锁，供 staleness 检查（进程崩了锁可被回收）
    try:
        os.write(lock_fd, ("%s:%d" % (task_id, proc.pid)).encode())
    finally:
        os.close(lock_fd)
    return {"task_id": task_id}


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _write_status(path, task_id, state, **kw):
    payload = {"task_id": task_id, "state": state, "ts": time.time()}
    payload.update(kw)
    try:
        with open(path, "w") as f:
            json.dump(payload, f)
    except Exception:
        pass


def run_cases_status(task_id, build=None, case_ids=None):
    """查 task 状态 + MySQL 结果（主源）+ junit 兜底。"""
    status_path = os.path.join(TASK_DIR, task_id + ".status.json")
    status = {}
    if os.path.exists(status_path):
        try:
            with open(status_path) as f:
                status = json.load(f)
        except Exception:
            pass
    build = build or status.get("build")
    results = {}
    mysql_err = None
    if build and case_ids:
        try:
            from result_db import query_results, read_mysql_ip
            mysql_ip = read_mysql_ip(_read_conf_text())
            results = query_results(mysql_ip, build, case_ids)
        except Exception as e:
            mysql_err = str(e)
    # tail log
    log_path = os.path.join(TASK_DIR, task_id + ".log")
    tail = ""
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", errors="replace") as f:
                tail = "".join(f.readlines()[-25:])
        except Exception:
            pass
    return {"status": status, "results": results, "mysql_error": mysql_err, "log_tail": tail}


# ── promote 纯逻辑（无文件系统副作用，可注入单测）────────────────────────

def _feature_from_xlsx(xlsx_path):
    """从 xlsx 路径取 feature 名（去扩展名的 basename）。"""
    base = os.path.basename(str(xlsx_path))
    if base.lower().endswith(".xlsx"):
        base = base[:-5]
    return base


def plan_promote_paths(staging_parent, module, feature, src_basename):
    """规划晋升目标路径（纯函数，不碰磁盘）。

    P1 产物粒度 = 单 feature 单 xlsx（含 N case）。整文件晋升到
    smoke_test/<staging_root>/<feature>/<src_basename>，保留原文件名，
    不再切成 <autoid>.xlsx 丢失同文件其他 case。

    返回 {feature_dir, dst_xlsx, link, link_target}。
    """
    feature_dir = os.path.join(staging_parent, str(feature))
    dst_xlsx = os.path.join(feature_dir, src_basename)
    link = os.path.join(feature_dir, "test_xlsx.py")
    # feature_dir 深度：smoke_test/<module>/<feature>/ → apv_src/lib
    link_target = "../../../lib/test_xlsx.py"
    return {
        "feature_dir": feature_dir,
        "dst_xlsx": dst_xlsx,
        "link": link,
        "link_target": link_target,
    }


def parse_list_caseids(text):
    """解析 lists 文件文本，返回已登记 case_id 有序列表（去重保序）。

    兼容 conftest get_caseid：每行形如 '| exec | <caseid> |' 或含 ':' 子用例行。
    取每行首个 7-60 位 [\\w.] token 作为 case_id；# 注释 / 空行跳过。
    """
    seen = []
    seen_set = set()
    for raw in str(text).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.search(r"[\w.]{7,60}", line)
        if not m:
            continue
        cid = m.group(0)
        if cid not in seen_set:
            seen_set.add(cid)
            seen.append(cid)
    return seen


def render_list_text(caseids):
    """把 case_id 列表渲染成框架 lists 行格式（| exec | <id> |，每行一个）。"""
    lines = ["| exec | %s |" % str(c) for c in caseids]
    return "\n".join(lines) + ("\n" if lines else "")


def merge_list_text(existing_text, new_caseids):
    """把 new_caseids 并入既有 lists 文本，去重保序（旧的在前，新增追加）。

    返回 (merged_text, added_caseids)。既有条目原样保留，仅追加缺失的。
    """
    existing = parse_list_caseids(existing_text or "")
    existing_set = set(existing)
    added = []
    for c in new_caseids:
        c = str(c)
        if c not in existing_set:
            existing_set.add(c)
            existing.append(c)
            added.append(c)
    return render_list_text(existing), added


def register_manifest(manifest, caseids, source_key, feature, xlsx_rel, overwrite=False):
    """autoid 命名空间防撞登记（纯函数）。

    manifest: {autoid: {source, feature, xlsx}}。同 autoid 不同 source 视为冲突。
    返回 (new_manifest, conflicts)。conflicts 为 [{autoid, existing_source, new_source}]。
    overwrite=True 时强制覆盖且不报冲突。
    """
    new_manifest = dict(manifest or {})
    conflicts = []
    for cid in caseids:
        cid = str(cid)
        prev = new_manifest.get(cid)
        if prev and prev.get("source") != source_key and not overwrite:
            conflicts.append({
                "autoid": cid,
                "existing_source": prev.get("source"),
                "new_source": source_key,
            })
            continue
        new_manifest[cid] = {
            "source": source_key,
            "feature": feature,
            "xlsx": xlsx_rel,
        }
    return new_manifest, conflicts


# ── promote_case（文件系统编排，调上面纯函数）──────────────────────────

def _load_manifest(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_manifest(path, manifest):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.rename(tmp, path)


def _write_list_file(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.rename(tmp, path)


def promote_case(module, autoid=None, feature=None, xlsx_path=None,
                 case_autoids=None, source=None, overwrite=False, list_name=None):
    """staging 通过后整 feature 晋升到正式 smoke_test/<module>/<feature>/。

    粒度：P1 产物 = 单 feature 单 xlsx（含 N case）。按 **文件** 晋升整个 feature
    xlsx，autoid 仅作 case 定位/校验，不再切成 <autoid>.xlsx 丢失同文件其他 case。

    参数：
      module        — 模块名（如 sdns），决定 staging 子目录与 lists 文件名。
      autoid        — 旧签名兼容：单 case 定位（无 xlsx_path 时走 staging case.xlsx）。
      feature       — feature 名（晋升目标子目录）；缺省从 xlsx 文件名推导，再退回 autoid。
      xlsx_path     — 直接指定要晋升的 feature xlsx（P1 产物）；优先于 staging。
      case_autoids  — 该 feature xlsx 内全部 case 的 autoid 列表，写入 lists 清单；
                      缺省退回 [autoid]（旧单 case 行为）。
      source        — autoid 命名空间防撞的来源标识（如编译运行/脑图名）；缺省=feature。
      overwrite     — True 时强制覆盖 manifest 冲突项。
      list_name     — lists 文件名；缺省=module（conftest --list <module>）。

    向后兼容：promote_case(module, autoid) 旧调用不报错，等价晋升 staging 单 case。
    """
    # 1) 解析源 xlsx：显式 xlsx_path 优先，否则退回旧 staging case.xlsx
    if xlsx_path:
        src_xlsx = str(xlsx_path)
    elif autoid is not None:
        stg = os.path.join(STAGING_PARENT, "ist_staging_%s" % module, str(autoid))
        src_xlsx = os.path.join(stg, "case.xlsx")
    else:
        return {"error": "promote_case 需要 xlsx_path 或 autoid 之一"}

    if not os.path.isfile(src_xlsx):
        return {"error": "source xlsx not found: %s" % src_xlsx}

    # 2) 解析 feature 名：显式 > xlsx 文件名 > autoid（旧）
    if feature:
        feat = str(feature)
    elif xlsx_path:
        feat = _feature_from_xlsx(src_xlsx)
    else:
        feat = str(autoid)

    # 3) 解析要登记的 case_id 列表
    if case_autoids:
        case_ids = [str(c) for c in case_autoids]
    elif autoid is not None:
        case_ids = [str(autoid)]
    else:
        case_ids = []

    source_key = str(source) if source else feat

    # 4) 规划目标路径（纯函数），整文件 copy + symlink
    src_basename = os.path.basename(src_xlsx)
    plan = plan_promote_paths(STAGING_PARENT, module, feat, src_basename)
    os.makedirs(plan["feature_dir"], exist_ok=True)
    shutil.copy(src_xlsx, plan["dst_xlsx"])
    if not os.path.lexists(plan["link"]):
        os.symlink(plan["link_target"], plan["link"])

    result = {
        "promoted": plan["dst_xlsx"],
        "feature": feat,
        "module": module,
        "cases": case_ids,
    }

    # 5) autoid 命名空间防撞登记
    manifest_path = os.path.join(STAGING_PARENT, PROMOTE_MANIFEST)
    xlsx_rel = os.path.relpath(plan["dst_xlsx"], STAGING_PARENT)
    if case_ids:
        manifest = _load_manifest(manifest_path)
        new_manifest, conflicts = register_manifest(
            manifest, case_ids, source_key, feat, xlsx_rel, overwrite=overwrite
        )
        if conflicts and not overwrite:
            result["lists_updated"] = False
            result["conflicts"] = conflicts
            result["warning"] = (
                "autoid 命名空间冲突，已晋升 xlsx 但未更新 lists；"
                "传 overwrite=True 覆盖或换 source 区分"
            )
            return result
        try:
            _save_manifest(manifest_path, new_manifest)
        except Exception as e:
            result["manifest_error"] = str(e)

        # 6) 生产 run 清单关联：把 case_id 并入 lists/<list_name>
        ln = str(list_name) if list_name else str(module)
        list_path = os.path.join(LISTS_DIR, ln)
        existing_text = ""
        if os.path.isfile(list_path):
            try:
                with open(list_path, "r", encoding="utf-8", errors="replace") as f:
                    existing_text = f.read()
            except Exception:
                existing_text = ""
        merged, added = merge_list_text(existing_text, case_ids)
        try:
            _write_list_file(list_path, merged)
            result["lists_updated"] = True
            result["lists_file"] = list_path
            result["lists_added"] = added
        except Exception as e:
            result["lists_updated"] = False
            result["lists_error"] = str(e)
    else:
        result["lists_updated"] = False
        result["warning"] = "无 case_autoids/autoid，未更新 lists 清单"

    return result


def _parse_device_conn(build_name=""):
    """从框架 conf 解析被测设备 SSH 连接参数（probe 只读用）。

    设备段名由 build_name 决定——**照搬框架 lib/config.py 的 build→段 映射(单一事实源)**:
      前缀: 'array'/'nodebug.(Beta|Rel)_APV'→array; 'infosec.*APV'→infosec; 'nsae'→nsae
      后缀: 'HG[-_]U'→_hgu; 'HG[-_]K'→_hgk; 否则 _ustack
    IP 取 [comm] ssh_ips 首个。返回 (ip,user,password,hostname) 或 None。凭据按 key 取,不回显。
    """
    try:
        import configparser
        text = _read_conf_text()
        cp = configparser.ConfigParser(strict=False)
        cp.read_string(text)
        ip = None
        if cp.has_option("comm", "ssh_ips"):
            ip = cp.get("comm", "ssh_ips").split(",")[0].strip()
        # 复刻框架 config.py 选段逻辑(不硬猜段名)
        prefix = ""
        if re.search(r"array", build_name, re.I) or re.search(r"nodebug[-_](Beta|Rel)_APV", build_name, re.I):
            prefix = "array"
        elif re.search(r"infosec.*APV", build_name, re.I):
            prefix = "infosec"
        elif re.search(r"nsae", build_name, re.I):
            prefix = "nsae"
        if re.search(r"HG[-_]U", build_name, re.I):
            suffix = "_hgu"
        elif re.search(r"HG[-_]K", build_name, re.I):
            suffix = "_hgk"
        else:
            suffix = "_ustack"
        sec = (prefix + suffix) if prefix else ""
        user = passwd = hostname = None
        sections = [sec] if (sec and cp.has_section(sec)) else [
            s for s in cp.sections() if s not in ("comm", "other", "env")]
        for s in sections:
            if cp.has_option(s, "user"):
                user = cp.get(s, "user")
            if cp.has_option(s, "passwd"):
                passwd = cp.get(s, "passwd")
            elif cp.has_option(s, "password"):
                passwd = cp.get(s, "password")
            if cp.has_option(s, "hostname"):
                hostname = cp.get(s, "hostname")
            if user and passwd:
                break
        if ip and user and passwd:
            return (ip, user, passwd, hostname or "")
    except Exception:
        pass
    return None


def probe_show(command, build=""):
    """只读探针：在被测设备上跑 show/get 命令，回传输出（KP1 设备 overlay 来源）。

    安全约束：
      - 硬白名单：命令首 token 必须 show/get（拒绝任何配置/写命令）。
      - 单跑锁：设备单例，与 run_cases 互斥（避免抢占正在跑的 build 的设备 shell）。
      - 交互式 invoke_shell（enable → 读 prompt → 发 show → 读回显），符合设备分页/enable 模型。
    设备与手册冲突的判定在 IST-Core 侧（classify + overlay 比对），此处只取事实。
    """
    cmd = (command or "").strip()
    first = cmd.split(None, 1)[0].lower() if cmd else ""
    if first not in ("show", "get"):
        return {"error": "probe only allows commands starting with show/get"}

    conn = _parse_device_conn(build)
    if conn is None:
        return {"error": "cannot resolve device connection from framework conf"}
    ip, user, passwd, hostname = conn

    # 单跑锁：设备单例，与 run_cases 互斥
    _ensure_dirs()
    task_id = "probe_%d" % int(time.time())
    lock_fd = _acquire_lock(task_id)
    if lock_fd is None:
        held = _read_lock()
        return {"error": "another run in progress (lock held by %s)" % (held[0] if held else "?")}
    try:
        os.write(lock_fd, ("%s:%d" % (task_id, os.getpid())).encode())
    finally:
        os.close(lock_fd)

    try:
        import paramiko
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(hostname=ip, port=22, username=user, password=passwd, timeout=15)
        chan = ssh.invoke_shell()

        def _read_until(token, timeout=8):
            import time as _t
            buf = ""
            end = _t.time() + timeout
            while _t.time() < end:
                if chan.recv_ready():
                    buf += chan.recv(65535).decode("utf-8", "replace")
                    if token in buf:
                        break
                else:
                    _t.sleep(0.1)
            return buf

        _read_until("#", timeout=5)
        chan.send("enable\n")
        _read_until("#", timeout=5)
        # 关闭分页避免 --More-- 卡死（show 命令前置）
        chan.send("terminal length 0\n")
        _read_until("#", timeout=3)
        chan.send(cmd + "\n")
        out = _read_until("#", timeout=10)
        ssh.close()
        # 去掉回显的命令行与结尾 prompt
        raw = out.splitlines()
        lines = [ln for ln in raw if ln.strip() not in (cmd, "")]
        # APV 语法错误:设备对无法识别的命令/参数,在出错 token 下方标 `^`(本固件不输出
        # `% Invalid input` 文字)。去噪后剥末尾提示符/空行,实质仅为 caret → 命令语法/参数无效。
        # 包装成清晰文字 + 找回命令回显行让 `^` 对齐有意义,免上层(LLM)把孤立 `^` 误读为有效输出。
        _tail = list(lines)
        while _tail and (not _tail[-1].strip() or re.match(r"^\S*[#>]$", _tail[-1].strip())):
            _tail.pop()
        _core = "\n".join(_tail).strip()
        if _core and re.match(r"^\^+$", _core):
            _echo = next((l for l in raw if l.strip() == cmd), cmd)
            _caret = next((l for l in _tail if l.strip().startswith("^")), "^")
            _out = ("%% Invalid input: command %r is invalid on this device "
                    "(syntax/parameter error; '^' marks the offending token)\n"
                    "%s\n%s") % (cmd, _echo.rstrip(), _caret.rstrip())
            return {"command": cmd, "output": _out, "device_ip": ip, "syntax_error": True}
        return {"command": cmd, "output": "\n".join(lines), "device_ip": ip}
    except Exception as e:
        return {"error": "probe failed: %s" % e}
    finally:
        try:
            os.unlink(LOCK_FILE)
        except Exception:
            pass
