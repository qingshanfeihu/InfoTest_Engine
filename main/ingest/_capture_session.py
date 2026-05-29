"""WebVPN 门户登录 + 验证码 OCR + Bugzilla/禅道 导航的共享工具。

从 ``scripts/bugzilla_capture.py`` / ``scripts/zendao_capture.py`` 提炼；
被 ``main/ingest/defect_fetch.py`` 与开发期的 capture 脚本共同使用。

### 能力总览

1. **登录**：``login_with_captcha(page, user, password)`` —— 自动识别验证码并 submit，
   失败（OCR 连续失效 / 页面仍在登录态）时向 ``stdin`` 询问手动输入，headless 下直接返回 False。
2. **门户就绪**：``wait_for_portal_ready(page)`` —— 等待 ``#tempNo`` / ``#currentuser`` / 含 PLM 的 ``<li>`` 全部到位。
3. **Bugzilla 详情 URL 候选**：``build_bugzilla_detail_urls(bug_id)`` —— 返回 [proxy_url, direct_url]。
4. **禅道 PLM 入口**：``open_plm_home(page, context)`` + ``goto_bug_from_plm_home(page, bug_id)``。
5. **SSO 失效识别**：``looks_like_sso_failure(page)``。

### 可选依赖

- ``ddddocr`` + ``Pillow``：仅在尝试验证码 OCR 时 import；未安装时自动退化到"只支持手动输入"。
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from collections import Counter
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)







PORTAL_LOGIN_URLS = [
    (
        os.environ.get("PORTAL_LOGIN_URL")
        or "https://portal.infosec.com.cn/prx/000/http/localh/login/menhu/WebVPN/login/index.html"
    ),
    "https://menhu.infosec.com.cn/login/d2VsY29tZQ/bWFpbg?tempNo=2",
]


BUGZILLA_DIRECT_HOME = (
    os.environ.get("BUGZILLA_BASE_URL") or "http://bugzilla.arraynetworks.com.cn/bugzilla"
).rstrip("/")


BUGZILLA_PROXY_HOME = (
    os.environ.get("BUGZILLA_PROXY_URL")
    or "https://portal.infosec.com.cn/prx/000/http/bugzilla.arraynetworks.com.cn:80/bugzilla"
).rstrip("/")


PLM_PROXY_HOME = (
    os.environ.get("PLM_PROXY_URL")
    or "https://portal.infosec.com.cn/prx/000/https/plm.infosec.com.cn/index.php?m=my&f=index"
)


PLM_DIRECT_HOME = (
    os.environ.get("ZENTAO_BASE_URL") or "https://plm.infosec.com.cn"
).rstrip("/")


CAPTCHA_LEN_MIN = int(os.environ.get("CAPTCHA_LEN_MIN") or "4")
CAPTCHA_LEN_MAX = int(os.environ.get("CAPTCHA_LEN_MAX") or "6")
CAPTCHA_OCR_RETRY = int(os.environ.get("CAPTCHA_OCR_RETRY") or "10")
LOGIN_RETRY = int(os.environ.get("LOGIN_RETRY") or "5")
CAPTCHA_CHARSET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"







def is_valid_url(raw_url: str | None) -> bool:
    return bool(raw_url and raw_url.strip() and raw_url != "about:blank")


def wait_for_valid_url(page, timeout_ms: int) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if page.is_closed():
            return False
        if is_valid_url(page.url):
            return True
        page.wait_for_timeout(200)
    return (not page.is_closed()) and is_valid_url(page.url)


def safe_title(page) -> str:
    try:
        return page.title()
    except Exception:  # noqa: BLE001
        return "(title unavailable)"


def find_first_locator(page, selectors: Iterable[str]):
    for sel in selectors:
        loc = page.locator(sel)
        try:
            if loc.count() > 0:
                return loc.first
        except Exception:  # noqa: BLE001
            continue
    return None







def _normalize_captcha_text(raw_text: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z]", "", (raw_text or "")).strip()
    if len(cleaned) > CAPTCHA_LEN_MAX:
        cleaned = cleaned[:CAPTCHA_LEN_MAX]
    return cleaned


def _make_captcha_variants(image_bytes: bytes) -> list[bytes]:
    variants: list[bytes] = [image_bytes]
    try:
        from PIL import Image, ImageOps  # type: ignore[import-not-found]

        img = Image.open(BytesIO(image_bytes)).convert("L")
        auto = ImageOps.autocontrast(img)
        buf_auto = BytesIO()
        auto.save(buf_auto, format="PNG")
        variants.append(buf_auto.getvalue())

        for th in (120, 150, 180):
            bw = auto.point(lambda p, t=th: 255 if p > t else 0)
            buf_bw = BytesIO()
            bw.save(buf_bw, format="PNG")
            variants.append(buf_bw.getvalue())
    except Exception:  # noqa: BLE001
        pass
    return variants


def _build_ocr_models() -> list:
    try:
        import ddddocr  # type: ignore[import-not-found]
    except ImportError:
        logger.warning("ddddocr 未安装，跳过验证码 OCR；可 pip install ddddocr")
        return []

    try:
        ocr_default = ddddocr.DdddOcr(show_ad=False)
        ocr_beta = ddddocr.DdddOcr(beta=True, show_ad=False)
        ocr_default.set_ranges(CAPTCHA_CHARSET)
        ocr_beta.set_ranges(CAPTCHA_CHARSET)
        return [ocr_default, ocr_beta]
    except Exception as exc:  # noqa: BLE001
        logger.warning("ddddocr 初始化失败: %s", exc)
        return []


def solve_captcha_with_ocr(image_bytes: bytes, ocr_models: list | None = None) -> tuple[str, list[str]]:
    """返回 ``(voted_result, all_candidates)``；若 OCR 完全不可用则 ``("", [])``。"""
    models = ocr_models or _build_ocr_models()
    if not models:
        return "", []
    candidates: list[str] = []
    for variant in _make_captcha_variants(image_bytes):
        for model in models:
            for png_fix in (False, True):
                try:
                    txt = model.classification(variant, png_fix=png_fix)
                    norm = _normalize_captcha_text(str(txt))
                    if len(norm) >= CAPTCHA_LEN_MIN:
                        candidates.append(norm)
                except Exception:  # noqa: BLE001
                    continue
    if not candidates:
        return "", []
    voted = Counter(candidates).most_common(1)[0][0]
    return voted, candidates







_LOGIN_PASSWORD_SELECTORS = [
    "input[type='password']",
    "input[name*='password' i]",
    "input[id*='password' i]",
    "#pass",
    "input[name='pwd']",
]

_LOGIN_USER_SELECTORS = [
    "#user",
    "input[name='uname']",
    "input[name='username']",
    "input[id='username']",
    "input[name*='user' i]",
    "input[id*='user' i]",
    "input[placeholder*='用户名']",
    "input[type='text']",
]

_LOGIN_CAPTCHA_INPUT_SELECTORS = [
    "#vscode",
    "input[name='vscode']",
    "input[name*='captcha' i]",
    "input[id*='captcha' i]",
    "input[name*='verify' i]",
    "input[id*='verify' i]",
    "input[name*='code' i]",
    "input[id*='code' i]",
    "input[placeholder*='验证码']",
]

_LOGIN_CAPTCHA_IMG_SELECTORS = [
    "#vcode-pic",
    "img[id='vcode-pic']",
    "img[id*='captcha' i]",
    "img[src*='captcha' i]",
    "img[id*='verify' i]",
    "img[src*='verify' i]",
    "canvas[id*='captcha' i]",
    "img[src*='vcode' i]",
    "img[src*='code' i]:not(#QRCode)",
]

_LOGIN_SUBMIT_SELECTORS = [
    "button.loginBtn",
    "button:has-text('登录')",
    "button[type='submit']",
    "input[type='submit']",
    "a:has-text('登录')",
    "#loginBtn",
    ".login-btn",
]

_LOGIN_TEXT_MARKERS = (
    "登录",
    "验证码",
    "用户名",
    "密码",
    "username",
    "password",
    "captcha",
    "sign in",
    "signin",
)


def looks_like_login_page(page) -> bool:
    """启发式判断当前 page 是否仍处于登录态页面。

    判定为 OR 链（任一命中即视为登录页）：

    0. **portal-ready 短路**：先看 ``#currentuser`` / ``#tempNo`` 是否已渲染。
       ready 即返回 False —— 否则像 ``/login/welcome/main`` 这种"路径含 /login/
       但实际是首页"的 SSO 重定向落地页，会被 URL/title 启发式误判为登录页。
    1. 找到 password input 控件 → True（最强信号）
    2. URL 含 ``/login/`` / ``signin`` → True；``sso`` 仅在页面文本也像登录页时成立
    3. title 含登录类关键字（"登录" / "sign in"）→ True
    """
    
    
    
    
    try:
        page.wait_for_function(
            "() => Boolean(document.querySelector('#currentuser')) "
            "|| Boolean(document.querySelector('#tempNo'))",
            timeout=2000,
        )
        return False
    except Exception:  # noqa: BLE001
        pass

    
    
    
    url_raw = page.url or ""
    content_url_tokens = (
        "show_bug.cgi",
        "buglist.cgi",
        "/zentao/bug-view-",
        "/zentao/story-view-",
    )
    if any(tok in url_raw.lower() for tok in content_url_tokens):
        return False

    
    try:
        if find_first_locator(page, _LOGIN_PASSWORD_SELECTORS) is not None:
            logger.debug("looks_like_login_page: password input matched url=%s", url_raw)
            return True
    except Exception:  # noqa: BLE001
        pass

    
    url = (page.url or "").lower()
    if any(tok in url for tok in ("/login/", "signin")):
        logger.debug("looks_like_login_page: URL token matched url=%s", page.url)
        return True
    if "sso" in url:
        try:
            body = (page.evaluate("() => document.body ? document.body.innerText : ''") or "").lower()
        except Exception:  # noqa: BLE001
            body = ""
        try:
            title = (page.title() or "").lower()
        except Exception:  # noqa: BLE001
            title = ""
        if any(marker in f"{title}\n{body}" for marker in _LOGIN_TEXT_MARKERS):
            logger.debug("looks_like_login_page: SSO login marker matched url=%s", page.url)
            return True

    
    try:
        title = (page.title() or "").lower()
    except Exception:  # noqa: BLE001
        title = ""
    if any(marker in title for marker in ("登录", "sign in", "signin")):
        logger.debug("looks_like_login_page: title token matched title=%r", title)
        return True

    
    
    
    

    return False


def login_with_captcha(
    page,
    user: str,
    password: str,
    *,
    debug_dir: Path | None = None,
    allow_manual_captcha: bool = True,
    headless: bool = False,
) -> bool:
    """尝试在当前页面完成账号/密码/验证码登录。

    Returns:
        True  → 登录页已离开
        False → 仍在登录页 / 字段不识别（由调用方决定是抛 LoginRequiredError 还是降级）
    """
    user_loc = find_first_locator(page, _LOGIN_USER_SELECTORS)
    pass_loc = find_first_locator(page, _LOGIN_PASSWORD_SELECTORS)
    code_loc = find_first_locator(page, _LOGIN_CAPTCHA_INPUT_SELECTORS)
    captcha_img_loc = find_first_locator(page, _LOGIN_CAPTCHA_IMG_SELECTORS)
    submit_loc = find_first_locator(page, _LOGIN_SUBMIT_SELECTORS)

    if user_loc is None or pass_loc is None:
        logger.info("当前页未识别到登录表单，等待可能的 SSO 自动跳转")
        page.wait_for_timeout(1500)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:  # noqa: BLE001
            pass
        if not looks_like_login_page(page):
            logger.info("未识别到登录表单且页面已离开登录态，视为自动登录完成")
            return True
        if wait_for_portal_ready(page, timeout_ms=5000):
            logger.info("未识别到登录表单但门户已就绪，视为自动登录完成")
            return True
        logger.info("当前页仍像登录页，login_with_captcha 返回失败")
        return False

    ocr_models = _build_ocr_models()

    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)

    for attempt in range(1, LOGIN_RETRY + 1):
        if page.is_closed():
            logger.warning("登录页已关闭")
            return False

        logger.info("自动登录尝试 %d/%d", attempt, LOGIN_RETRY)

        
        
        
        
        if attempt > 1:
            
            try:
                page.keyboard.press("Enter")
            except Exception:  # noqa: BLE001
                pass
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(800)
            user_loc = find_first_locator(page, _LOGIN_USER_SELECTORS)
            pass_loc = find_first_locator(page, _LOGIN_PASSWORD_SELECTORS)
            if user_loc is None or pass_loc is None:
                
                logger.info("attempt %d 找不到登录表单，尝试整页 reload", attempt)
                try:
                    page.reload(wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(1000)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("reload 失败: %s", exc)
                
                try:
                    page.wait_for_selector(
                        ",".join(_LOGIN_USER_SELECTORS), timeout=10000, state="visible"
                    )
                except Exception:  # noqa: BLE001
                    pass
                user_loc = find_first_locator(page, _LOGIN_USER_SELECTORS)
                pass_loc = find_first_locator(page, _LOGIN_PASSWORD_SELECTORS)
                if user_loc is None or pass_loc is None:
                    logger.warning(
                        "attempt %d reload 后仍找不到登录表单 (url=%s)，结束登录",
                        attempt,
                        page.url,
                    )
                    return False
            code_loc = find_first_locator(page, _LOGIN_CAPTCHA_INPUT_SELECTORS)
            captcha_img_loc = find_first_locator(page, _LOGIN_CAPTCHA_IMG_SELECTORS)
            submit_loc = find_first_locator(page, _LOGIN_SUBMIT_SELECTORS)

        try:
            user_loc.fill(user, timeout=10000)
            pass_loc.fill(password, timeout=10000)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "attempt %d 填写账号密码失败: %s（继续下一次重试）", attempt, exc
            )
            continue

        if code_loc is not None and captcha_img_loc is not None:
            code_text = ""
            for try_idx in range(1, CAPTCHA_OCR_RETRY + 1):
                if page.is_closed():
                    return False
                try:
                    img_bytes = captcha_img_loc.screenshot(type="png")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("验证码截图失败: %s", exc)
                    break
                code_text, candidates = solve_captcha_with_ocr(img_bytes, ocr_models)
                if debug_dir is not None:
                    try:
                        (debug_dir / f"attempt_{attempt:02d}_try_{try_idx:02d}.png").write_bytes(img_bytes)
                        (debug_dir / f"attempt_{attempt:02d}_try_{try_idx:02d}.txt").write_text(
                            "candidates=" + ",".join(candidates) + "\n", encoding="utf-8"
                        )
                    except Exception:  # noqa: BLE001
                        pass
                logger.info("OCR 验证码 try %d/%d: %s", try_idx, CAPTCHA_OCR_RETRY, code_text or "<empty>")
                if len(code_text) >= CAPTCHA_LEN_MIN:
                    code_loc.fill(code_text)
                    break
                
                try:
                    captcha_img_loc.click()
                except Exception:  # noqa: BLE001
                    pass
                page.wait_for_timeout(600)

            if not code_text:
                if not allow_manual_captcha or headless or not sys.stdin.isatty():
                    logger.warning("OCR 失败且无法手工输入（headless/非 tty），终止本次登录尝试")
                    return False
                try:
                    manual_code = input("[?] OCR 失败，请直接输入浏览器中的验证码: ").strip()
                except EOFError:
                    return False
                manual_code = _normalize_captcha_text(manual_code)
                if len(manual_code) < CAPTCHA_LEN_MIN:
                    logger.warning("手工验证码长度不足")
                    return False
                code_loc.fill(manual_code)

        try:
            if submit_loc is not None:
                submit_loc.click()
            else:
                pass_loc.press("Enter")
        except Exception as exc:  # noqa: BLE001
            logger.warning("提交登录失败: %s", exc)
            return False

        page.wait_for_timeout(2500)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:  # noqa: BLE001
            pass

        if not looks_like_login_page(page):
            logger.info("自动登录成功")
            return True

        logger.warning("仍在登录页，准备重试 attempt=%d", attempt)
        if captcha_img_loc is not None:
            try:
                captcha_img_loc.click()
                page.wait_for_timeout(800)
            except Exception:  # noqa: BLE001
                pass

    logger.error("login_with_captcha 连续 %d 次仍失败", LOGIN_RETRY)
    return False







def wait_for_portal_ready(page, *, timeout_ms: int = 20000) -> bool:
    from playwright.sync_api import TimeoutError as _PwTimeout  # type: ignore[import-not-found]

    try:
        page.wait_for_function(
            """
            () => {
                const tempNo = document.querySelector('#tempNo')?.value?.trim() || '';
                const loginType = document.querySelector('#logintype')?.value?.trim() || '';
                const currentUser = document.querySelector('#currentuser')?.textContent?.trim() || '';
                const hasPlmEntry = Array.from(document.querySelectorAll('li')).some(
                    (node) => (node.textContent || '').includes('PLM')
                );
                return Boolean(tempNo && loginType && currentUser && hasPlmEntry);
            }
            """,
            timeout=timeout_ms,
        )
        logger.info("门户首页初始化完成")
        return True
    except _PwTimeout:
        logger.warning("门户首页初始化等待超时")
        return False







def build_bugzilla_detail_urls(bug_id: str) -> list[str]:
    """返回详情页 URL 候选 [proxy_first, direct_fallback]。

    Bugzilla 只接受纯数字 id；会自动 strip ``BUG-`` / ``#`` 等前缀。
    """
    nid = _strip_bug_prefix(str(bug_id)) or str(bug_id)
    encoded = quote_plus(nid)
    return [
        f"{BUGZILLA_PROXY_HOME}/show_bug.cgi?id={encoded}",
        f"{BUGZILLA_DIRECT_HOME}/show_bug.cgi?id={encoded}",
    ]


def build_bugzilla_home_urls() -> list[str]:
    return [f"{BUGZILLA_PROXY_HOME}/", f"{BUGZILLA_DIRECT_HOME}/"]


def find_bugzilla_page(context, fallback_page):
    for p in reversed(context.pages):
        if p.is_closed():
            continue
        url = (p.url or "").lower()
        if "bugzilla.arraynetworks.com.cn" in url:
            return p
    return fallback_page







def looks_like_sso_failure(page) -> bool:
    url = page.url or ""
    if "plm.infosec.com.cn:443" in url and "ticket=" in url:
        return True
    try:
        title = page.title() or ""
    except Exception:  # noqa: BLE001
        title = ""
    if "SSO Authentication failed" in title:
        return True
    try:
        body = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
    except Exception:  # noqa: BLE001
        body = ""
    lowered = body.lower()
    return "sso authentication failed" in lowered or "app not allowed" in lowered


def _find_visible_plm_entry(page):
    entries = page.locator("li", has_text="PLM")
    for idx in range(entries.count()):
        cand = entries.nth(idx)
        try:
            if cand.is_visible():
                return cand
        except Exception:  # noqa: BLE001
            continue
    return None


def open_plm_home(page, context, *, plm_home_url: str | None = None):
    """确保当前有一个 PLM 首页 tab（带 ``#searchInput`` 搜索框）。返回 PLM 页面对象。"""
    if page.locator("#searchInput").count() > 0:
        return page

    wait_for_portal_ready(page)

    
    portal_entry = _find_visible_plm_entry(page)
    if portal_entry is not None:
        logger.info("通过门户 PLM 入口进入")
        try:
            portal_entry.click(timeout=5000)
        except Exception as exc:  # noqa: BLE001
            logger.warning("点击门户 PLM 入口失败: %s", exc)
        else:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                alive = [p for p in context.pages if not p.is_closed()]
                for cand in reversed(alive):
                    try:
                        if looks_like_sso_failure(cand):
                            continue
                        if "plm.infosec.com.cn" not in (cand.url or ""):
                            continue
                        if cand.locator("#searchInput").count() > 0:
                            return cand
                    except Exception:  # noqa: BLE001
                        continue
                page.wait_for_timeout(500)

    target = plm_home_url or PLM_PROXY_HOME
    for attempt in range(1, 4):
        if attempt > 1:
            page.wait_for_timeout(attempt * 1500)
        logger.info("直接 goto PLM 首页 attempt=%d url=%s", attempt, target)
        try:
            page.goto(target, wait_until="domcontentloaded", timeout=20000)
        except Exception as exc:  # noqa: BLE001
            logger.warning("goto PLM 首页异常: %s", exc)
        try:
            page.wait_for_selector("#searchInput", timeout=5000)
            return page
        except Exception:  # noqa: BLE001
            pass
        if looks_like_sso_failure(page):
            logger.warning("SSO app not allowed，重试")
            continue

    logger.warning("无法稳定进入 PLM 首页，返回当前页")
    return page


def goto_bug_from_plm_home(page, bug_id: str) -> bool:
    """在 PLM 首页通过搜索框跳转到 bug 详情页；返回是否成功 navigate。"""
    search_input = page.locator("#searchInput").first
    search_go = page.locator("#searchGo").first
    search_type = page.locator("#searchType").first

    try:
        if search_input.count() == 0 or search_go.count() == 0:
            logger.warning("PLM 首页缺少搜索框，无法跳转")
            return False
    except Exception:  # noqa: BLE001
        return False

    try:
        if search_type.count() > 0:
            current_type = search_type.input_value().strip().lower()
            if current_type != "bug":
                page.evaluate(
                    """
                    () => {
                        if (window.$ && typeof $.setSearchType === 'function') {
                            $.setSearchType('bug');
                        } else {
                            const input = document.querySelector('#searchType');
                            if (input) input.value = 'bug';
                        }
                    }
                    """
                )

        nid = _strip_bug_prefix(bug_id)
        search_input.fill(nid)
        search_go.click()
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("PLM 搜索跳转失败: %s", exc)
        return False


def goto_story_from_plm_home(page, story_id: str) -> bool:
    """在 PLM 首页搜索跳转到 story 详情。"""
    search_input = page.locator("#searchInput").first
    search_go = page.locator("#searchGo").first

    try:
        if search_input.count() == 0 or search_go.count() == 0:
            return False
        page.evaluate(
            """
            () => {
                if (window.$ && typeof $.setSearchType === 'function') {
                    $.setSearchType('story');
                } else {
                    const input = document.querySelector('#searchType');
                    if (input) input.value = 'story';
                }
            }
            """
        )
        nid = _strip_bug_prefix(story_id)
        search_input.fill(nid)
        search_go.click()
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("PLM story 搜索跳转失败: %s", exc)
        return False


_PREFIX_RE = re.compile(r"^(?:BUG|BZ|ZT|PLM|STORY|REQ|TICKET|#)[-_ #]*", re.IGNORECASE)


def _strip_bug_prefix(ticket_id: str) -> str:
    s = (ticket_id or "").strip()
    if not s:
        return s
    m = _PREFIX_RE.match(s)
    if m:
        s = s[m.end() :]
    m2 = re.match(r"^(\d+)", s)
    return m2.group(1) if m2 else s







def ensure_portal_logged_in(
    page,
    context,
    *,
    user: str,
    password: str,
    state_path: Path | None = None,
    debug_dir: Path | None = None,
    headless: bool = False,
) -> bool:
    """打开门户登录入口 → 尝试自动登录 → 登录成功写 storage_state。

    返回 True 表示已位于已登录状态；False 表示自动登录失败（headless 时不阻塞，返回 False）。
    """
    for url in PORTAL_LOGIN_URLS:
        try:
            
            
            
            page.goto(url, wait_until="networkidle", timeout=20000)
            break
        except Exception as exc:  # noqa: BLE001
            logger.warning("打开门户失败 %s: %s", url, exc)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                break
            except Exception:  # noqa: BLE001
                continue

    
    
    
    
    try:
        page.wait_for_function(
            """() => Boolean(document.querySelector('#currentuser'))
                  || Boolean(document.querySelector('#tempNo'))
                  || Boolean(document.querySelector('input[type=\"password\"]'))
                  || Boolean(document.querySelector('#user'))""",
            timeout=8000,
        )
    except Exception:  # noqa: BLE001
        pass

    if not looks_like_login_page(page):
        logger.info("当前已在已登录态（未检测到登录表单）")
        if state_path is not None:
            try:
                context.storage_state(path=str(state_path))
            except Exception:  # noqa: BLE001
                pass
        return True

    ok = login_with_captcha(
        page,
        user,
        password,
        debug_dir=debug_dir,
        allow_manual_captcha=not headless,
        headless=headless,
    )
    if ok and state_path is not None:
        try:
            context.storage_state(path=str(state_path))
        except Exception:  # noqa: BLE001
            pass
    return ok


def get_portal_credentials(prefix: str = "") -> tuple[str, str]:
    """从环境变量读账号密码。

    prefix 空 → ``PORTAL_LOGIN_USER`` / ``PORTAL_LOGIN_PASS``
    prefix="BUGZILLA" → 覆盖为 ``BUGZILLA_LOGIN_USER/PASS``，空时 fallback 到 PORTAL 版
    prefix="ZENDAO" → 同上
    """

    def _read(name: str) -> str:
        return (os.environ.get(name) or "").strip()

    prefix = (prefix or "").strip().upper()
    user = _read(f"{prefix}_LOGIN_USER") if prefix else ""
    pwd = _read(f"{prefix}_LOGIN_PASS") if prefix else ""
    if not user:
        user = _read("PORTAL_LOGIN_USER")
    if not pwd:
        pwd = _read("PORTAL_LOGIN_PASS")
    return user, pwd


__all__ = [
    
    "is_valid_url",
    "wait_for_valid_url",
    "safe_title",
    "find_first_locator",
    
    "solve_captcha_with_ocr",
    
    "looks_like_login_page",
    "login_with_captcha",
    "ensure_portal_logged_in",
    "get_portal_credentials",
    
    "build_bugzilla_detail_urls",
    "build_bugzilla_home_urls",
    "find_bugzilla_page",
    
    "wait_for_portal_ready",
    "open_plm_home",
    "goto_bug_from_plm_home",
    "goto_story_from_plm_home",
    "looks_like_sso_failure",
    
    "BUGZILLA_PROXY_HOME",
    "BUGZILLA_DIRECT_HOME",
    "PLM_PROXY_HOME",
    "PLM_DIRECT_HOME",
    "PORTAL_LOGIN_URLS",
]
