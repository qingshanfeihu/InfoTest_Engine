"""
DashScope qwen-plus chat completions client with structured JSON output.

Uses the OpenAI-compatible endpoint; requires DASHSCOPE_API_KEY.
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
DASHSCOPE_CHAT_URL = f"{DASHSCOPE_COMPAT_BASE}/chat/completions"
CHAT_MODEL = "qwen-plus"
DEFAULT_MAX_TOKENS = 8192
DEFAULT_TEMPERATURE = 0.1
DEFAULT_TOP_P = 0.1
REQUEST_TIMEOUT = 180


class TruncationError(Exception):
    """Raised when LLM output is truncated (finish_reason == 'length')."""


class ChatCompletionError(Exception):
    """Raised on non-retryable chat completion failures."""


def chat_completion(
    session: requests.Session,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = DEFAULT_TEMPERATURE,
    top_p: float = DEFAULT_TOP_P,
    max_retries: int = 3,
) -> dict[str, Any]:
    """Call qwen-plus and return parsed JSON dict.

    Raises TruncationError if output was truncated.
    Raises ChatCompletionError on persistent failures.
    """
    cache = _get_llm_cache()
    if cache is not None:
        cached = cache.get(
            system=system_prompt,
            user=user_prompt,
            model=CHAT_MODEL,
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
        "model": CHAT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
    }

    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            r = session.post(
                DASHSCOPE_CHAT_URL,
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
            content = choice["message"]["content"]

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

            result = json.loads(content)
            if cache is not None:
                cache.put(
                    result=result,
                    system=system_prompt,
                    user=user_prompt,
                    model=CHAT_MODEL,
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
