"""验证:haiku(快模型) + 修好的 footprint(带回总开关) + 装配纪律,能否产出完整正确、上机通过的配置。

对了 → 又快又对,pipeline 可用 haiku。
"""
import json
import re

from main.langchain_env import langchain_load_dotenv_if_present


def main():
    langchain_load_dotenv_if_present()
    from main.ist_core.tools.knowledge.footprint_lookup import qa_footprint_lookup
    from main.ist_core.agents._llm import build_agent_chat_model, ist_core_tier_model

    fp = []
    for cmd in ["sdns on", "sdns host", "sdns pool", "sdns service ip", "sdns listener"]:
        try:
            fp.append(qa_footprint_lookup.invoke({"command": cmd}))
        except Exception as ex:
            fp.append(f"({cmd}: {ex})")
    fpctx = "\n\n".join(fp)[:6000]

    discipline = (
        "组装配置时严格遵守通用装配纪律(自检):\n"
        "1. 功能总开关:先开启该功能的总开关(footprint 已标'模块总开关')——没开后面配了也不生效。\n"
        "2. 先后顺序:被引用对象必须先创建再被引用(先建池/服务,再绑定;先建监听器)。\n"
        "3. 参数引用一致:绑定命令里引用的名字必须和创建时逐字一致。\n"
        "4. 逐条自检:每个定义的对象后面有没有接入解析链(host↔pool、pool↔service 的绑定步绝不能漏)?"
        "每个引用的名字前面有没有创建?只定义不绑定 = 配置不完整 = 设备不解析。"
    )
    m = build_agent_chat_model(model=ist_core_tier_model("haiku"))
    prompt = (
        "你是 APV SDNS 测试工程师。下面是 footprint(命令签名 + 规则 + 模块总开关):\n" + fpctx +
        "\n\n" + discipline +
        "\n\n任务:配置使域名 autotest.com 通过 rr(轮询)算法解析到后端 172.16.35.231,"
        "监听器 IP 172.16.34.70,使 dig @172.16.34.70 autotest.com 能解析出 172.16.35.231。"
        "只输出完整 CLI 配置(每行一条),不解释。"
    )
    out = str(getattr(m.invoke(prompt), "content", ""))
    cfg = out.split("```")[1] if "```" in out else out
    cfg = re.sub(r"^(cli|bash|text)\n", "", cfg.strip(), flags=re.I)
    print("=== haiku(footprint修复+纪律) 产出 ===")
    print(cfg[:700])
    low = cfg.lower()
    print("=== 完整性 ===")
    for k in ["sdns on", "host name", "service ip", "pool name", "pool service",
              "host pool", "rr", "listener"]:
        print(f"  {k}: " + ("有" if k in low else "缺!"))

    from main.ist_core.tools.device.emit_xlsx_tool import qa_emit_xlsx
    from main.case_compiler.device_mcp_client import FrameworkMCPClient
    from main.case_compiler.config import get_config
    lines = [l.strip() for l in cfg.split("\n") if l.strip().lower().startswith(("sdns", "no "))]
    steps = [{"E": "APV_0", "F": "cmds_config", "G": "\n".join(lines)},
             {"E": "APV_0", "F": "cmd_config", "G": "show sdns listener"},
             {"E": "check_point", "F": "found", "G": "172.16.34.70"},
             {"E": "test_env", "F": "routera", "G": "dig @172.16.34.70 autotest.com"},
             {"E": "check_point", "F": "found", "G": "172.16.35.231"}]
    qa_emit_xlsx.invoke({"autoid": "203699000002", "steps_json": json.dumps(steps),
                         "init_commands": "", "out_name": "haiku_disc"})
    cfgc = get_config()
    with FrameworkMCPClient() as c:
        c.deliver(cfgc.staging_module, "203699000002", "workspace/outputs/haiku_disc/case.xlsx")
        run = c.run_and_wait(cfgc.staging_module, "203699000002", cfgc.build, ["203699000002"], max_s=120)
        v = (run.get("results") or {}).get("203699000002") or run.get("result") or run.get("error")
        d = c.fetch_case_detail("203699000002", max_chars=2500)
    print("\n=== 上机 verdict:", v, "| pymysql崩:", "execute() first" in d, "===")
    for l in [x.strip()[:75] for x in d.splitlines() if "Num" in x or "172.16.35.231" in x][:4]:
        print("  " + l)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
