"""把现役（103）的旧框架 stdio MCP server（``/home/test/mcp_server/``）克隆到环境池里的新机。

背景（2026-06-24 实测）：环境池 4 机里只有 103 有 ``/home/test/mcp_server/server.py``
（IST-Core pipeline 经 FrameworkMCPClient 驱动的 stdio server）；93/79/105 只跑新的
``/home/test/MCP_Server/server.py --http``（工具集完全不同），缺这个 stdio server。
本脚本把 ``server.py`` / ``result_db.py`` / ``tools.py`` 从源机复制到目标机，让它们成为
103 的克隆，从而能被现有 pipeline 驱动、加入并行池（``IST_ENV_POOL_ENABLED=1``）。

安全：
- ``--dry-run``（默认）只报告现状 + 将做的事；``--apply`` 才真复制。
- 默认**不覆盖**已存在的 server.py（除非 ``--force``）。
- 口令从 ``IST_JUMPHOST_PASS`` 读，不打印。
- ⚠ 设备 conf 正确性由 ops 复核：各机设备床「隔离但同地址」克隆时 conf 通常可直接复用，
  但请人工确认源机 conf 不含指向 103 自身的硬编码，避免新机误驱动 103 的设备。

用法::

    python -m scripts.maintenance.deploy_framework_to_envs                      # dry-run，看现状
    python -m scripts.maintenance.deploy_framework_to_envs --apply              # 复制到所有缺失目标
    python -m scripts.maintenance.deploy_framework_to_envs --apply --targets 10.4.127.93,10.4.127.79
"""
from __future__ import annotations

import argparse
import os
import posixpath
import sys

from main.case_compiler import config
from main.case_compiler.device_mcp_client import _password, framework_ready

_FILES = ("server.py", "result_db.py", "tools.py")
_REMOTE_DIR = "/home/test/mcp_server"


def _ssh(env):
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(env.jumphost, port=int(env.ssh_port), username=env.ssh_user,
              password=_password(env), timeout=15, look_for_keys=False, allow_agent=False)
    return c


def _read_source_files(src_env) -> dict[str, bytes]:
    c = _ssh(src_env)
    try:
        sftp = c.open_sftp()
        out: dict[str, bytes] = {}
        for f in _FILES:
            with sftp.open(posixpath.join(_REMOTE_DIR, f), "rb") as fh:
                out[f] = fh.read()
        return out
    finally:
        c.close()


def _deploy_to(env, blobs: dict[str, bytes], force: bool, apply: bool) -> str:
    c = _ssh(env)
    try:
        sftp = c.open_sftp()
        exists = True
        try:
            sftp.stat(posixpath.join(_REMOTE_DIR, "server.py"))
        except IOError:
            exists = False
        if exists and not force:
            return "已存在 server.py，跳过（--force 覆盖）"
        if not apply:
            verb = "覆盖" if exists else "创建"
            return f"将{verb} {_REMOTE_DIR}/ 并写入 {', '.join(_FILES)}（dry-run，未执行）"
        c.exec_command(f"mkdir -p {_REMOTE_DIR}/tasks")[1].channel.recv_exit_status()
        for f, data in blobs.items():
            with sftp.open(posixpath.join(_REMOTE_DIR, f), "wb") as fh:
                fh.write(data)
        return f"已写入 {len(blobs)} 文件；framework_ready={framework_ready(env)}"
    finally:
        c.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="克隆旧框架 stdio MCP server 到环境池新机")
    ap.add_argument("--source", default="10.4.127.103", help="源跳板机（有旧 mcp_server）")
    ap.add_argument("--targets", default="", help="逗号分隔目标；缺省=池里除源外所有")
    ap.add_argument("--apply", action="store_true", help="真复制（缺省 dry-run）")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的 server.py")
    args = ap.parse_args(argv)

    os.environ.setdefault("IST_ENV_POOL_ENABLED", "1")  # 临时启用以枚举多机
    config.get_config(reload=True)
    envs = {e.jumphost: e for e in config.load_environments()}

    src_env = envs.get(args.source) or config.Environment(id="src", jumphost=args.source)
    if args.targets:
        tgt_hosts = [h.strip() for h in args.targets.split(",") if h.strip()]
    else:
        tgt_hosts = [h for h in envs if h != args.source]
    targets = [envs.get(h) or config.Environment(id=f"env-{h.rsplit('.', 1)[-1]}", jumphost=h)
               for h in tgt_hosts]

    print(f"源: {args.source}  目标: {', '.join(tgt_hosts) or '(无)'}  "
          f"模式: {'APPLY' if args.apply else 'DRY-RUN'}")
    print("\n现状（framework_ready = 旧 stdio server.py 是否就绪）:")
    print(f"  {args.source} (源): {framework_ready(src_env)}")
    for env in targets:
        print(f"  {env.jumphost}: {framework_ready(env)}")

    try:
        blobs = _read_source_files(src_env)
    except Exception as exc:  # noqa: BLE001
        print(f"\n✗ 读源失败: {exc}")
        return 2
    print("\n源文件: " + ", ".join(f"{f}({len(b)}B)" for f, b in blobs.items()))

    print("\n部署:")
    rc = 0
    for env in targets:
        try:
            print(f"  {env.jumphost}: {_deploy_to(env, blobs, args.force, args.apply)}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {env.jumphost}: ✗ {exc}")
            rc = 1
    if not args.apply:
        print("\n（dry-run；加 --apply 真执行。务必先人工确认各机设备 conf 正确。）")
    return rc


if __name__ == "__main__":
    sys.exit(main())
