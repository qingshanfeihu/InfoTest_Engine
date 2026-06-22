"""实验:启用 footprint + 加通用装配纪律(总开关/顺序/引用一致),看 opus 能否产对配置。

判定失败是"不懂装配纪律(可通用 prompt 教)"还是"知识不够(教不会)"。
纪律是通用原则(enable/order/ref-consistency),不写死任何 sdns 具体命令(红线内)。
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
        "组装配置时严格遵守这几条通用装配纪律(自检):\n"
        "1. 功能总开关:先开启该功能的总开关——没开,后面配了也不生效。\n"
        "2. 先后顺序:被引用的对象必须先创建再被引用(先建池、建服务,再做绑定;先建监听器)。\n"
        "3. 参数相互引用一致:绑定命令里引用的名字,必须和前面创建时用的名字逐字一致"
        "(host 绑的 pool 名 = 建 pool 时的名;pool 引的 service 名 = 建 service 时的名)。\n"
        "4. 逐条自检:每个你定义的对象,后面有没有把它接入解析链?每个你引用的名字,前面有没有创建?"
        "只定义不接入、或引用了没建的名字 = 配置不完整 = 设备不解析。"
    )
    m = build_agent_chat_model(model=ist_core_tier_model("opus"))
    prompt = (
        "你是 APV SDNS 测试工程师。下面是 footprint(命令签名 + 决策规则):\n" + fpctx +
        "\n\n" + discipline +
        "\n\n任务:配置使域名 autotest.com 通过 rr(轮询)算法解析到后端 172.16.35.231,"
        "监听器 IP 172.16.34.70,使 dig @172.16.34.70 autotest.com 能解析出 172.16.35.231。"
        "只输出完整 CLI 配置(每行一条),不解释。"
    )
    r = m.invoke(prompt)
    out = str(getattr(r, "content", r))
    cfg = out.split("```")[1] if "```" in out else out
    cfg = re.sub(r"^(cli|bash|text)\n", "", cfg.strip(), flags=re.I)
    print("=== opus(footprint+纪律) 产出 ===")
    print(cfg[:800])
    low = cfg.lower()
    print("\n=== 完整性 ===")
    for k in ["sdns on", "host name", "service ip", "pool name", "pool service",
              "host pool", "pool method", "rr", "listener"]:
        print(f"  {k}: " + ("有" if k in low else "缺!"))

    from main.ist_core.tools.device.emit_xlsx_tool import qa_emit_xlsx
    from main.ist_core.tools.device.run_case import qa_run_case
    lines = [l.strip() for l in cfg.split("\n") if l.strip() and l.strip().lower().startswith(("sdns", "no "))]
    steps = [{"E": "APV_0", "F": "cmds_config", "G": "\n".join(lines)},
             {"E": "APV_0", "F": "cmd_config", "G": "show sdns listener"},
             {"E": "check_point", "F": "found", "G": "172.16.34.70"},
             {"E": "test_env", "F": "routera", "G": "dig @172.16.34.70 autotest.com"},
             {"E": "check_point", "F": "found", "G": "172.16.35.231"}]
    qa_emit_xlsx.invoke({"autoid": "888disc", "steps_json": json.dumps(steps),
                         "init_commands": "", "out_name": "opus_disc_test"})
    o = qa_run_case.invoke({"xlsx_path": "workspace/outputs/opus_disc_test/case.xlsx", "autoid": "888disc"})
    v = re.search(r"verdict: (\w+)", o)
    caus = [l.strip()[:90] for l in o.splitlines() if "Num" in l or "172.16.35.231" in l]
    print("\n=== 上机 verdict:", v.group(1) if v else "?", "===")
    for l in caus[:6]:
        print("  " + l)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
