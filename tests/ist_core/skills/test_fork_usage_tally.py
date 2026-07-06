"""fork usage 计量:显式 callback 即时计(替代末态 messages 直计)。

旧直计从 fork 末态 messages 累加 usage_metadata——摘要压缩撤史/transient 重试/
看门狗超时的用量全不进账,系统性偏小(与 DeepSeek 官方按请求计量对不上,2026-07-06
用户实证)。现 _ForkUsageTally 挂 fork invoke config,每次 on_llm_end 取 API 真实
usage(经 graph.extract_llm_usage,含 cache 命中),不依赖 callback 传播。
"""
from main.ist_core.graph import extract_llm_usage
from main.ist_core.skills import loader


class _Msg:
    def __init__(self, um):
        self.usage_metadata = um


class _Gen:
    def __init__(self, um):
        self.message = _Msg(um)


class _Resp:
    def __init__(self, um, llm_output=None):
        self.generations = [[_Gen(um)]]
        self.llm_output = llm_output or {}


def test_extract_llm_usage_merges_deepseek_cache_fields():
    r = _Resp({"input_tokens": 1000, "output_tokens": 50, "total_tokens": 1050},
              llm_output={"token_usage": {"prompt_cache_hit_tokens": 800,
                                          "prompt_cache_miss_tokens": 200}})
    u = extract_llm_usage(r)
    assert u["input_tokens"] == 1000 and u["output_tokens"] == 50
    assert u["prompt_cache_hit_tokens"] == 800
    assert u["prompt_cache_miss_tokens"] == 200


def test_extract_llm_usage_openai_cached_tokens_detail():
    r = _Resp({"input_tokens": 500, "output_tokens": 20},
              llm_output={"token_usage": {"prompt_tokens": 500,
                                          "prompt_tokens_details": {"cached_tokens": 300}}})
    u = extract_llm_usage(r)
    assert u["prompt_cache_hit_tokens"] == 300
    assert u["prompt_cache_miss_tokens"] == 200


def test_fork_usage_tally_accumulates_per_call_with_cache():
    loader.reset_fork_tokens()
    tally = loader._ForkUsageTally()
    # 两次 LLM 调用(agentic 两轮),第二轮 prompt 更大——按请求逐次计,不看末态
    tally.on_llm_end(_Resp({"input_tokens": 1000, "output_tokens": 40},
                           llm_output={"token_usage": {"prompt_cache_hit_tokens": 600}}))
    tally.on_llm_end(_Resp({"input_tokens": 1500, "output_tokens": 60},
                           llm_output={"token_usage": {"prompt_cache_hit_tokens": 1400}}))
    fin, fout, fhit = loader.get_fork_tokens()
    assert (fin, fout, fhit) == (2500, 100, 2000)
    loader.reset_fork_tokens()


def test_fork_usage_tally_other_callbacks_are_noop():
    tally = loader._ForkUsageTally()
    tally.on_tool_start(None, "x")          # 不抛
    tally.on_chat_model_start(None, None)   # 不抛
