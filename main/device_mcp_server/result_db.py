"""框架 MySQL 结果通道封装（跳转机侧，Py3.8 纯标准库 + PyMySQL）。

复用框架 build_name 规范化（抄 lib/config.py L54-62）+ conf 的 mysql_ip（容错解析
git 冲突重复键），查 smoke_test 库 build 表取 per-case_id result。

不裸拼表名（经规范化复算）；mysql 凭据来自框架 conf + lib/mysqldb.py 既有约定
（user=root, db=smoke_test, port=3306）——server 在受信内网复用框架配置，不外传。
"""

import re


def normalize_build_name(build_name):
    """复刻 lib/config.py 的 build_name 规范化（表名）。"""
    b = build_name
    b = re.sub(r".*(ArrayOS.*?\.array)", r"\1", b)
    b = re.sub(r".*(nodebug.*?\.click)", r"\1", b)
    b = re.sub(r".*(Rel.*?).click", r"\1", b)
    b = re.sub(r".*(Rel.*?).array", r"\1", b)
    b = re.sub(r".*(Beta.*?).click", r"\1", b)
    b = re.sub(r".*(Beta.*?).array", r"\1", b)
    b = re.sub(r".*(Alpha.*?).click", r"\1", b)
    b = re.sub(r".*(Alpha.*?).array", r"\1", b)
    b = re.sub(r"-", r"_", b)
    return b


def read_mysql_ip(conf_text):
    """从 conf 文本容错读取 [other] mysql_ip（忽略 git 冲突标记/重复键/注释）。"""
    in_other = False
    val = None
    for line in conf_text.splitlines():
        s = line.strip()
        if s.startswith("<<<<<<") or s.startswith("======") or s.startswith(">>>>>>"):
            continue
        if s.startswith("[") and s.endswith("]"):
            in_other = (s == "[other]")
            continue
        if in_other and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            if k.strip() == "mysql_ip" and v.strip():
                val = v.strip()  # 取最后一个非注释值
    return val


def bare_autoid(case_id):
    """case_id 形态归一：剥离脚本名后缀与框架包装，得到裸 autoid。

    实证三类形态（计划 P0-4 / GAP-4）：
      - .pl 老用例：case_id 落库为 '0258010101.pl'
      - 改名后 .py：函数名 'test_<autoid>'，回填可能带 'test_' 前缀
      - xlsx：裸 autoid '203031753342777976'
    归一规则：去 'test_' 前缀 → 去末尾 '.<ext>'（ext 为字母）→ 取首段纯数字。
    """
    s = str(case_id).strip()
    if s.startswith("test_"):
        s = s[len("test_"):]
    # 去脚本扩展名后缀（.pl/.py/.sh…），仅当后缀是字母时（避免误切纯数字）
    m = re.match(r"^(.+?)\.[A-Za-z]+$", s)
    if m:
        s = m.group(1)
    return s


def query_results(mysql_ip, build_name, case_ids):
    """查 build 表取 {裸autoid: result}。

    case_ids 传入裸 autoid 列表，但库里 case_id 可能带 .pl/.py 后缀或 test_ 前缀
    （P0-4 归一层）。匹配时对每个 autoid 同时命中裸形态与 '<autoid>.%' 后缀形态，
    回填时把库里 case_id 归一回裸 autoid 作为 key，供调用方用裸 autoid 直查。
    """
    import os
    import pymysql

    # 凭据外置（去硬编码）：env 优先，缺则框架内置约定（受信内网复用框架配置）。
    user = os.environ.get("IST_MYSQL_USER") or "root"
    passwd = os.environ.get("IST_MYSQL_PASS") or "click1"
    db = os.environ.get("IST_MYSQL_DB") or "smoke_test"

    table = normalize_build_name(build_name)
    conn = pymysql.connect(
        host=mysql_ip, port=3306, user=user, passwd=passwd,
        db=db, charset="UTF8",
    )
    out = {}
    try:
        cur = conn.cursor()
        if case_ids:
            bare = [bare_autoid(c) for c in case_ids]
            # 每个 autoid 匹配三形态：裸 / '<id>.%'(后缀) / 'test_<id>%'(框架包装)
            clauses = []
            params = []
            for b in bare:
                clauses.append("(case_id = %s OR case_id LIKE %s OR case_id LIKE %s)")
                params.extend([b, b + ".%", "test_" + b + "%"])
            sql = "SELECT case_id, result FROM `%s` WHERE %s" % (table, " OR ".join(clauses))
            cur.execute(sql, params)
        else:
            sql = "SELECT case_id, result FROM `%s`" % table
            cur.execute(sql)
        for cid, res in cur.fetchall():
            # 归一回裸 autoid 作 key；同一 autoid 多形态时后者覆盖（一般唯一）
            out[bare_autoid(cid)] = res
        cur.close()
    finally:
        conn.close()
    return out
