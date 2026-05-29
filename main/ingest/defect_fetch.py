"""Stage 1：Playwright 抓取 Bugzilla / 禅道（ZenTao）HTML，落地到 knowledge/defect_raw/。

**v1.5.1 真实 WebVPN 对接**：登录 / 验证码 OCR / PLM 首页搜索跳转 已全部下沉到
``main/ingest/_capture_session.py``，本模块只做 **调度 + 本地落盘 + meta.jsonl**。

流程：

1. 启动 Chrome（优先 channel=chrome；回退 chromium）
2. 加载 ``PLAYWRIGHT_STATE_DIR/{backend}.storage.json`` 作为 ``storage_state``
3. goto 门户登录入口，用 ``ensure_portal_logged_in`` 自动填账号/密码/验证码
4. 若为 Bugzilla → 构造 ``[proxy_url, direct_url]`` 候选，``goto`` 详情页
   若为 ZenTao → ``open_plm_home`` → ``goto_bug_from_plm_home(bug_id)``
5. ``page.content()`` 落地到 ``knowledge/defect_raw/{backend}/{id}.html`` + meta 追加

用法::

    # 批量
    python -m main.ingest.defect_fetch --backend bugzilla --ids BUG-121100
    python -m main.ingest.defect_fetch --backend zentao --ids-file tickets.txt --resume

    # 首次登录（headful 手动点验证码也行；OCR 自动尝试）
    python -m main.ingest.defect_fetch --backend bugzilla --refresh-login
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


from main.knowledge_paths import KNOWLEDGE_INTERMEDIATE
RAW_ROOT = KNOWLEDGE_INTERMEDIATE / "defect_raw"
META_FILENAME = "meta.jsonl"

SUPPORTED_BACKENDS = ("bugzilla", "zentao", "zentao_story", "plm")


class LoginRequiredError(RuntimeError):
    """登录态失效，需要 headful 重登。"""


def _ensure_no_langsmith() -> None:
    os.environ["LANGSMITH_TRACING"] = "false"


def _canonical_backend(backend: str) -> str:
    b = (backend or "").strip().lower()
    if b == "plm":
        return "zentao"
    return b


def _state_path(backend: str) -> Path:
    b = _canonical_backend(backend)
    if b == "zentao_story":
        b = "zentao"
    root = Path(os.environ.get("PLAYWRIGHT_STATE_DIR") or str(KNOWLEDGE_INTERMEDIATE / "defect_raw" / "_state"))
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{b}.storage.json"


def _raw_dir(backend: str) -> Path:
    b = _canonical_backend(backend)
    if b == "zentao_story":
        b = "zentao"
    p = RAW_ROOT / b
    p.mkdir(parents=True, exist_ok=True)
    return p


def _probe_vpn() -> bool:
    """探测是否能访问门户（而不是内网直连 URL），因为内网直连在未登录 WebVPN 时必 fail。

    注意 ``verify=False``：portal.infosec.com.cn 用企业私有 CA 证书，httpx 默认
    ``verify=True`` 会立即抛 ``CERTIFICATE_VERIFY_FAILED``（与原 Playwright 脚本
    ``ignore_https_errors=True`` 行为对齐）。这里仅做"网络是否可达"探测，不做证书校验。

    用 GET 而非 HEAD：portal 对 HEAD 会回 malformed response（直接吐 HTML body 而非
    HTTP status line），httpx 抛 ``RemoteProtocolError``。GET 正常返回 200。
    """
    from main.ingest._capture_session import PORTAL_LOGIN_URLS

    for url in PORTAL_LOGIN_URLS:
        try:
            r = httpx.get(url, follow_redirects=True, timeout=5, verify=False)
            if r.status_code < 500:
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _load_ids(args: argparse.Namespace) -> list[str]:
    ids: list[str] = []
    if args.ids:
        ids.extend(s.strip() for s in args.ids.split(",") if s.strip())
    if args.ids_file:
        text = Path(args.ids_file).read_text(encoding="utf-8")
        ids.extend(s.strip() for s in text.splitlines() if s.strip() and not s.startswith("#"))
    return ids


def _resume_filter(ids: list[str], backend: str) -> list[str]:
    meta_path = _raw_dir(backend) / META_FILENAME
    done: set[str] = set()
    if meta_path.exists():
        for line in meta_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("http_status") and 200 <= row["http_status"] < 400:
                done.add(str(row.get("ticket_id") or ""))
    return [i for i in ids if i not in done]


def _append_meta(backend: str, row: dict[str, Any]) -> None:
    meta_path = _raw_dir(backend) / META_FILENAME
    with meta_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False))
        fh.write("\n")


def _refresh_login_ready(page, *, looks_like_login_page, wait_for_portal_ready) -> bool:
    if not looks_like_login_page(page):
        return True
    return wait_for_portal_ready(page, timeout_ms=5000)



def _complete_refresh_login(
    page,
    context,
    state_path: Path,
    *,
    logged_in: bool,
    headless: bool,
    looks_like_login_page,
    wait_for_portal_ready,
) -> int:
    if logged_in:
        print(f"✅ 登录态已保存到 {state_path}")
        return 1

    print("⚠️ 自动登录未成功；若 headful 下仍在登录页，请人工完成后按回车")
    if not headless:
        try:
            input()
        except EOFError:
            pass
        page.wait_for_timeout(1000)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:  # noqa: BLE001
            pass
        if _refresh_login_ready(
            page,
            looks_like_login_page=looks_like_login_page,
            wait_for_portal_ready=wait_for_portal_ready,
        ):
            context.storage_state(path=str(state_path))
            print(f"✅ 登录态已保存到 {state_path}")
            return 1

    raise LoginRequiredError(
        "refresh-login 未成功：浏览器仍停留在登录页或门户未就绪，请完成登录后重试"
    )







def _fetch_loop_sync(
    ids: list[str],
    backend: str,
    *,
    refresh_login_only: bool = False,
) -> int:
    """同步 Playwright；沿用 scripts/*_capture.py 的结构。"""
    try:
        from playwright.sync_api import (  # type: ignore[import-not-found]
            Error as PlaywrightError,
            TimeoutError as PlaywrightTimeoutError,
            sync_playwright,
        )
    except ImportError as exc:
        logger.error(
            "playwright 未安装。请运行：pip install playwright && python -m playwright install chromium"
        )
        raise SystemExit(4) from exc

    from main.ingest._capture_session import (
        build_bugzilla_detail_urls,
        ensure_portal_logged_in,
        find_bugzilla_page,
        get_portal_credentials,
        goto_bug_from_plm_home,
        goto_story_from_plm_home,
        looks_like_login_page,
        looks_like_sso_failure,
        open_plm_home,
        wait_for_portal_ready,
    )

    canonical = _canonical_backend(backend)
    state_path = _state_path(backend)
    headless = (os.environ.get("PLAYWRIGHT_HEADLESS") or "1").strip() != "0"
    
    if (os.environ.get("DEFECT_FETCH_DISPLAY") or "").strip() == "1":
        headless = False
    
    
    

    cred_prefix = "BUGZILLA" if canonical == "bugzilla" else "ZENDAO"
    user, password = get_portal_credentials(cred_prefix)
    if not user or not password:
        raise LoginRequiredError(
            f"缺少账号密码：请在 environment 里设置 {cred_prefix}_LOGIN_USER / {cred_prefix}_LOGIN_PASS "
            f"或 PORTAL_LOGIN_USER / PORTAL_LOGIN_PASS"
        )

    if not _probe_vpn():
        print("❌ 无法访问 WebVPN 门户（portal.infosec.com.cn），请确认 VPN / 网络", file=sys.stderr)
        raise SystemExit(3)

    ok_count = 0

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                headless=headless,
                channel="chrome",
                args=["--disable-popup-blocking"],
            )
            logger.info("使用 Chrome 通道启动 (headless=%s)", headless)
        except Exception:  # noqa: BLE001
            browser = p.chromium.launch(
                headless=headless,
                args=["--disable-popup-blocking"],
            )
            logger.info("Chrome 通道不可用，回退 Chromium (headless=%s)", headless)

        try:
            storage = str(state_path) if state_path.exists() else None
            context = browser.new_context(
                ignore_https_errors=True,
                storage_state=storage,
            )
            page = context.new_page()

            
            logged_in = ensure_portal_logged_in(
                page,
                context,
                user=user,
                password=password,
                state_path=state_path,
                debug_dir=_raw_dir(backend) / "captcha_debug",
                headless=headless,
            )

            if refresh_login_only:
                return _complete_refresh_login(
                    page,
                    context,
                    state_path,
                    logged_in=logged_in,
                    headless=headless,
                    looks_like_login_page=looks_like_login_page,
                    wait_for_portal_ready=wait_for_portal_ready,
                )

            if not logged_in and looks_like_login_page(page):
                raise LoginRequiredError(
                    "门户自动登录失败；请先运行 "
                    f"`python -m main.ingest.defect_fetch --backend {backend} --refresh-login`"
                )

            
            for ticket_id in ids:
                try:
                    html, url_used, status = _fetch_single_ticket(
                        page,
                        context,
                        ticket_id,
                        canonical,
                        PlaywrightTimeoutError=PlaywrightTimeoutError,
                        PlaywrightError=PlaywrightError,
                        find_bugzilla_page=find_bugzilla_page,
                        build_bugzilla_detail_urls=build_bugzilla_detail_urls,
                        open_plm_home=open_plm_home,
                        goto_bug_from_plm_home=goto_bug_from_plm_home,
                        goto_story_from_plm_home=goto_story_from_plm_home,
                        looks_like_sso_failure=looks_like_sso_failure,
                        looks_like_login_page=looks_like_login_page,
                    )
                    html_sha = hashlib.sha256(html.encode("utf-8", errors="ignore")).hexdigest()
                    out_path = _raw_dir(backend) / f"{ticket_id}.html"
                    out_path.write_text(html, encoding="utf-8")
                    _append_meta(
                        backend,
                        {
                            "ticket_id": ticket_id,
                            "backend": canonical,
                            "url": url_used,
                            "http_status": status,
                            "html_sha256": html_sha,
                            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        },
                    )
                    ok_count += 1
                    logger.info("fetched %s (status=%s)", ticket_id, status)
                except LoginRequiredError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.warning("抓取 %s 失败: %s", ticket_id, exc)
                    _append_meta(
                        backend,
                        {
                            "ticket_id": ticket_id,
                            "backend": canonical,
                            "url": "",
                            "http_status": 0,
                            "error": str(exc),
                            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        },
                    )
                page.wait_for_timeout(int(random.uniform(800, 2000)))

            
            try:
                context.storage_state(path=str(state_path))
            except Exception:  # noqa: BLE001
                pass
        finally:
            browser.close()

    return ok_count


def _fetch_single_ticket(
    page,
    context,
    ticket_id: str,
    canonical: str,
    *,
    PlaywrightTimeoutError,
    PlaywrightError,
    find_bugzilla_page,
    build_bugzilla_detail_urls,
    open_plm_home,
    goto_bug_from_plm_home,
    goto_story_from_plm_home,
    looks_like_sso_failure,
    looks_like_login_page,
) -> tuple[str, str, int]:
    """抓取单个 ticket 的 HTML；返回 ``(html, url_used, http_status)``。

    - bugzilla：依次尝试 [proxy_url, direct_url]，命中即返回
    - zentao / zentao_story：确保 PLM 首页已打开 → 搜索跳转到详情
    """
    if canonical == "bugzilla":
        last_error = None
        
        
        
        from main.ingest._capture_session import build_bugzilla_home_urls

        for home_url in build_bugzilla_home_urls():
            try:
                page.goto(home_url, wait_until="domcontentloaded", timeout=20000)
                break
            except (PlaywrightTimeoutError, PlaywrightError) as exc:
                logger.warning("bugzilla home %s 失败: %s", home_url, exc)

        candidates = build_bugzilla_detail_urls(ticket_id)
        for url in candidates:
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=20000)
                status = resp.status if resp else 0
                target_page = find_bugzilla_page(context, page)
                html = target_page.content()
                if looks_like_login_page(target_page):
                    raise LoginRequiredError(f"访问 {ticket_id} 时被重定向到登录页")
                return html, url, status
            except LoginRequiredError:
                raise
            except (PlaywrightTimeoutError, PlaywrightError) as exc:
                last_error = exc
                logger.warning("bugzilla URL %s 失败: %s", url, exc)
                continue
        raise RuntimeError(f"all bugzilla urls failed: {last_error}")

    
    plm_page = open_plm_home(page, context)
    if plm_page is None or looks_like_sso_failure(plm_page):
        raise RuntimeError("PLM 首页不可达（SSO app not allowed）")
    if looks_like_login_page(plm_page):
        raise LoginRequiredError("打开 PLM 首页后仍在登录页")

    if canonical == "zentao_story":
        ok = goto_story_from_plm_home(plm_page, ticket_id)
    else:
        ok = goto_bug_from_plm_home(plm_page, ticket_id)
    if not ok:
        raise RuntimeError(f"PLM 搜索跳转失败: {ticket_id}")

    
    time_budget = 8.0
    import time as _time

    deadline = _time.monotonic() + time_budget
    target_page = plm_page
    while _time.monotonic() < deadline:
        alive = [p for p in context.pages if not p.is_closed()]
        for cand in reversed(alive):
            if "plm.infosec.com.cn" in (cand.url or "") and not looks_like_sso_failure(cand):
                target_page = cand
                break
        break

    try:
        target_page.wait_for_load_state("domcontentloaded", timeout=10000)
    except PlaywrightTimeoutError:
        pass

    if looks_like_login_page(target_page):
        raise LoginRequiredError(f"访问 {ticket_id} 时被重定向到登录页")

    
    
    
    
    final_url = (target_page.url or "").lower()
    expected_url_tokens = (
        ("story-view-", "m=story&f=view") if canonical == "zentao_story"
        else ("bug-view-", "m=bug&f=view")
    )
    if not any(tok in final_url for tok in expected_url_tokens):
        raise RuntimeError(
            f"zentao 搜索未跳转到详情页（最终 url={final_url[:120]}），"
            f"该 ticket 在禅道不存在"
        )

    html = target_page.content()
    return html, target_page.url or "", 200







def fetch_one_sync(ticket_id: str, backend: str) -> dict[str, Any]:
    """单条抓取；永不抛异常，返回 ``{"ok": bool, "raw_path", "html_sha256", "url", "error"}``。

    Tool 层 ``defect_fetch_on_demand`` 依赖此接口。

    **进程隔离**：实际抓取走 ``subprocess.run([python, -m main.ingest.defect_fetch, ...])``，
    避免在 langgraph dev 的 asyncio 事件循环里直接跑 ``sync_playwright`` —— 后者内部
    通过 greenlet 启动自己的 event loop + ``os.getcwd``，会被 BlockBuster 拦截抛
    ``BlockingError``。子进程里没有 BlockBuster，行为与命令行 ``python -m ...`` 一致。
    """
    _ensure_no_langsmith()
    canonical = _canonical_backend(backend)
    raw_path = _raw_dir(backend) / f"{ticket_id}.html"

    
    pre_mtime = raw_path.stat().st_mtime if raw_path.exists() else 0.0

    cmd = [
        sys.executable,
        "-m",
        "main.ingest.defect_fetch",
        "--backend",
        canonical,
        "--ids",
        ticket_id,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            
            
            timeout=int(os.environ.get("DEFECT_FETCH_SUBPROCESS_TIMEOUT") or "270"),
            cwd=str(Path(__file__).resolve().parent.parent.parent),
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "error": "fetch_timeout",
            "message": f"subprocess 超时 {exc.timeout}s",
            "ticket_id": ticket_id,
            "backend": canonical,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": "subprocess_failed",
            "message": str(exc),
            "ticket_id": ticket_id,
            "backend": canonical,
        }

    rc = proc.returncode
    if rc == 5:
        return {
            "ok": False,
            "error": "login_expired",
            "message": (proc.stderr or "门户登录失败").strip()[:300],
            "ticket_id": ticket_id,
            "backend": canonical,
        }
    if rc == 3:
        return {
            "ok": False,
            "error": "system_exit_3",
            "message": "无法访问 WebVPN 门户",
            "ticket_id": ticket_id,
            "backend": canonical,
        }
    if rc == 4:
        return {
            "ok": False,
            "error": "system_exit_4",
            "message": "Playwright 未安装",
            "ticket_id": ticket_id,
            "backend": canonical,
        }
    if rc != 0:
        return {
            "ok": False,
            "error": f"system_exit_{rc}",
            "message": (proc.stderr or proc.stdout or "").strip()[:300],
            "ticket_id": ticket_id,
            "backend": canonical,
        }

    if not raw_path.exists() or raw_path.stat().st_mtime == pre_mtime:
        return {
            "ok": False,
            "error": "no_fetch",
            "message": "subprocess 退出 0 但未写入 raw HTML",
            "ticket_id": ticket_id,
            "backend": canonical,
        }

    html_sha = ""
    try:
        html_sha = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    except Exception:  # noqa: BLE001
        pass
    from main.ingest._capture_session import build_bugzilla_detail_urls

    url = build_bugzilla_detail_urls(ticket_id)[0] if canonical == "bugzilla" else ""
    return {
        "ok": True,
        "raw_path": str(raw_path),
        "html_sha256": html_sha,
        "url": url,
        "ticket_id": ticket_id,
        "backend": canonical,
    }







def refresh_login_sync(backend: str) -> bool:
    """编程式触发一次 refresh-login，永不抛异常；返回是否成功。

    工具层（``defect_fetch_on_demand``）在检测到 ``no_saved_session`` /
    ``session_stale`` / ``login_expired`` 时调用本函数自动恢复，避免把运维状态
    冒泡给 agent / 用户。

    **进程隔离**：实际登录走子进程 ``python -m main.ingest.defect_fetch
    --backend X --refresh-login``。原因同 ``fetch_one_sync``：sync_playwright
    在 langgraph dev 的事件循环里会被 BlockBuster 拦截。

    成功路径取决于环境：
    - ``PLAYWRIGHT_HEADLESS=0`` 或 ``DEFECT_FETCH_DISPLAY=1`` → headful，OCR + 人工兜底
    - 默认 headless → 仅靠 ddddocr 多次重试（``CAPTCHA_OCR_RETRY`` 默认 10）
    """
    _ensure_no_langsmith()
    canonical = _canonical_backend(backend)
    cmd = [
        sys.executable,
        "-m",
        "main.ingest.defect_fetch",
        "--backend",
        canonical,
        "--refresh-login",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(Path(__file__).resolve().parent.parent.parent),
        )
    except subprocess.TimeoutExpired:
        logger.warning("refresh_login_sync(%s) 子进程超时", canonical)
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("refresh_login_sync(%s) 子进程异常: %s", canonical, exc)
        return False

    if proc.returncode == 0 and _state_path(backend).exists():
        return True
    logger.info(
        "refresh_login_sync(%s) 未成功 rc=%s stderr=%s",
        canonical,
        proc.returncode,
        (proc.stderr or "").strip()[:300],
    )
    return False







async def _fetch_loop(ids: list[str], backend: str, *, refresh_login_only: bool = False) -> int:
    """旧 v1.4 签名的 async wrapper；内部同步执行。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, lambda: _fetch_loop_sync(ids, backend, refresh_login_only=refresh_login_only)
    )







def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _ensure_no_langsmith()
    
    
    
    try:
        from main.langchain_env import langchain_load_dotenv_if_present

        langchain_load_dotenv_if_present()
    except Exception as exc:  # noqa: BLE001
        logger.warning("environment 加载失败（可忽略）: %s", exc)

    parser = argparse.ArgumentParser(description="HTML 抓取（Playwright + WebVPN 门户登录）")
    parser.add_argument(
        "--backend",
        choices=list(SUPPORTED_BACKENDS),
        required=True,
        help="bugzilla / zentao / zentao_story（plm 为 zentao 的别名）",
    )
    parser.add_argument("--ids", default="", help="逗号分隔 id 列表，如 BUG-1,BUG-2")
    parser.add_argument("--ids-file", default="", help="每行一个 id 的文本文件")
    parser.add_argument("--resume", action="store_true", help="跳过已抓 id")
    parser.add_argument(
        "--refresh-login",
        action="store_true",
        help="只跑一次 headful 登录，保存 storage_state 后退出（不抓票）",
    )
    args = parser.parse_args()

    if args.refresh_login:
        try:
            _fetch_loop_sync([], args.backend, refresh_login_only=True)
        except LoginRequiredError as exc:
            print(f"❌ {exc}", file=sys.stderr)
            sys.exit(5)
        print(f"✅ refresh-login 完成（backend={args.backend}）")
        return

    ids = _load_ids(args)
    if not ids:
        print("❌ 请提供 --ids / --ids-file 或使用 --refresh-login", file=sys.stderr)
        sys.exit(2)
    if args.resume:
        ids = _resume_filter(ids, args.backend)
    if not ids:
        print("✅ 所有 id 已在 meta.jsonl 中，无需重复抓取")
        return

    try:
        count = _fetch_loop_sync(ids, args.backend)
    except LoginRequiredError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        sys.exit(5)
    print(f"✅ fetched {count}/{len(ids)} tickets, raw saved to {_raw_dir(args.backend)}")







def build_detail_url(backend: str, ticket_id: str) -> str:
    """返回首选详情 URL（不再带选择；Bugzilla=proxy，Zentao=search landing URL）。"""
    from main.ingest._capture_session import build_bugzilla_detail_urls, PLM_PROXY_HOME

    canonical = _canonical_backend(backend)
    if canonical == "bugzilla":
        return build_bugzilla_detail_urls(ticket_id)[0]
    if canonical in ("zentao", "zentao_story"):
        return PLM_PROXY_HOME
    raise ValueError(f"未知 backend: {backend}")


if __name__ == "__main__":
    main()
