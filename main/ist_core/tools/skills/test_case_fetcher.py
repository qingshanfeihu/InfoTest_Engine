"""qa_fetch_test_cases: 从 Agile 平台拉取测试用例脑图 JSON。

通过网络 API 直接从 Agile 平台获取用例套件的脑图数据，跳过手动导出步骤。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import requests
from langchain_core.tools import tool

_PROJECT_ROOT = Path(__file__).resolve().parents[4]

# 默认 API 地址（可通过 AGILE_API_URL 覆盖）
_DEFAULT_API_URL = "https://portal.infosec.com.cn/prx/000/http/10.4.150.56:8004/agile/get_case_data/"
# 默认 token（可通过 AGILE_AUTH_TOKEN 覆盖；过期后从浏览器 F12 → Network 重新获取）
_DEFAULT_AUTH_TOKEN = (
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9."
    "eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzgyODkyNjEwLCJpYXQiOjE3ODAzMDA2MTAsImp0aSI6ImNlODQ5YTJlYm"
    "VjNjRiNWFiZmE0ZDMxYzJhMDk1MmI4IiwidXNlcl9pZCI6ImNjYzBmZTU4Y2Y2NzQxYTlhZmU4NmM2ZjU1M2YxMDU0IiwidXNlcm"
     "5hbWUiOiJ5dXpoaWdhbmciLCJuaWNrbmFtZSI6Ilx1NGU4ZVx1NWZkN1x1NmUyZiIsImVtYWlsIjoieXV6Z0BhcnJheW5ldHdvcm"
     "tzLmNvbS5jbiIsIm1vYmlsZSI6IjE4NzM1NDY2NDcxIiwicm9sZV9uYW1lIjoiXHU2NjZlXHU5MDFhXHU3NTI4XHU2MjM3IiwicG"
      "9zdF9uYW1lIjoiXHU2ZDRiXHU4YmQ1XHU1ZGU1XHU3YTBiXHU1ZTA4IiwicG9zdF9jb2RlIjoiUUEiLCJkZXB0X25hbWUiOiJcdT"
       "RlYTdcdTU0YzFcdTZkNGJcdThiZDVcdTRlMDlcdTkwZTgiLCJhdmF0YXIiOiJsaWJzL29hdXRoL2F2YXRhci85ZDcyM2ZlMmU3ZD"
        "c0ZjFhYjE2NzFiOWYxODgzY2U1ZS5wbmciLCJ1c2VySWQiOiJjY2MwZmU1OGNmNjc0MWE5YWZlODZjNmY1NTNmMTA1NCJ9."
        "tQkhDGm7RcMGBgdcumN1G7ACnhL0yQHV7XC55YGq8PM"
)
# 默认 cookie — nginx 代理需要 cookie 才能放行（可通过 AGILE_COOKIES 覆盖）
_DEFAULT_COOKIES = (
    "AN_nav1=1%3dopen%262%3dbuttons%263%3dright%264%3dclosed%265%3d37099aaf%26eoc; "
    "ANsession0005012657143474=menhu+37099aaf_f6c7d3bed1dbd010b2b47e36a1a33573; "
    "username=yuzhigang; "
    "role_names=all"
)


@tool
def qa_fetch_test_cases(case_id: int, api_url: str = "", auth_token: str = "") -> str:
    """从 Agile 平台拉取测试用例脑图 JSON。

    通过 ID 直接从 Agile 平台获取用例套件的完整脑图数据（与手动导出的 .txt
    格式完全一致），拉取后可直接用 qa_extract_test_cases 进行提取。

    使用前需设置环境变量：
        AGILE_AUTH_TOKEN — JWT token（从浏览器 F12 → Network → 请求头中获取）
        AGILE_API_URL    — 可选，覆盖默认 API 地址

    Args:
        case_id: 用例套件 ID。从 Agile 页面 URL 的 query 参数解密后得到，
            或从 Network 请求的 request body 中查看 `{"id": 23099}`。
        api_url: 可选，覆盖默认 API 地址。
        auth_token: 可选，覆盖环境变量 AGILE_AUTH_TOKEN。

    Returns:
        JSON 字符串，含 status 和 brain_map_text（可直接写入 .txt 文件）。
    """
    url = api_url or os.getenv("AGILE_API_URL", _DEFAULT_API_URL)
    token = auth_token or os.getenv("AGILE_AUTH_TOKEN", "") or _DEFAULT_AUTH_TOKEN
    cookies = os.getenv("AGILE_COOKIES", "") or _DEFAULT_COOKIES

    if not token:
        return json.dumps({
            "status": "error",
            "error": "AGILE_AUTH_TOKEN 未设置。请设置环境变量或在参数中传入 JWT token。",
            "hint": "浏览器 F12 → Network → 找到 /agile/get_case_data/ 请求 → "
                    "复制 Authorization 头的值（Bearer 后面的部分，或完整 JWT）。",
        }, indent=2, ensure_ascii=False)

    headers = {
        "Authorization": token if token.startswith("eyJ") else f"Bearer {token}",
        "Content-Type": "application/json;charset=utf-8",
        "Accept": "application/json, text/plain, */*",
    }
    payload = {"id": case_id}

    try:
        # 解析 cookie 字符串为 dict
        cookie_dict = {}
        for c in cookies.split(";"):
            c = c.strip()
            if "=" in c:
                k, v = c.split("=", 1)
                cookie_dict[k.strip()] = v.strip()
        resp = requests.post(url, headers=headers, json=payload, cookies=cookie_dict, timeout=30, verify=False)
        resp.raise_for_status()
        api_result = resp.json()
    except requests.exceptions.ConnectionError:
        return json.dumps({
            "status": "error",
            "error": f"无法连接到 Agile API: {url}",
            "hint": "请确认在可访问 portal.infosec.com.cn 的网络环境中运行。",
        }, indent=2, ensure_ascii=False)
    except requests.exceptions.Timeout:
        return json.dumps({
            "status": "error",
            "error": "Agile API 请求超时（30s）",
        }, indent=2, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "error": f"请求失败: {exc}",
        }, indent=2, ensure_ascii=False)

    # API 返回格式: {"code": 1000, "msg": "...", "data": "<脑图 JSON 字符串>"}
    if api_result.get("code") != 1000:
        return json.dumps({
            "status": "error",
            "error": f"API 返回错误: code={api_result.get('code')}, msg={api_result.get('msg')}",
        }, indent=2, ensure_ascii=False)

    brain_map_raw = api_result.get("data", "")
    if not brain_map_raw:
        return json.dumps({
            "status": "error",
            "error": "API 返回的 data 字段为空",
        }, indent=2, ensure_ascii=False)

    # data 字段是 JSON 字符串，解析验证
    try:
        brain_map = json.loads(brain_map_raw)
    except json.JSONDecodeError as exc:
        return json.dumps({
            "status": "error",
            "error": f"脑图 JSON 解析失败: {exc}",
            "raw_preview": brain_map_raw[:200],
        }, indent=2, ensure_ascii=False)

    # 提取套件名称
    root_text = ""
    root = brain_map.get("root", {})
    if isinstance(root, dict):
        root_text = root.get("data", {}).get("text", "")

    # 转为与手动导出 .txt 一致的格式（JSON 数组）
    brain_map_text = json.dumps([root], indent=2, ensure_ascii=False) if root else brain_map_raw

    # 保存到 workspace/inputs/yzg/
    safe_name = root_text.replace(" ", "_").replace("/", "_")[:50] if root_text else f"agile_{case_id}"
    output_dir = _PROJECT_ROOT / "workspace" / "inputs" / "yzg"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{safe_name}.txt"
    output_path.write_text(brain_map_text, encoding="utf-8")

    return json.dumps({
        "status": "success",
        "case_id": case_id,
        "suite_name": root_text,
        "output_file": str(output_path.relative_to(_PROJECT_ROOT)),
        "hint": f"已保存到 {output_path}，可直接用 qa_extract_test_cases(file_path='{output_path.relative_to(_PROJECT_ROOT)}') 提取用例。",
    }, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python3 -m main.qa_agent.tools.skills.test_case_fetcher <case_id>")
        print("示例: python3 -m main.qa_agent.tools.skills.test_case_fetcher 23099")
        sys.exit(1)
    try:
        cid = int(sys.argv[1])
    except ValueError:
        print(f"错误: case_id 必须是数字，收到 {sys.argv[1]!r}")
        sys.exit(1)
    print(qa_fetch_test_cases.invoke({"case_id": cid}))
