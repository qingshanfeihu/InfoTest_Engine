"""V3 编译驱动：对一个脑图直接调确定性流水线 compile_pipeline（不经主 agent，免编排 churn）。

产出 workspace/outputs/<out_name>/case.xlsx——含 draft 诚实留空的 <RUNTIME> 槽位（不可知期望值）。
上机回填走 ist_verify（另起）。

用法：python -m scripts.debug.run_v3_compile <mindmap.txt> <version> [out_name]
"""
import sys
import time

from main.langchain_env import langchain_load_dotenv_if_present


def main():
    langchain_load_dotenv_if_present()
    if len(sys.argv) < 3:
        print("用法: run_v3_compile <mindmap.txt> <version> [out_name]")
        return 2
    mindmap, version = sys.argv[1], sys.argv[2]
    out_name = sys.argv[3] if len(sys.argv) > 3 else ""
    from main.ist_core.tools.device.compile_pipeline import compile_pipeline

    t0 = time.time()
    print(f"[compile] mindmap={mindmap} version={version} out_name={out_name or '(默认脑图名)'}", flush=True)
    out = compile_pipeline.invoke(
        {"mindmap_path": mindmap, "product_version": version, "out_name": out_name})
    print(out, flush=True)
    print(f"[compile] 耗时 {time.time()-t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
