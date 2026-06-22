"""测:不给 footprint,让 opus 自己 grep/read 手册,看能否产出正确完整的 SDNS rr 配置。

判定"问题在 footprint 碎片化 vs 模型/知识本身"。手动 ReAct 循环(opus + 手册 grep/read)。
"""
import glob
import re
import subprocess
import sys

from main.langchain_env import langchain_load_dotenv_if_present

MANUAL = "knowledge/data/markdown/product/10.5_cli__part*.md"


def do_grep(pattern):
    files = glob.glob(MANUAL)
    try:
        r = subprocess.run(["grep", "-rin", "-A2", pattern] + files,
                           capture_output=True, text=True, timeout=20)
        out = r.stdout[:2500]
        return out or "(无匹配)"
    except Exception as e:
        return f"(grep 错误: {e})"


def do_read(filename, rng):
    cands = glob.glob(f"knowledge/data/markdown/product/*{filename}*")
    if not cands:
        return "(文件未找到)"
    try:
        lines = open(cands[0], encoding="utf-8").read().split("\n")
        m = re.match(r"(\d+)-(\d+)", rng or "")
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            return "\n".join(lines[a:b])[:2500]
        return "\n".join(lines[:60])[:2500]
    except Exception as e:
        return f"(read 错误: {e})"


def main():
    langchain_load_dotenv_if_present()
    from main.ist_core.agents._llm import build_agent_chat_model, ist_core_tier_model
    m = build_agent_chat_model(model=ist_core_tier_model("opus"))

    sys_p = (
        "你是 APV SDNS 测试工程师。你可以查 10.5 版手册来确认命令:\n"
        "  - 输出一行 `GREP: <关键词>` 我帮你 grep 手册并返回匹配\n"
        "  - 输出一行 `READ: <文件关键词> <起>-<止>` 读手册某段\n"
        "想清楚了就输出 `CONFIG:` 后跟完整 CLI 配置(每行一条)。\n"
        "任务:配置使域名 autotest.com 通过 rr(轮询)算法解析到后端 172.16.35.231,"
        "监听器 IP 172.16.34.70,使 dig @172.16.34.70 autotest.com 能解析出 172.16.35.231。\n"
        "一次只发一个 GREP 或 READ 或 CONFIG。"
    )
    msgs = [("system", sys_p), ("user", "开始。")]
    config = None
    for turn in range(14):
        r = m.invoke(msgs)
        txt = str(getattr(r, "content", r)).strip()
        msgs.append(("assistant", txt))
        first = txt.splitlines()[0] if txt.splitlines() else ""
        print(f"\n--- turn{turn} opus: {first[:80]} ---", flush=True)
        if "CONFIG:" in txt:
            config = txt.split("CONFIG:", 1)[1].strip()
            break
        gm = re.search(r"GREP:\s*(.+)", txt)
        rm = re.search(r"READ:\s*(\S+)\s*(\S+)?", txt)
        if gm:
            res = do_grep(gm.group(1).strip())
            print(f"  grep {gm.group(1).strip()!r} → {len(res)} chars", flush=True)
            msgs.append(("user", "grep 结果:\n" + res))
        elif rm:
            res = do_read(rm.group(1), rm.group(2) or "")
            msgs.append(("user", "read 结果:\n" + res))
        else:
            msgs.append(("user", "请发 GREP: / READ: / CONFIG:"))
    print("\n========== opus 最终配置 ==========", flush=True)
    print(config or "(未产出 CONFIG)", flush=True)
    if config:
        low = config.lower()
        print("\n=== 完整性 ===", flush=True)
        for k in ["sdns on", "host name", "service ip", "pool name", "pool service",
                  "host pool", "pool method", "rr", "listener"]:
            print(f"  {k}: " + ("有" if k in low else "缺!"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
