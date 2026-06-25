"""
OpenAI 兼容 chat completions client with structured JSON output.

调用方传入 ``base_url`` + ``api_key``（OpenAI 协议端点：mimo / dashscope 兼容口 /
deepseek 等）。``base_url`` 缺省时回退到 DashScope 兼容地址（历史默认）。
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

import requests

try:
    from terminal_progress import emit_llm_event
except ImportError:
    from main.terminal_progress import emit_llm_event

from main.common.llm_cache import LLMCache
from main.knowledge_paths import KNOWLEDGE_ROOT

_LLM_CACHE: LLMCache | None = None
_LLM_CACHE_INITIALIZED = False
_LLM_CACHE_LOCK = threading.Lock()


def _get_llm_cache() -> LLMCache | None:
    global _LLM_CACHE, _LLM_CACHE_INITIALIZED
    if _LLM_CACHE_INITIALIZED:
        return _LLM_CACHE
    with _LLM_CACHE_LOCK:
        if _LLM_CACHE_INITIALIZED:
            return _LLM_CACHE
        if os.environ.get("QA_LLM_CACHE_DISABLED") == "1":
            _LLM_CACHE = None
        else:
            _LLM_CACHE = LLMCache(root=KNOWLEDGE_ROOT / ".cache" / "llm")
        _LLM_CACHE_INITIALIZED = True
    return _LLM_CACHE

DASHSCOPE_COMPAT_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_CHAT_COMPLETIONS_SUFFIX = "/chat/completions"
DASHSCOPE_CHAT_URL = f"{DASHSCOPE_COMPAT_BASE}{_CHAT_COMPLETIONS_SUFFIX}"
CHAT_MODEL = "qwen-plus"
DEFAULT_MAX_TOKENS = 8192
DEFAULT_TEMPERATURE = 0.1
DEFAULT_TOP_P = 0.1
REQUEST_TIMEOUT = 180


class TruncationError(Exception):
    """Raised when LLM output is truncated (finish_reason == 'length')."""


class ChatCompletionError(Exception):
    """Raised on non-retryable chat completion failures."""


def resolve_chat_completions_url(base_url: str | None) -> str:
    """OpenAI 兼容 API 根（或已含 ``/chat/completions`` 的 URL）→ POST 目标."""
    if not base_url:
        return DASHSCOPE_CHAT_URL
    root = base_url.strip().rstrip("/")
    if root.endswith(_CHAT_COMPLETIONS_SUFFIX):
        return root
    return f"{root}{_CHAT_COMPLETIONS_SUFFIX}"


def _supports_thinking_toggle(url: str) -> bool:
    """端点是否认 `thinking` 开关（MiMo / 小米 / DeepSeek 系）。

    实测：思考模式下 tool_call 会以私有文本格式返回、且占满 token 致截断 → 拿不到
    结构化 tool_calls。对工具调用（结构化抽取）须关思考。与 agents/_llm 一致。
    """
    u = (url or "").lower()
    return any(k in u for k in ("mimo", "xiaomi", "deepseek"))


def chat_completion(
    session: requests.Session,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = DEFAULT_TEMPERATURE,
    top_p: float = DEFAULT_TOP_P,
    max_retries: int = 3,
    tool: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call LLM and return parsed JSON dict.

    Raises TruncationError if output was truncated.
    Raises ChatCompletionError on persistent failures.

    ``base_url`` 为 OpenAI 兼容 API 根（如 ``https://api.deepseek.com`` 或
    DashScope ``.../compatible-mode/v1``）；已含 ``/chat/completions`` 时原样使用。

    ``tool``（OpenAI function 定义 ``{"type":"function","function":{...}}``）非空时走
    **function calling** 结构化输出：强制 ``tool_choice`` 调该工具、解析 ``tool_calls``
    里的 ``arguments``（schema 作硬约束，比 json_object 更可靠）。MiMo/DeepSeek 端点会
    自动关思考（思考模式下 tool_call 以文本返回、且占满 token 截断，拿不到结构化）。
    ``tool`` 为空时维持 json_object 模式（向后兼容，行为不变）。
    """
    use_model = model or CHAT_MODEL
    use_url = resolve_chat_completions_url(base_url)
    cache_key_system = (
        system_prompt if tool is None
        else system_prompt + "\x00tool\x00" + json.dumps(tool, sort_keys=True, ensure_ascii=False)
    )

    cache = _get_llm_cache()
    if cache is not None:
        cached = cache.get(
            system=cache_key_system,
            user=user_prompt,
            model=use_model,
            max_tokens=max_tokens,
        )
        if cached is not None:
            emit_llm_event("cache_hit", "skipped LLM call (cache hit)")
            return cached

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": use_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
    }
    if tool is not None:
        body["tools"] = [tool]
        body["tool_choice"] = {
            "type": "function",
            "function": {"name": tool["function"]["name"]},
        }
        if _supports_thinking_toggle(use_url):
            body["thinking"] = {"type": "disabled"}
    else:
        body["response_format"] = {"type": "json_object"}

    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            r = session.post(
                use_url,
                headers=headers,
                json=body,
                timeout=REQUEST_TIMEOUT,
            )

            if r.status_code == 429:
                wait = 2 ** attempt * 5
                emit_llm_event("rate_limit", f"429 rate limited, waiting {wait}s")
                time.sleep(wait)
                continue

            r.raise_for_status()
            data = r.json()

            choice = data["choices"][0]
            finish_reason = choice.get("finish_reason", "")
            message = choice["message"]

            usage = data.get("usage", {})
            prompt_tok = usage.get("prompt_tokens", "?")
            comp_tok = usage.get("completion_tokens", "?")
            total_tok = usage.get("total_tokens", "?")
            retry_tag = f" (retry {attempt})" if attempt > 0 else ""
            emit_llm_event("usage", f"tokens: prompt={prompt_tok} completion={comp_tok} total={total_tok}{retry_tag}")

            if finish_reason == "length":
                raise TruncationError(
                    f"Output truncated at {max_tokens} tokens "
                    f"(prompt={usage.get('prompt_tokens')}, "
                    f"completion={usage.get('completion_tokens')})"
                )

            if tool is not None:
                tool_calls = message.get("tool_calls") or []
                if not tool_calls:
                    # 工具模式却没回结构化 tool_calls（端点偶发，如把工具调用塞进 content）→
                    # 当 JSON 错误走重试路径，不直接挂。
                    raise json.JSONDecodeError("tool mode: no tool_calls in response", "", 0)
                content = tool_calls[0].get("function", {}).get("arguments", "") or ""
            else:
                content = message["content"]

            result = json.loads(content)
            if cache is not None:
                cache.put(
                    result=result,
                    system=cache_key_system,
                    user=user_prompt,
                    model=use_model,
                    max_tokens=max_tokens,
                )
            return result

        except TruncationError:
            raise
        except json.JSONDecodeError as e:
            last_err = e
            if attempt < max_retries - 1:
                emit_llm_event("json_error", f"parse error on attempt {attempt + 1}, retrying")
                time.sleep(1)
                continue
            raise ChatCompletionError(f"JSON decode failed after {max_retries} attempts: {e}") from e
        except requests.exceptions.HTTPError as e:
            last_err = e
            if attempt < max_retries - 1:
                wait = 2 ** attempt * 3
                emit_llm_event("http_error", f"HTTP {e.response.status_code}, retrying in {wait}s")
                time.sleep(wait)
                continue
            raise ChatCompletionError(f"HTTP error after {max_retries} attempts: {e}") from e
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt < max_retries - 1:
                wait = 2 ** attempt * 3
                emit_llm_event("network_error", f"{e}, retrying in {wait}s")
                time.sleep(wait)
                continue
            raise ChatCompletionError(f"Request failed after {max_retries} attempts: {e}") from e

    raise ChatCompletionError(f"Exhausted {max_retries} retries; last error: {last_err}")
