"""SSH 自动化脚本：在运行 IST-Core 的服务器上部署自签证书 + 修改 frpc.toml。

用法：
    python wecom_bot/setup_frp.py
"""

import sys
import time
import paramiko


WSL_HOST = "192.168.88.60"
WSL_USER = "root"
WSL_PASS = ""

CLOUD_HOST = "49.234.21.32"


def ssh_exec(client: paramiko.SSHClient, cmd: str, timeout: int = 30) -> tuple[str, str]:
    print(f"  $ {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="ignore")
    err = stderr.read().decode("utf-8", errors="ignore")
    if out.strip():
        print(f"    [stdout] {out.strip()[:500]}")
    if err.strip():
        print(f"    [stderr] {err.strip()[:500]}")
    return out, err


def connect() -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"🔌 连接 {WSL_USER}@{WSL_HOST} ...")
    client.connect(hostname=WSL_HOST, username=WSL_USER, password=WSL_PASS,
                   timeout=10, allow_agent=False, look_for_keys=False)
    print("✅ 连接成功\n")
    return client


def step_1_gen_cert(client: paramiko.SSHClient) -> None:
    print("=" * 60)
    print("步骤 1/4: 生成自签证书")
    print("=" * 60)
    cd = "cd /opt/frp/ssl && "
    cmds = [
        "rm -rf /opt/frp/ssl && mkdir -p /opt/frp/ssl",
        f"{cd}openssl genrsa -out ca.key 2048 2>&1",
        f'{cd}openssl req -x509 -new -nodes -key ca.key -days 3650 -subj "/CN=MyWecomCA" -out ca.crt 2>&1',
        f"{cd}openssl genrsa -out server.key 2048 2>&1",
        f"bash -c 'cd /opt/frp/ssl && cat > server.ext <<EOF\nauthorityKeyIdentifier=keyid,issuer\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment\nsubjectAltName=@alt_names\n[alt_names]\nDNS.1 = wecom.{CLOUD_HOST}.nip.io\nIP.1  = {CLOUD_HOST}\nEOF'",
        f'{cd}openssl req -new -key server.key -subj "/CN=wecom.{CLOUD_HOST}.nip.io" -out server.csr 2>&1',
        f"{cd}openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 365 -sha256 -extfile server.ext 2>&1",
        "ls -la /opt/frp/ssl/",
        "openssl x509 -in /opt/frp/ssl/server.crt -noout -subject -ext subjectAltName 2>&1",
    ]
    for cmd in cmds:
        ssh_exec(client, cmd)


def step_2_rewrite_frpc(client: paramiko.SSHClient) -> None:
    print("\n" + "=" * 60)
    print("步骤 2/4: 改写 frpc.toml")
    print("=" * 60)
    frpc_content = f'''serverAddr = "{CLOUD_HOST}"
serverPort = 7000

auth.method = "token"
auth.token = "MyConfigToken_2026_ChangeMe"

[[proxies]]
name = "qyweixin-bot"
type = "https"
localIp = "127.0.0.1"
localPort = 8088
customDomains = ["wecom.{CLOUD_HOST}.nip.io"]
transport.useEncryption = true

[proxies.plugin]
type = "https2http"
localAddr = "127.0.0.1:8088"
crtPath = "/opt/frp/ssl/server.crt"
keyPath = "/opt/frp/ssl/server.key"
hostHeaderRewrite = "127.0.0.1:8088"
'''
    sftp = client.open_sftp()
    try:
        with sftp.file("/opt/frp/frpc.toml", "w") as f:
            f.write(frpc_content)
        print(f"  📝 已写入 /opt/frp/frpc.toml ({len(frpc_content)} 字节)")
    finally:
        sftp.close()
    ssh_exec(client, "cat /opt/frp/frpc.toml")


def step_3_restart_frpc(client: paramiko.SSHClient) -> None:
    print("\n" + "=" * 60)
    print("步骤 3/4: 重启 frpc")
    print("=" * 60)
    ssh_exec(client, "systemctl restart frpc 2>&1")
    time.sleep(2)
    ssh_exec(client, "systemctl status frpc --no-pager -l 2>&1 | head -30")


def step_4_verify(client: paramiko.SSHClient) -> None:
    print("\n" + "=" * 60)
    print("步骤 4/4: 验证 frp 链路")
    print("=" * 60)
    cmds = [
        f"nslookup wecom.{CLOUD_HOST}.nip.io 2>&1 | head -10",
        "echo '---'",
        f"curl -kv https://wecom.{CLOUD_HOST}.nip.io/health --max-time 10 2>&1 | tail -30",
        "echo '---'",
        f"curl -kv 'https://wecom.{CLOUD_HOST}.nip.io/wecom/callback?msg_signature=x&timestamp=1&nonce=x&echostr=x' --max-time 10 2>&1 | tail -20",
    ]
    for cmd in cmds:
        ssh_exec(client, cmd, timeout=20)


def main() -> int:
    print("🚀 开始在 WSL 上部署 frp 自签证书配置")
    print(f"   目标: {WSL_USER}@{WSL_HOST}\n")
    try:
        client = connect()
    except paramiko.AuthenticationException:
        print(f"❌ 认证失败：{WSL_USER}@{WSL_HOST}")
        return 1
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        return 1

    try:
        step_1_gen_cert(client)
        step_2_rewrite_frpc(client)
        step_3_restart_frpc(client)
        step_4_verify(client)
    except Exception as e:
        print(f"\n❌ 执行出错: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        client.close()
        print("\n🔌 已断开连接")

    print("\n" + "=" * 60)
    print("✅ 全部完成！")
    print("=" * 60)
    print(f"\n📋 接下来：\n  1. 启动中间件：python -m wecom_bot.main\n  2. 企微后台填：https://wecom.{CLOUD_HOST}.nip.io/wecom/callback")
    return 0


if __name__ == "__main__":
    sys.exit(main())
