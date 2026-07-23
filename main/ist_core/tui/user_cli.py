"""``infotest user`` CLI 入口。

用法::

    infotest user add <username> [--role admin|reviewer]
    infotest user list
    infotest user disable <username>
    infotest user passwd <username>
"""

from __future__ import annotations

import argparse
import getpass
import sys


def run_user_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="infotest user",
        description="用户管理（PostgreSQL ist_audit schema）。",
    )
    sub = parser.add_subparsers(dest="subcmd")

    p_add = sub.add_parser("add", help="创建新用户")
    p_add.add_argument("username", help="用户名")
    p_add.add_argument("--role", default="reviewer", choices=["admin", "reviewer" ,"superadmin"],
                       help="角色（默认 reviewer）")

    sub.add_parser("list", help="列出所有用户")

    p_disable = sub.add_parser("disable", help="禁用用户")
    p_disable.add_argument("username", help="用户名")

    p_passwd = sub.add_parser("passwd", help="重置密码")
    p_passwd.add_argument("username", help="用户名")

    args = parser.parse_args(argv)

    if not args.subcmd:
        parser.print_help()
        return 1

    from main.ist_core.auth.db import ensure_schema, pg_cursor

    ensure_schema()

    if args.subcmd == "add":
        return _cmd_add(args.username, args.role)
    elif args.subcmd == "list":
        return _cmd_list()
    elif args.subcmd == "disable":
        return _cmd_disable(args.username)
    elif args.subcmd == "passwd":
        return _cmd_passwd(args.username)
    return 1


def _cmd_add(username: str, role: str) -> int:
    from main.ist_core.auth.db import pg_cursor
    from main.ist_core.auth.password import hash_password

    # 检查是否已存在
    with pg_cursor() as cur:
        cur.execute("SELECT id FROM ist_audit.users WHERE username = %s", (username,))
        if cur.fetchone():
            print(f"错误：用户 '{username}' 已存在", file=sys.stderr)
            return 1

    # 交互式输入密码
    try:
        pw1 = getpass.getpass("输入密码: ")
        if len(pw1) < 8:
            print("错误：密码至少 8 个字符", file=sys.stderr)
            return 1
        pw2 = getpass.getpass("确认密码: ")
    except (EOFError, KeyboardInterrupt):
        print("\n已取消。")
        return 1

    if pw1 != pw2:
        print("错误：两次密码不一致", file=sys.stderr)
        return 1

    pw_hash = hash_password(pw1)
    with pg_cursor() as cur:
        cur.execute(
            """INSERT INTO ist_audit.users (username, password_hash, role)
               VALUES (%s, %s, %s)""",
            (username, pw_hash, role),
        )
    print(f"用户 '{username}' 创建成功（角色: {role}）")
    return 0


def _cmd_list() -> int:
    from main.ist_core.auth.db import pg_cursor

    with pg_cursor() as cur:
        cur.execute(
            "SELECT username, role, account_status, created_at, last_login_at FROM ist_audit.users ORDER BY created_at"
        )
        rows = cur.fetchall()

    if not rows:
        print("（无用户）")
        return 0

    # 简单表格输出
    print(f"{'用户名':<20} {'角色':<12} {'状态':<10} {'创建时间':<22} {'最后登录'}")
    print("-" * 90)
    for r in rows:
        created = str(r["created_at"])[:19] if r["created_at"] else "-"
        last_login = str(r["last_login_at"])[:19] if r["last_login_at"] else "-"
        print(f"{r['username']:<20} {r['role']:<12} {r['account_status']:<10} {created:<22} {last_login}")
    return 0


def _cmd_disable(username: str) -> int:
    from main.ist_core.auth.db import pg_cursor

    with pg_cursor() as cur:
        cur.execute(
            "UPDATE ist_audit.users SET account_status = 'disable', updated_at = now() WHERE username = %s",
            (username,),
        )
        if cur.rowcount == 0:
            print(f"错误：用户 '{username}' 不存在", file=sys.stderr)
            return 1
    print(f"用户 '{username}' 已禁用")
    return 0


def _cmd_passwd(username: str) -> int:
    from main.ist_core.auth.db import pg_cursor
    from main.ist_core.auth.password import hash_password

    # 检查用户存在
    with pg_cursor() as cur:
        cur.execute("SELECT id FROM ist_audit.users WHERE username = %s", (username,))
        if not cur.fetchone():
            print(f"错误：用户 '{username}' 不存在", file=sys.stderr)
            return 1

    try:
        pw1 = getpass.getpass("输入新密码: ")
        if len(pw1) < 8:
            print("错误：密码至少 8 个字符", file=sys.stderr)
            return 1
        pw2 = getpass.getpass("确认新密码: ")
    except (EOFError, KeyboardInterrupt):
        print("\n已取消。")
        return 1

    if pw1 != pw2:
        print("错误：两次密码不一致", file=sys.stderr)
        return 1

    pw_hash = hash_password(pw1)
    with pg_cursor() as cur:
        cur.execute(
            "UPDATE ist_audit.users SET password_hash = %s, updated_at = now(), failed_login_count = 0, locked_until = NULL WHERE username = %s",
            (pw_hash, username),
        )
    print(f"用户 '{username}' 密码已重置")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run_user_command(sys.argv[1:]))
