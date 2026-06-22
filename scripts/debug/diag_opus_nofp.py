"""测:纯装配纪律、不给 footprint,opus 靠自身知识能产出什么 SDNS rr 配置。

判定 footprint 价值:无 footprint 更差=footprint 提供命令词汇;一样=opus 自带够。
"""
import json
import re

from main.langchain_env import langchain_load_dotenv_if_present


def main():
    langchain_load_dotenv_if_present()
    from main.ist_core.agents._llm import build_agent_chat_model, ist_core_tier_model

    disc = ("组装配置时严格遵守通用装配纪律:"
            "1.功能总开关:先开启该功能的总开关——没开后面配了也不生效。"
            "2.先后顺序:被引用对象必须先创建再被引用(先建池/服务,再绑定;先建监听器)。"
            "3.参数引用一致:绑定命令里引用的名字必须和创建时逐字一致。"
            "4.逐条自检:每个定义的对象后面有没有接入解析链?每个引用的名字前面有没有创建?")
    m = build_agent_chat_model(model=ist_core_tier_model("opus"))
    prompt = ("你是 APV SDNS 测试工程师。" + disc +
              " 任务:配置使域名 autotest.com 通过 rr(轮询)算法解析到后端 172.16.35.231,"
              "监听器 IP 172.16.34.70,使 dig @172.16.34.70 autotest.com 能解析出 172.16.35.231。"
              "只输出完整 CLI 配置(每行一条),不解释。")
    out = str(getattr(m.invoke(prompt), "content", ""))
    cfg = out.split("```")[1] if "```" in out else out
    cfg = re.sub(r"^(cli|bash|text)\n", "", cfg.strip(), flags=re.I)
    print("=== opus(纯纪律,无footprint) 产出 ===")
    print(cfg[:700])
    low = cfg.lower()
    print("=== 完整性 ===")
    for k in ["sdns on", "host name", "service ip", "pool name", "pool service",
              "host pool", "pool method", "rr", "listener"]:
        print(f"  {k}: " + ("有" if k in low else "缺!"))

    from main.ist_core.tools.device.emit_xlsx_tool import qa_emit_xlsx
    from main.ist_core.tools.device.run_case import qa_run_case
    lines = [l.strip() for l in cfg.split("\n") if l.strip().lower().startswith(("sdns", "no "))]
    steps = [{"E": "APV_0", "F": "cmds_config", "G": "\n".join(lines)},
             {"E": "APV_0", "F": "cmd_config", "G": "show sdns listener"},
             {"E": "check_point", "F": "found", "G": "172.16.34.70"},
             {"E": "test_env", "F": "routera", "G": "dig @172.16.34.70 autotest.com"},
             {"E": "check_point", "F": "found", "G": "172.16.35.231"}]
    qa_emit_xlsx.invoke({"autoid": "888nofp", "steps_json": json.dumps(steps),
                         "init_commands": "", "out_name": "opus_nofp"})
    o = qa_run_case.invoke({"xlsx_path": "workspace/outputs/opus_nofp/case.xlsx", "autoid": "888nofp"})
    v = re.search(r"verdict: (\w+)", o)
    print("=== 上机 verdict:", v.group(1) if v else "?", "===")
    for l in [x.strip()[:90] for x in o.splitlines() if "Num" in x or "172.16.35.231" in x][:5]:
        print("  " + l)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
