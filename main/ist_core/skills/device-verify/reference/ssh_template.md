# SSH execution template

## Method 1: run_python + paramiko (recommended)

paramiko ships with the project environment (`requirements.txt`) — no install step needed.

```python
import paramiko, time, re, json

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("<IP>", port=22, username="<user>", password="<pass>", timeout=10, look_for_keys=False, allow_agent=False)
shell = ssh.invoke_shell(term='vt100', width=200, height=50)
shell.settimeout(15)
time.sleep(3)

while shell.recv_ready():
    shell.recv(65535)

def send_cmd(cmd, wait=3.0):
    shell.send(cmd + '\n')
    time.sleep(wait)
    out = ""
    deadline = time.time() + 10
    while time.time() < deadline:
        if shell.recv_ready():
            chunk = shell.recv(65535).decode('utf-8', errors='replace')
            out += chunk
            if '--More--' in out:
                out = out.replace('--More--', '')
                shell.send(' ')
                time.sleep(0.5)
                continue
            if out.rstrip().endswith('>') or out.rstrip().endswith('#'):
                break
        else:
            time.sleep(0.3)
    lines = out.splitlines()
    if lines and cmd.strip() in lines[0]:
        lines = lines[1:]
    return '\n'.join(lines)

# 进入 enable
send_cmd('enable', 2.0)

# ── 只读验证场景 ──
# results = []
# for cmd in ["show xxx", "show yyy"]:
#     results.append({"command": cmd, "output": send_cmd(cmd)})
# print(json.dumps(results, ensure_ascii=False, indent=2))

# ── 配置下发场景 ──
# send_cmd('config terminal', 2.0)
# for cmd in ["<config命令1>", "<config命令2>"]:
#     out = send_cmd(cmd)
#     print(f"=== {cmd} ===\n{out}\n")
# send_cmd('exit')

ssh.close()
```

## Method 2: manual via ask_user

```
ssh -o StrictHostKeyChecking=no <user>@<IP>
# 进入 enable 后执行命令，贴回输出
```
