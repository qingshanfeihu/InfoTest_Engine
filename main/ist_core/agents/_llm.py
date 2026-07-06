"""Agent 层 LLM 工厂.

统一走 OpenAI 兼容端点（``OPENAI_BASE_URL`` / ``OPENAI_API_KEY``）——任何 OpenAI
协议端点皆可：小米 MiMo / DeepSeek 原生口 / DashScope 兼容口 / 自建网关。不再做
provider 分支：要换厂商只改 ``OPENAI_BASE_URL`` + key + ``IST_MODEL``。
共享 ``ChatOpenAIWithReasoning`` 子类，处理 ``reasoning_content`` 双向 patch
（思考模式 multi-turn tool_call 要求回填历史 reasoning_content）。
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any


logger = logging.getLogger(__name__)

DEFAULT_OPENAI_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
DEFAULT_IST_MODEL = "mimo-v2.5-pro"
DEFAULT_HAIKU_MODEL = "mimo-v2.5"   # 兼容别名(旧 env/调用面);新代码用 DEFAULT_FLASH_MODEL
DEFAULT_FLASH_MODEL = "deepseek-v4-flash"

# 默认请求超时 / 重试。streaming 模式下端点中途 stall 时，没有 timeout
# 会无限挂（TUI 永远转圈、无报错）。可用 env 覆盖。
# 300s：开思考（IST_THINKING=on）单次响应常 >120s——重推理 case（如 rr 轮转）第一次思考
# 就可能过 120s，被 request_timeout 砍、ai_rounds=0 不出 xlsx。给长思考留足时间。
DEFAULT_REQUEST_TIMEOUT = 300.0
DEFAULT_MAX_RETRIES = 2


def _sanitize_dangling_tool_calls(msgs: list) -> int:
    """OpenAI dict 消息序列消毒:assistant.tool_calls 的每个 id 必须被紧随的连续
    tool 消息段回应——缺的**原地插入**占位 tool 消息,返回补的条数。

    根因(2026-07-05 dongkl 死锁):摘要边界把 assistant(tool_calls) 与 tool 回应
    切开后,供应商每轮 400(insufficient tool messages following tool_calls),
    上层吞成零响应,会话锁死。此处是请求发出前的最终形态,上游怎么切都兜得住。
    """
    i = 0
    fixed = 0
    while i < len(msgs):
        m = msgs[i] if isinstance(msgs[i], dict) else {}
        calls = m.get("tool_calls") or [] if m.get("role") == "assistant" else []
        if not calls:
            i += 1
            continue
        j = i + 1
        answered: set[str] = set()
        while j < len(msgs) and isinstance(msgs[j], dict) and msgs[j].get("role") == "tool":
            answered.add(str(msgs[j].get("tool_call_id")))
            j += 1
        missing = [c for c in calls
                   if str((c or {}).get("id")) not in answered]
        for k, c in enumerate(missing):
            msgs.insert(j + k, {
                "role": "tool",
                "tool_call_id": str((c or {}).get("id") or "unknown"),
                "content": "[该工具调用被会话历史截断,没有产生结果;如果它仍然必要,重新发起。]",
            })
            fixed += 1
        i = j + len(missing)
    return fixed


def _resolve_timeout_retries() -> tuple[float, int]:
    """从 env 解析 (request_timeout 秒, max_retries)；非法值回退默认。"""
    try:
        timeout = float(os.environ.get("IST_LLM_TIMEOUT") or DEFAULT_REQUEST_TIMEOUT)
    except (TypeError, ValueError):
        timeout = DEFAULT_REQUEST_TIMEOUT
    try:
        retries = int(os.environ.get("IST_LLM_MAX_RETRIES") or DEFAULT_MAX_RETRIES)
    except (TypeError, ValueError):
        retries = DEFAULT_MAX_RETRIES
    return timeout, retries


def _resolve_streaming() -> bool:
    """是否用流式请求。默认 True（TUI astream_events 需要）；``IST_LLM_STREAMING=0`` 关。

    关流式用于**不稳定端点**的批量 agent 跑（如 print 模式跑编译流水线）：某些 OpenAI 兼容
    网关流式会周期性发空 chunk、令 httpx 每 chunk 重置读超时 → 整体响应永不完成也永不超时
    （观测到 0% CPU 死挂）。非流式是单次请求 + 干净的整体 request_timeout，遇 stall 会按时
    超时重试，不会无限挂。
    """
    return (os.environ.get("IST_LLM_STREAMING") or "1").strip().lower() not in (
        "0", "false", "off", "no",
    )


def resolve_llm_base_url() -> str:
    """OpenAI 兼容 API 根；留空走默认 MiMo CN 集群。"""
    return (os.environ.get("OPENAI_BASE_URL") or DEFAULT_OPENAI_BASE_URL).strip()


def resolve_llm_api_key() -> str:
    """OpenAI 兼容 API key（``OPENAI_API_KEY``）。"""
    return (os.environ.get("OPENAI_API_KEY") or "").strip()


def _resolve_endpoint() -> tuple[str, str]:
    """解析 ``(base_url, api_key)``；无 key 时 raise。单一事实源。"""
    base_url = resolve_llm_base_url()
    api_key = resolve_llm_api_key()
    if not api_key:
        raise RuntimeError("需要 OPENAI_API_KEY（OpenAI 兼容端点）")
    return base_url, api_key


def _build_chat_model(model_name: str, effort: str = "", **kwargs: Any):
    """统一的 ChatOpenAI 工厂（OpenAI 兼容端点）。"""
    try:
        from langchain_openai import ChatOpenAI  # noqa: F401  type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("LLM 工厂需要 `pip install langchain-openai`") from exc

    extra_body = dict(kwargs.pop("extra_body", None) or {})
    base_url, api_key = _resolve_endpoint()

    # 深度思考显式锁定(不再靠端点默认,防默认变更)。thinking 参数的 **schema 随模型族**
    # (mimo/deepseek=enabled/disabled;minimax=adaptive/disabled——实证同一网关下取值不同,
    # 按 URL 判定必 400),故按模型名族注入;未知族不注入(端点默认,绝不赌 400)。
    # IST_THINKING=on|off 控制;默认 on。已显式传 extra_body.thinking 的不覆盖。
    if "thinking" not in extra_body:
        from main.common.llm_helpers import thinking_param_for_model
        _think = (os.environ.get("IST_THINKING") or "on").strip().lower()
        _on = _think in ("on", "1", "true", "enabled")
        _param = thinking_param_for_model(model_name, _on)
        if _param is not None:
            extra_body["thinking"] = _param

    # 思考深度 reasoning_effort(2026-07-06):deepseek 族支持 high|max,平台默认 high
    # (34-case 实跑对照:max 无更好表现、只多烧 token——2026-07-06 用户拍板降回;
    # IST_EFFORT=max 可全局升,或 effort= 按调用点覆盖——fork 经 agents md frontmatter
    # 的 effort: 字段)。仅思考开启且 deepseek 族注入,其他族支持面未证实、不赌 400;
    # 非法值按 high 处理。
    if ("reasoning_effort" not in extra_body
            and extra_body.get("thinking", {}).get("type") in ("enabled", "adaptive")):
        _fam = (model_name or "").lower().rpartition("/")[-1]
        if _fam.startswith("deepseek"):
            _eff = (effort or os.environ.get("IST_EFFORT") or "high").strip().lower()
            extra_body["reasoning_effort"] = _eff if _eff in ("high", "max") else "high"

    # 深度思考开启(enabled/adaptive)时端点多强制自家采样参数、不接受自定义(如 mimo 官方
    # deep-thinking 页)。再发 0.0/0.5 是冗余,且可能触发端点告警或被静默忽略。仅未开 thinking
    # 时设确定性默认采样。
    if extra_body.get("thinking", {}).get("type") not in ("enabled", "adaptive"):
        kwargs.setdefault("temperature", 0.0)
        kwargs.setdefault("top_p", 0.5)
    _stream = _resolve_streaming()
    kwargs.setdefault("streaming", _stream)
    kwargs.setdefault("stream_usage", _stream)
    # 关流式时强制 disable_streaming=True：仅 streaming=False 挡不住 TUI 的 astream_events(version="v2")——
    # 后者会让 model 走流式 HTTP 拉 token 事件、覆盖 streaming=False。disable_streaming=True 才真把 astream
    # 退化成非流式 invoke。否则开思考(IST_THINKING=on)时 mimo 长响应 + 流式 HTTP 撞网关周期性空 chunk →
    # httpx 每 chunk 重置读超时 → 0% CPU 死挂(永不完成也永不超时)。这是 TUI 模式开思考的死挂根因。
    if not _stream:
        kwargs.setdefault("disable_streaming", True)
    timeout, retries = _resolve_timeout_retries()
    kwargs.setdefault("request_timeout", timeout)
    kwargs.setdefault("max_retries", retries)
    kwargs["extra_body"] = extra_body

    cls = _get_chat_openai_with_reasoning()
    logger.info(
        "LLM: model=%s base_url=%s timeout=%ss retries=%s",
        model_name, base_url, timeout, retries,
    )
    return cls(model=model_name, base_url=base_url, api_key=api_key, **kwargs)


def build_agent_chat_model(**kwargs: Any):
    """主 LLM 工厂。模型取 ``IST_MODEL``;``effort=`` 可按调用点覆盖思考深度(high/max)。"""
    model_name = (
        kwargs.pop("model", None)
        or os.environ.get("IST_MODEL")
        or DEFAULT_IST_MODEL
    ).strip()
    return _build_chat_model(model_name, **kwargs)


def build_explore_model(**kwargs: Any):
    """Explore sub-agent：flash 档模型，快速低成本检索。

    走 OpenAI 兼容端点；模型取 ``IST_FLASH``(兼容回落旧 IST_HAIKU_MODEL)。
    所有 streaming / timeout / thinking 逻辑复用 ``_build_chat_model``。
    """
    return _build_chat_model(ist_core_flash_model(), **kwargs)


def _reasoning_from_raw(raw_chunk_dict) -> str | None:
    """从 raw stream chunk dict 取 delta.reasoning_content（思考增量），无则 None。"""
    try:
        choices = raw_chunk_dict.get("choices") or raw_chunk_dict.get("chunk", {}).get("choices") or []
        if not choices:
            return None
        delta = choices[0].get("delta") or {}
        rc = delta.get("reasoning_content") or delta.get("reasoning")
        return rc if isinstance(rc, str) and rc else None
    except Exception:  # noqa: BLE001
        return None


def _patch_chunk_with_reasoning(chunk, raw_chunk_dict) -> None:
    """把 raw_chunk['choices'][0]['delta']['reasoning_content'] 拷到 chunk.message.additional_kwargs."""
    if chunk is None:
        return
    rc = _reasoning_from_raw(raw_chunk_dict)
    if not rc:
        return
    try:
        msg = getattr(chunk, "message", None)
        if msg is None:
            return
        if not hasattr(msg, "additional_kwargs") or msg.additional_kwargs is None:
            msg.additional_kwargs = {}
        msg.additional_kwargs["reasoning_content"] = rc
    except Exception:  # noqa: BLE001
        pass


_CHAT_OPENAI_REASONING_CLS: Any = None


def _get_chat_openai_with_reasoning():
    """延迟构造的 ChatOpenAI 子类（首次调用时构造）。"""
    global _CHAT_OPENAI_REASONING_CLS
    if _CHAT_OPENAI_REASONING_CLS is not None:
        return _CHAT_OPENAI_REASONING_CLS

    from langchain_openai import ChatOpenAI  # type: ignore[import-not-found]

    def _is_thinking_param_rejection(exc: BaseException) -> bool:
        """端点拒绝 ``thinking`` 参数的错误特征（借鉴 cc-switch thinking_rectifier 的
        错误驱动整流模式：列举已知拒绝文案特征，命中才整流，绝不过宽）。

        实证样本：minimax "invalid params, invalid thinking.type: \\"enabled\\"
        (allowed: adaptive, disabled)"；其他端点常见 "unknown parameter: thinking" /
        "extra inputs are not permitted"。
        """
        s = str(exc).lower()
        if "thinking" not in s:
            return False
        return any(k in s for k in (
            "invalid", "not permitted", "unknown parameter", "unsupported",
            "unexpected", "allowed:",
        ))

    class ChatOpenAIWithReasoning(ChatOpenAI):
        """ChatOpenAI 子类，双向支持 reasoning_content（DeepSeek 多轮 + qwen 流式）.

        入方向（响应）：override ``_convert_chunk_to_generation_chunk`` 把
        ``delta.reasoning_content`` 拷到 ``message.additional_kwargs``。
        参考 langchain-ai/langchain issue #33672。

        工具绑定：override ``bind_tools`` 支持 ``IST_TOOLS_STRICT=1`` 时统一开
        function-calling strict 模式——schema 强约束治供应商把数组参数
        stringify/在长字符串参数后拖尾（emit steps_json 实证单轮 73% 解析失败；
        footprint extractor 的 strict 先例见 memory/footprint/extractor.py）。
        strict 只支持 JSON schema 子集（additionalProperties:false、全字段
        required、可选字段 ["type","null"]），对所有工具 schema 生效，故默认关、
        A/B 验证供应商兼容性后再考虑默认开。

        出方向（请求）：override ``_get_request_payload`` 把上一轮 AIMessage
        的 ``additional_kwargs["reasoning_content"]`` 注入回 assistant payload
        dict 的同名 sibling 字段——DeepSeek thinking 模式下 multi-turn
        tool_call 要求这个字段必须保留，否则 400 "reasoning_content must be
        passed back"。BaseChatOpenAI 的 ``_convert_message_to_dict`` 默认会
        丢非标准 additional_kwargs，langchain issue #37178 仍 Open，无官方
        修复，所以在子类层面打补丁。
        """

        # ── minimax `<think>` 内联剥离 ─────────────────────────────────────────
        # minimax 系把思考以 ``<think>...</think>`` 内联在 content（非 reasoning_content
        # 字段）。不剥离的话：思考文本被当正文渲染（⏺ 块）、进多轮上下文污染、且"纯思考
        # 响应"被 agent 判为最终答复提前收口。这里把 think 段转入 reasoning_content 通道
        # ——与 mimo/deepseek 对齐后，TUI 思考渲染/回传链路原样复用。
        # 流式用实例级状态机（think 段跨多个 chunk）；标签本身跨 chunk 切割的场景极罕见
        # （<think> 通常是模板特殊 token 整块到达），不做部分标签缓冲。
        def bind_tools(self, tools, **kwargs):
            # IST_TOOLS_STRICT=1 → 统一 strict 绑定(见类 docstring;默认关)。
            if os.environ.get("IST_TOOLS_STRICT", "0") == "1":
                kwargs.setdefault("strict", True)
            return super().bind_tools(tools, **kwargs)

        def _split_think_inline(self, text: str) -> tuple[str, str]:
            """按 <think>/</think> 状态机切分 (正文, 思考)；状态存 self._mm_in_think。"""
            if not text:
                return "", ""
            out, reason = [], []
            buf = text
            while buf:
                if getattr(self, "_mm_in_think", False):
                    j = buf.find("</think>")
                    if j < 0:
                        reason.append(buf); buf = ""
                    else:
                        reason.append(buf[:j]); buf = buf[j + 8:]
                        self._mm_in_think = False
                else:
                    i = buf.find("<think>")
                    if i < 0:
                        out.append(buf); buf = ""
                    else:
                        out.append(buf[:i]); buf = buf[i + 7:]
                        self._mm_in_think = True
            return "".join(out), "".join(reason)

        def _convert_chunk_to_generation_chunk(
            self, chunk, default_chunk_class, base_generation_info
        ):
            gen_chunk = super()._convert_chunk_to_generation_chunk(
                chunk, default_chunk_class, base_generation_info
            )
            if gen_chunk is not None:
                msg = getattr(gen_chunk, "message", None)
                if msg is not None and isinstance(getattr(msg, "content", None), str) \
                        and ("<think>" in msg.content or "</think>" in msg.content
                             or getattr(self, "_mm_in_think", False)):
                    body, reason = self._split_think_inline(msg.content)
                    msg.content = body
                    if reason:
                        if getattr(msg, "additional_kwargs", None) is None:
                            msg.additional_kwargs = {}
                        prev = msg.additional_kwargs.get("reasoning_content") or ""
                        msg.additional_kwargs["reasoning_content"] = prev + reason
            if isinstance(chunk, dict):
                if gen_chunk is not None:
                    _patch_chunk_with_reasoning(gen_chunk, chunk)
                else:
                    # mimo 深度思考期的 reasoning chunk 是 content=null 的纯思考增量，
                    # super() 视其为空 delta 返回 None → 会被丢弃：思考无法流式，footer 也
                    # 无从得知 mimo 此刻真在思考。若该 chunk 带 reasoning_content，构造一个
                    # 空 content + reasoning 的 gen chunk 保住它，让思考 delta 上抛为流式事件
                    # （reducer 据此置 thinking 相位 + 逐字渲染；最终消息里 reasoning 也不丢）。
                    rc = _reasoning_from_raw(chunk)
                    if rc:
                        from langchain_core.messages import AIMessageChunk  # noqa: PLC0415
                        from langchain_core.outputs import ChatGenerationChunk  # noqa: PLC0415
                        gen_chunk = ChatGenerationChunk(
                            message=AIMessageChunk(
                                content="", additional_kwargs={"reasoning_content": rc}
                            )
                        )
            return gen_chunk

        def _get_request_payload(self, input_, *, stop=None, **kwargs):
            payload = super()._get_request_payload(input_, stop=stop, **kwargs)
            # 悬空 tool_calls 消毒(最终 payload 层,2026-07-05 dongkl 死锁取证):
            # 摘要/剪枝等上游中间件可能把 assistant(tool_calls) 与其 tool 回应切开
            # ——OpenAI 兼容供应商对此一律 400,错误被吞成「零响应」,会话每轮 400
            # 死锁。外层 middleware 修不到摘要后的视图(实证 sanitize→summarization
            # →LLM 的洋葱顺序),只有这里是发出前的最终形态。
            try:
                _fixed = _sanitize_dangling_tool_calls(payload.get("messages") or [])
                if _fixed:
                    logger.warning("payload 消毒: 补 %d 条悬空 tool_call 占位回应", _fixed)
            except Exception:  # noqa: BLE001 — 消毒绝不挂请求
                logger.debug("payload 消毒失败(放行原文)", exc_info=True)
            try:
                from langchain_core.messages import AIMessage  # noqa: PLC0415

                originals = input_ if isinstance(input_, list) else []
                ai_iter = iter(
                    m for m in originals if isinstance(m, AIMessage)
                )
                injected = 0
                rc_total_chars = 0
                for msg_dict in payload.get("messages", []):
                    if msg_dict.get("role") != "assistant":
                        continue
                    src = next(ai_iter, None)
                    if src is None:
                        break
                    rc = (src.additional_kwargs or {}).get("reasoning_content")
                    if rc:
                        msg_dict["reasoning_content"] = rc
                        injected += 1
                        rc_total_chars += len(rc)
                if os.environ.get("IST_DEBUG_PAYLOAD") == "1":
                    import json as _json  # noqa: PLC0415
                    payload_size = len(_json.dumps(payload, ensure_ascii=False))
                    msg_count = len(payload.get("messages", []))
                    logger.warning(
                        "[deepseek payload] msgs=%d size=%dKB rc_injected=%d rc_chars=%d",
                        msg_count, payload_size // 1024, injected, rc_total_chars,
                    )
            except Exception as exc:  # noqa: BLE001
                if os.environ.get("IST_DEBUG_PAYLOAD") == "1":
                    logger.warning("[deepseek payload patch err] %s", exc)
            return payload

        def _create_chat_result(self, response, generation_info=None):
            """非流式路径的 reasoning_content 收取。

            ``_convert_chunk_to_generation_chunk`` 只在【流式 chunk】触发；当
            ``IST_LLM_STREAMING=0`` 或用 ``.invoke()`` 非流式调用时走 ``_generate``→
            ``_create_chat_result``,若不在这里收,``reasoning_content`` 永远进不了
            ``additional_kwargs`` → 出方向 ``_get_request_payload`` 回传时拿不到 →
            mimo/DeepSeek thinking 多轮 tool_call 报 400 "reasoning_content must be
            passed back",或上下文不完整导致指令遵循下降、幻觉增多。流式/非流式两条
            收取路径都打补丁,reasoning_content 才不会因开/关流式而丢。
            """
            result = super()._create_chat_result(response, generation_info)
            try:
                resp = response if isinstance(response, dict) else (
                    response.model_dump() if hasattr(response, "model_dump") else {})
                choices = resp.get("choices") or []
                for gen, choice in zip(result.generations, choices):
                    msg = (choice or {}).get("message") or {}
                    rc = msg.get("reasoning_content") or msg.get("reasoning")
                    gm = getattr(gen, "message", None)
                    if rc and gm is not None:
                        if getattr(gm, "additional_kwargs", None) is None:
                            gm.additional_kwargs = {}
                        gm.additional_kwargs["reasoning_content"] = rc
                    # minimax <think> 内联(非流式整段)：剥入 reasoning_content 通道
                    if gm is not None and isinstance(getattr(gm, "content", None), str) \
                            and "<think>" in gm.content:
                        self._mm_in_think = False
                        body, reason = self._split_think_inline(gm.content)
                        gm.content = body
                        if reason:
                            if getattr(gm, "additional_kwargs", None) is None:
                                gm.additional_kwargs = {}
                            prev = gm.additional_kwargs.get("reasoning_content") or ""
                            gm.additional_kwargs["reasoning_content"] = prev + reason
            except Exception:  # noqa: BLE001
                pass
            return result

        # ── thinking 参数整流重试（cc-switch rectifier 模式）────────────────────
        # 模型族表(thinking_param_for_model)是快路径;端点仍拒 thinking 参数时(表错/
        # 未知网关方言),按错误文案特征命中 → 移除 thinking → 立即重试一次,并把
        # self.extra_body 就地降级(本会话后续请求不再带)——永不因参数方言空转。
        def _drop_thinking_param(self, exc: BaseException) -> bool:
            eb = dict(self.extra_body or {})
            if "thinking" not in eb:
                return False
            dropped = eb.pop("thinking")
            self.extra_body = eb
            logger.warning(
                "端点拒绝 thinking 参数(%s)——已移除 %s 并重试;本会话后续请求降级不再携带",
                str(exc)[:140], dropped,
            )
            return True

        def _generate(self, *args, **kwargs):
            try:
                return super()._generate(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                if _is_thinking_param_rejection(exc) and self._drop_thinking_param(exc):
                    return super()._generate(*args, **kwargs)
                raise

        async def _agenerate(self, *args, **kwargs):
            try:
                return await super()._agenerate(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                if _is_thinking_param_rejection(exc) and self._drop_thinking_param(exc):
                    return await super()._agenerate(*args, **kwargs)
                raise

        @staticmethod
        def _chunk_has_substance(ch) -> bool:
            """chunk 是否携带实质进度:正文/思考增量、tool_call 增量、或 usage 收尾帧。
            网关的 keep-alive 空 chunk 全不带这些——它骗得过 httpx 读超时(每 chunk 重置),
            骗不过这里。"""
            try:
                m = ch.message
            except Exception:  # noqa: BLE001
                return True   # 结构不明就当有进度,守卫绝不误杀正常流
            if getattr(m, "content", None):
                return True
            if getattr(m, "tool_call_chunks", None):
                return True
            if getattr(m, "usage_metadata", None):
                return True
            ak = getattr(m, "additional_kwargs", None) or {}
            return bool(ak.get("reasoning_content") or ak.get("tool_calls"))

        def _stall_deadline_s(self) -> float:
            """连续零实质内容的容忍秒数;0=关守卫。挂流实证(2026-07-04 V轮):思考/输出
            增量冻结 15-45 分钟,期间仅 keep-alive 空 chunk,httpx 读超时被逐个重置永不触发。
            正常深度思考期间 reasoning_content 持续有增量,不会命中。"""
            try:
                return float(os.environ.get("IST_LLM_STALL_TIMEOUT") or 180.0)
            except (TypeError, ValueError):
                return 180.0

        def _stream(self, *args, **kwargs):
            import time as _time
            yielded = False
            substantive = False
            stall_s = self._stall_deadline_s()
            last_progress = _time.monotonic()
            try:
                for ch in super()._stream(*args, **kwargs):
                    yielded = True
                    if self._chunk_has_substance(ch):
                        substantive = True
                        last_progress = _time.monotonic()
                    elif stall_s > 0 and _time.monotonic() - last_progress > stall_s:
                        logger.warning(
                            "LLM 流实质内容停滞 >%ss(仅 keep-alive 空 chunk),主动断流"
                            "(substantive=%s)", stall_s, substantive)
                        raise TimeoutError(
                            f"stream stalled: 连续 {stall_s}s 无实质内容(空 chunk 保活)")
                    yield ch
            except Exception as exc:  # noqa: BLE001
                # 参数拒绝发生在建流前(首 chunk 前 4xx);已吐过 chunk 说明不是参数问题,不重试防重复内容
                if (not yielded and _is_thinking_param_rejection(exc)
                        and self._drop_thinking_param(exc)):
                    for ch in super()._stream(*args, **kwargs):
                        yield ch
                # 停滞发生在任何实质内容之前 → 上游没消费到任何东西,从头重发一次是安全的
                elif isinstance(exc, TimeoutError) and not substantive:
                    logger.warning("LLM 流零内容停滞,安全重发一次")
                    for ch in super()._stream(*args, **kwargs):
                        yield ch
                else:
                    raise

        async def _astream(self, *args, **kwargs):
            import time as _time
            yielded = False
            substantive = False
            stall_s = self._stall_deadline_s()
            last_progress = _time.monotonic()
            try:
                async for ch in super()._astream(*args, **kwargs):
                    yielded = True
                    if self._chunk_has_substance(ch):
                        substantive = True
                        last_progress = _time.monotonic()
                    elif stall_s > 0 and _time.monotonic() - last_progress > stall_s:
                        logger.warning(
                            "LLM 流实质内容停滞 >%ss(仅 keep-alive 空 chunk),主动断流"
                            "(substantive=%s)", stall_s, substantive)
                        raise TimeoutError(
                            f"stream stalled: 连续 {stall_s}s 无实质内容(空 chunk 保活)")
                    yield ch
            except Exception as exc:  # noqa: BLE001
                if (not yielded and _is_thinking_param_rejection(exc)
                        and self._drop_thinking_param(exc)):
                    async for ch in super()._astream(*args, **kwargs):
                        yield ch
                elif isinstance(exc, TimeoutError) and not substantive:
                    logger.warning("LLM 流零内容停滞,安全重发一次")
                    async for ch in super()._astream(*args, **kwargs):
                        yield ch
                else:
                    raise

    _CHAT_OPENAI_REASONING_CLS = ChatOpenAIWithReasoning
    return ChatOpenAIWithReasoning


def ist_core_default_model() -> str:
    """平台主档模型:``IST_MODEL`` 单源(2026-07-06 配置收敛:与旧 IST_REVIEW_MODEL/
    IST_OPUS_MODEL/IST_SONNET_MODEL 合并,后两者不再读取;IST_REVIEW_MODEL 保留为
    兼容 fallback,仅在 IST_MODEL 缺省的旧环境里生效)。"""
    return (
        os.environ.get("IST_MODEL")
        or os.environ.get("IST_REVIEW_MODEL")
        or DEFAULT_IST_MODEL
    ).strip()








# 两档收敛(2026-07-06):主档=IST_MODEL(pro,全局默认),省钱档=IST_FLASH。
# 旧三档词汇保留为别名:opus/sonnet→主档;haiku→flash。fork md 的 model: 标注不用改。
_FLASH_TIERS = frozenset({"flash", "haiku"})


def ist_core_flash_model() -> str:
    """省钱档模型:``IST_FLASH``(缺省回落旧 IST_HAIKU_MODEL,再回落 deepseek-v4-flash)。
    与主档同样开思考(effort 同规则),只为降低 token 单价。"""
    return (
        os.environ.get("IST_FLASH")
        or os.environ.get("IST_HAIKU_MODEL")
        or DEFAULT_FLASH_MODEL
    ).strip()


def ist_core_tier_model(tier: str) -> str:
    """Return the configured model for ``tier``(flash/haiku → IST_FLASH;其余 → IST_MODEL)."""
    if (tier or "").lower() in _FLASH_TIERS:
        return ist_core_flash_model()
    return ist_core_default_model()


def ist_core_select_model_for_task(task_complexity: str) -> str:
    """根据任务复杂度自动选 tier 模型.

    ``task_complexity``:
      - "high" / "review" → opus tier
      - "medium" / "qa" → sonnet tier
      - "low" / "completion" → haiku tier
    """
    tier_map = {
        "high": "opus", "review": "opus",
        "medium": "sonnet", "qa": "sonnet",
        "low": "haiku", "completion": "haiku",
    }
    tier = tier_map.get(task_complexity.lower(), "sonnet")
    return ist_core_tier_model(tier)


def ist_core_allowed_models() -> list[str]:
    """Return allowed reviewer models from ``IST_ALLOWED_MODELS``.

    Comma-separated whitelist for the ``/model`` slash command. When unset,
    only the current default model is selectable.
    """
    raw = (os.environ.get("IST_ALLOWED_MODELS") or "").strip()
    if raw:
        models = [item.strip() for item in raw.split(",") if item.strip()]
    else:
        models = [ist_core_default_model()]
    return list(dict.fromkeys(models))


def validate_review_model(model_name: str | None) -> str:
    """Return an environment-allowed reviewer model name or raise."""
    model = (model_name or ist_core_default_model()).strip()
    allowed = ist_core_allowed_models()
    if model not in allowed:
        raise ValueError(
            f"unsupported review model {model!r}; configure IST_ALLOWED_MODELS; allowed={allowed}"
        )
    return model


@contextmanager
def ist_core_model_override(model_name: str | None):
    """Temporarily route all QA reviewer model factories to a concrete model."""
    model = validate_review_model(model_name)
    old = os.environ.get("IST_MODEL")
    os.environ["IST_MODEL"] = model
    try:
        yield model
    finally:
        if old is None:
            os.environ.pop("IST_MODEL", None)
        else:
            os.environ["IST_MODEL"] = old
