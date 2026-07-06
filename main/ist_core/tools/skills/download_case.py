"""download_agile_case: 从 Agile 平台下载测试用例脑图 JSON。

两种调用方式:
  - 给 case_id(数字) → 直接调 get_case_data/ 拉脑图
  - 给 suite_name + --name → 调 select_case_set/ 拿列表 → 按名字匹配 → 调 get_case_data/

账号密码自动登录 → JWT → 调数据接口 → 落盘。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests
from langchain_core.tools import tool

# 脚本独立跑也要加载项目根 environment 文件(AGILE_LOGIN_USER/PASS 等)
try:
    from main.langchain_env import langchain_load_dotenv_if_present
    langchain_load_dotenv_if_present()
except ImportError:
    pass

_PROJECT_ROOT = Path(__file__).resolve().parents[4]

# 登录端点(OAuth 服务,同 10.4.150.56 主机 8032 端口)
_DEFAULT_LOGIN_URL = "http://10.4.150.56:8032/oauth/login/"
# 用例集列表接口(主页选用例集时调,8004 端口)
_DEFAULT_SELECT_URL = "http://10.4.150.56:8004/agile/select_case_set/"
# 数据接口(8004 端口)
_DEFAULT_API_URL = "http://10.4.150.56:8004/agile/get_case_data/"
_DEFAULT_OUTPUT_DIR = _PROJECT_ROOT / "workspace" / "inputs" / "yzg"
_DEFAULT_TOKEN_FIELD = "data.token"

# 账号密码从 environment 文件读取(AGILE_LOGIN_USER / AGILE_LOGIN_PASS)。
# 源码不再存凭据;环境变量在 main/langchain_env.py dotenv loader 启动时注入。

# case_set 列表项里"名字"的候选字段名(从 select_case_set 响应里取名时遍历这几个)
_NAME_KEYS = ("name", "title", "case_set_name", "text", "label")
# case_set 列表项里"id"的候选字段名
_ID_KEYS = ("id", "case_set_id", "case_id", "biz_id")
# biz_id 可选(限定到具体项目/业务);留空时 select_case_set 用后端默认上下文
_DEFAULT_BIZ_ID = ""


def _err(status: str, error: str, **extra: object) -> str:
    payload: dict[str, object] = {"status": status, "error": error}
    payload.update(extra)
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _sha512_base64(password: str) -> str:
    """Agile 前端约定:密码 SHA-512 哈希后 base64 编码。

    见 login.3a7f70b5.js: ``password = SHA512(password).toString(Base64)``
    """
    return base64.b64encode(hashlib.sha512(password.encode("utf-8")).digest()).decode("ascii")


def _login_and_get_token(
    user: str, password: str, login_url: str, token_field: str,
    skip_verify: bool = False,
) -> tuple[str | None, str | None]:
    """账号密码登录拿 JWT,返回 (token, error)。"""
    payload = {"username": user, "password": _sha512_base64(password)}
    try:
        resp = requests.post(
            login_url, json=payload,
            timeout=30, verify=not skip_verify,
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        return None, f"登录请求失败: {type(exc).__name__}: {exc}"

    try:
        result = resp.json()
    except json.JSONDecodeError as exc:
        return None, f"登录响应非 JSON: {exc}\n响应体前 300: {resp.text[:300]}"

    cur = result
    for key in token_field.split("."):
        if not isinstance(cur, dict):
            return None, (
                f"路径 {token_field!r} 中途不是 dict,响应: "
                f"{json.dumps(result, ensure_ascii=False)[:300]}"
            )
        if key not in cur:
            return None, (
                f"路径 {token_field!r} 不存在,响应: "
                f"{json.dumps(result, ensure_ascii=False)[:300]}"
            )
        cur = cur[key]
    if not isinstance(cur, str):
        return None, f"字段 {token_field!r} 不是字符串: {cur!r}"
    return cur, None


def _debug_login_request(
    user: str, password: str, login_url: str, skip_verify: bool = False,
) -> dict:
    payload = {"username": user, "password": _sha512_base64(password)}
    masked = {**payload, "password": f"***SHA512({len(payload['password'])} chars)***"}
    try:
        resp = requests.post(
            login_url, json=payload,
            timeout=30, verify=not skip_verify,
        )
        body_json: object
        try:
            body_json = resp.json()
        except Exception:
            body_json = None
        return {
            "status": "ok",
            "url": login_url,
            "request_body": masked,
            "response_status": resp.status_code,
            "response_headers": dict(resp.headers),
            "response_body_preview": resp.text[:1500],
            "response_body_json": body_json,
        }
    except Exception as exc:
        return {
            "status": "error", "url": login_url,
            "request_body": masked,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _list_case_sets(
    token: str, select_url: str, biz_id: str = "", title: str = "",
    page_size: int = 100, max_pages: int = 50, skip_verify: bool = False,
) -> tuple[list, str | None]:
    """调 select_case_set/ 拿用例集列表,支持按 title 关键字搜索 + 翻页。

    Payload 形态(从用户抓的 cURL 校准):
        {"biz_id": ..., "page": N, "title": "...", "creator": "", "page_size": ...}

    行为:
        - 不传 title:拉第一页(可能不全;调试用)
        - 传 title:按关键字搜索,后端只返匹配项,循环翻页直到空 / 不到 page_size

    返回: (all_cases_list, error) — list 累积所有页的项
    """
    headers = {
        "Authorization": token,
        "Content-Type": "application/json;charset=UTF-8",
    }
    all_cases: list = []
    for page in range(1, max_pages + 1):
        payload: dict[str, Any] = {
            "page": page,
            "creator": "",
            "page_size": page_size,
        }
        if biz_id:
            payload["biz_id"] = biz_id
        if title:
            payload["title"] = title

        try:
            resp = requests.post(
                select_url, headers=headers, json=payload,
                timeout=30, verify=not skip_verify,
            )
            resp.raise_for_status()
            result = resp.json()
        except requests.exceptions.RequestException as exc:
            return None, f"select_case_set 请求失败: {type(exc).__name__}: {exc}"
        except json.JSONDecodeError as exc:
            return None, f"select_case_set 响应非 JSON: {exc}"

        code = result.get("code") if isinstance(result, dict) else None
        if code is not None and code != 1000:
            return None, f"select_case_set 返回错误: code={code}, msg={result.get('msg')}"

        data = result.get("data") if isinstance(result, dict) else result
        cases = _extract_case_list(data)
        if not cases:
            break
        all_cases.extend(cases)
        if not title or len(cases) < page_size:
            # 列表模式只拿第一页;搜索模式如果本页 < page_size = 最后一页
            break
    return all_cases, None


def _extract_case_list(data: Any) -> list[dict]:
    """从 select_case_set 响应的 data 里抽 list[dict](尽力猜测,可能返回空列表)。"""
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("cases", "case_sets", "items", "results", "data", "list"):
            v = data.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
            if isinstance(v, dict):
                # 嵌套再找一层
                nested = _extract_case_list(v)
                if nested:
                    return nested
    return []


def _normalize(s: str) -> str:
    """用于模糊匹配:去空格、连字符、制表符、中英文标点,统一小写。"""
    if not isinstance(s, str):
        return ""
    drop = " \t\r\n-_‐‑‒–—―()()【】[]、，。.,;:;!?！?/\\|·"
    out = s.lower()
    for ch in drop:
        out = out.replace(ch, "")
    return out


def _find_case_by_name(case_list: list[dict], suite_name: str) -> tuple[dict | None, str]:
    """在 case_set 列表里找名字匹配的项,返回 (case_dict, match_type)。

    match_type ∈ {exact, normalized_exact, contains, not_found}
    """
    if not case_list:
        return None, "empty_list"

    target = suite_name.strip()
    target_norm = _normalize(target)

    # 1. 精确匹配
    for cs in case_list:
        for k in _NAME_KEYS:
            v = cs.get(k)
            if isinstance(v, str) and v.strip() == target:
                return cs, "exact"

    # 2. 归一化精确(忽略空格/连字符/标点/大小写)
    for cs in case_list:
        for k in _NAME_KEYS:
            v = cs.get(k)
            if isinstance(v, str) and _normalize(v) == target_norm:
                return cs, "normalized_exact"

    # 3. 包含匹配(归一化后 target 是 cs 名子串,或反之)
    for cs in case_list:
        for k in _NAME_KEYS:
            v = cs.get(k)
            if isinstance(v, str):
                v_norm = _normalize(v)
                if target_norm and (target_norm in v_norm or v_norm in target_norm):
                    return cs, "contains"

    return None, "not_found"


def _extract_case_id(case: dict) -> int | None:
    """从 case dict 里尝试抽 id(兼容多种字段名)。"""
    for k in _ID_KEYS:
        v = case.get(k)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
    return None


def _debug_list(token: str, select_url: str, biz_id: str, title: str = "") -> dict:
    """调试用:登录 + 调 select_case_set 看响应结构。"""
    case_list, err = _list_case_sets(token, select_url, biz_id=biz_id, title=title)
    if err:
        return {"status": "error", "error": err}
    return {
        "status": "ok",
        "url": select_url,
        "biz_id": biz_id,
        "title": title,
        "count": len(case_list),
        "first_5": [
            {"id": _extract_case_id(c),
             "name": next((c[k] for k in _NAME_KEYS if isinstance(c.get(k), str)), None)}
            for c in case_list[:5]
        ],
    }


@tool
def download_agile_case(
    case_id: int = 0,
    suite_name: str = "",
    biz_id: str = "",
    user: str = "",
    password: str = "",
    api_url: str = "",
    login_url: str = "",
    select_url: str = "",
    output_dir: str = "",
) -> str:
    """从 Agile 平台下载测试用例脑图 JSON,落盘到 workspace/inputs/yzg/。

    两种调用方式(二选一):
      - case_id(数字):直接调 get_case_data/({id: case_id})
      - suite_name(字符串):先调 select_case_set/ 拿列表,按名字匹配 → 拿 id → 调 get_case_data/

    账号密码读取顺序:显式参数 > AGILE_LOGIN_USER/PASS env > 源码 _TEMP_USER/PASS 临时值。

    可选 env:
        AGILE_LOGIN_URL    — 登录端点(默认 http://10.4.150.56:8032/oauth/login/)
        AGILE_SELECT_URL   — 列表接口(默认 .../agile/select_case_set/)
        AGILE_API_URL      — 数据接口(默认 .../agile/get_case_data/)
        AGILE_TOKEN_FIELD  — 登录响应 token dotpath(默认 data.token)
        AGILE_OUTPUT_DIR   — 产物落盘目录

    Args:
        case_id: 用例集 ID(二选一)。为 0 时忽略。
        suite_name: 用例集名称(二选一)。非空时优先按名字查 ID。
        biz_id: select_case_set 的 biz_id 参数(可选,后端如不接受空就传)。
        user/password/api_url/login_url/select_url/output_dir: 覆盖默认值。

    Returns:
        JSON 字符串,含 status / suite_name / output_file / matched_as(若走 suite_name)。
    """
    user = user or os.getenv("AGILE_LOGIN_USER", "").strip()
    password = password or os.getenv("AGILE_LOGIN_PASS", "").strip()
    url = api_url or os.getenv("AGILE_API_URL", "").strip() or _DEFAULT_API_URL
    login_url = login_url or os.getenv("AGILE_LOGIN_URL", "").strip() or _DEFAULT_LOGIN_URL
    select_url = select_url or os.getenv("AGILE_SELECT_URL", "").strip() or _DEFAULT_SELECT_URL
    token_field = (
        os.getenv("AGILE_TOKEN_FIELD", "").strip() or _DEFAULT_TOKEN_FIELD
    )
    biz_id = biz_id or os.getenv("AGILE_BIZ_ID", "").strip()
    out_root = Path(output_dir) if output_dir else Path(
        os.getenv("AGILE_OUTPUT_DIR", "").strip() or str(_DEFAULT_OUTPUT_DIR)
    )
    if not out_root.is_absolute():
        out_root = (_PROJECT_ROOT / out_root).resolve()

    # 1. 登录
    token, err = _login_and_get_token(user, password, login_url, token_field)
    if err:
        return _err("error", err,
                    hint="用 --debug-login 探明登录响应。")

    # 2. 决定 case_id
    target_case_id = case_id
    matched_as = None
    final_suite_name = None

    if suite_name:
        # 按 title 关键字搜索(后端只返匹配项,翻页兜底)。biz_id 可选,留空时走后端默认上下文。
        case_list, err = _list_case_sets(
            token, select_url, biz_id=biz_id, title=suite_name,
        )
        if err:
            return _err("error", err,
                        hint="若后端要 biz_id 才能拿到数据,加 AGILE_BIZ_ID env 或 --biz-id 传具体值。")
        case_dict, match_type = _find_case_by_name(case_list, suite_name)
        if not case_dict:
            # 失败时把整个列表(含 id + name)吐出来,用户肉眼能直接定位
            all_items = [
                {
                    "id": _extract_case_id(c),
                    "name": next(
                        (c[k] for k in _NAME_KEYS if isinstance(c.get(k), str)),
                        None,
                    ),
                }
                for c in case_list
            ]
            return _err("error",
                        f"suite_name={suite_name!r} 没在列表里找到(共 {len(case_list)} 项,match={match_type})",
                        all_items=all_items,
                        hint="从 all_items 找 id=<你想要的>,直接用 case_id 模式跑:download_case <id>")
        target_case_id = _extract_case_id(case_dict)
        if not target_case_id:
            return _err("error",
                        f"找到匹配的 case 但没有 id 字段: {case_dict}",
                        hint="联系开发或贴 case_dict 给我调 id 字段名。")
        matched_as = match_type
        for k in ("name", "title", "case_set_name", "text"):
            v = case_dict.get(k)
            if isinstance(v, str):
                final_suite_name = v
                break

    if not target_case_id:
        return _err("error", "case_id 和 suite_name 至少传一个")

    # 3. 调 get_case_data 拉脑图
    headers = {
        "Authorization": token,
        "Content-Type": "application/json;charset=UTF-8",
        "Accept": "application/json, text/plain, */*",
    }
    payload = {"id": target_case_id}

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        api_result = resp.json()
    except requests.exceptions.ConnectionError:
        return _err("error", f"无法连接 Agile API: {url}",
                    hint="请确认网络可访问 10.4.150.56:8004。")
    except requests.exceptions.Timeout:
        return _err("error", "Agile API 请求超时(30s)")
    except requests.exceptions.HTTPError as exc:
        return _err("error", f"HTTP {exc.response.status_code}: {exc.response.reason}",
                    body_preview=resp.text[:300],
                    hint="多半是 JWT 过期或 case_id 不存在。")
    except requests.exceptions.JSONDecodeError as exc:
        return _err("error", f"响应非 JSON: {exc}")
    except requests.exceptions.RequestException as exc:
        return _err("error", f"请求失败: {type(exc).__name__}: {exc}")

    if api_result.get("code") != 1000:
        return _err("error", f"API 返回错误: code={api_result.get('code')}, msg={api_result.get('msg')}")

    brain_map_raw = api_result.get("data", "")
    if not brain_map_raw:
        return _err("error", "API 返回的 data 字段为空")

    try:
        brain_map = json.loads(brain_map_raw)
    except json.JSONDecodeError as exc:
        return _err("error", f"脑图 JSON 解析失败: {exc}",
                    raw_preview=brain_map_raw[:200])

    root = brain_map.get("root", {})
    root_data_text = ""
    if isinstance(root, dict):
        root_data_text = root.get("data", {}).get("text", "")

    root_text = final_suite_name or root_data_text
    brain_map_text = (
        json.dumps([root], indent=2, ensure_ascii=False)
        if isinstance(root, dict) else brain_map_raw
    )

    safe_name = root_text.replace(" ", "_").replace("/", "_")[:50] if root_text else f"agile_{target_case_id}"
    out_root.mkdir(parents=True, exist_ok=True)
    output_path = out_root / f"{safe_name}.txt"
    output_path.write_text(brain_map_text, encoding="utf-8")

    return _err(
        "success", "",
        case_id=target_case_id,
        suite_name=root_text,
        matched_as=matched_as,
        output_file=str(output_path.relative_to(_PROJECT_ROOT)),
        hint=f"已保存到 {output_path}",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="从 Agile 平台下载脑图 JSON(账号密码自动登录)",
    )
    parser.add_argument("target", nargs="?",
                       help="用例集 ID(数字)或 suite_name(--name 时为后者)")
    parser.add_argument("--name", action="store_true",
                       help="把 target 当 suite_name 解析(默认当 case_id)")
    parser.add_argument("--biz-id", default="",
                       help="select_case_set 的 biz_id 参数(默认 1571,改 AGILE_BIZ_ID env)")
    parser.add_argument("--title", default="",
                       help="--debug-list 时用:按 title 关键字搜索(等同于 suite_name 模式)")
    parser.add_argument("--debug-login", action="store_true",
                       help="调试模式:用账号密码登录一次,打印诊断")
    parser.add_argument("--debug-list", action="store_true",
                       help="调试模式:登录 + 调 select_case_set,看响应结构")
    args = parser.parse_args()

    if args.debug_login:
        user = os.getenv("AGILE_LOGIN_USER", "").strip()
        password = os.getenv("AGILE_LOGIN_PASS", "").strip()
        login_url = os.getenv("AGILE_LOGIN_URL", "").strip() or _DEFAULT_LOGIN_URL
        print(json.dumps(
            _debug_login_request(user, password, login_url),
            indent=2, ensure_ascii=False,
        ))
        sys.exit(0)

    if args.debug_list:
        user = os.getenv("AGILE_LOGIN_USER", "").strip() or _TEMP_USER
        password = os.getenv("AGILE_LOGIN_PASS", "").strip() or _TEMP_PASS
        login_url = os.getenv("AGILE_LOGIN_URL", "").strip() or _DEFAULT_LOGIN_URL
        select_url = os.getenv("AGILE_SELECT_URL", "").strip() or _DEFAULT_SELECT_URL
        token, err = _login_and_get_token(user, password, login_url, _DEFAULT_TOKEN_FIELD)
        if err:
            print(json.dumps({"status": "error", "stage": "login", "error": err},
                            indent=2, ensure_ascii=False))
            sys.exit(1)
        biz_id = args.biz_id or os.getenv("AGILE_BIZ_ID", "").strip() or _DEFAULT_BIZ_ID
        print(json.dumps(
            _debug_list(token, select_url, biz_id, title=args.title),
            indent=2, ensure_ascii=False,
        ))
        sys.exit(0)

    if not args.target:
        parser.print_help()
        sys.exit(1)

    if args.name:
        result = download_agile_case.invoke({
            "suite_name": args.target,
            "biz_id": args.biz_id,
        })
    else:
        try:
            cid = int(args.target)
        except ValueError:
            print(f"错误: 不带 --name 时 target 必须是数字 ID,收到 {args.target!r}",
                  file=sys.stderr)
            sys.exit(2)
        result = download_agile_case.invoke({"case_id": cid})
    print(result)