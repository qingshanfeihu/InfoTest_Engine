"""自适应并发限流器(AIMD) + transient 端点错误判定。"""

from __future__ import annotations

import threading

from main.ist_core.resilience import AdaptiveLimiter, is_transient_error


def test_transient_detection():
    # 流中断 / 限流 / 过载 / 连接抖动 → transient
    assert is_transient_error("ERROR: httpx.RemoteProtocolError: peer closed connection without sending complete message body")
    assert is_transient_error("ERROR: 429 Too Many Requests")
    assert is_transient_error("ERROR: rate limit exceeded")
    assert is_transient_error("ERROR: model overloaded")
    assert is_transient_error("ERROR: Connection reset by peer")
    assert is_transient_error(Exception("incomplete chunked read"))
    # 业务/质量错误 → 不是 transient（不该触发降并发重试）
    assert not is_transient_error("ERROR: case 没有任何 check_point 步骤")
    assert not is_transient_error("CUT: 断言没咬住需求行为")
    assert not is_transient_error("")


def test_aimd_decrease_on_overload():
    lim = AdaptiveLimiter(start=8, min_limit=1, max_limit=16)
    lim.record_overload()
    assert lim.current == 4          # 乘性减半
    lim.record_overload()
    assert lim.current == 2
    lim.record_overload(); lim.record_overload()
    assert lim.current == 1          # 触底 min，不再降


def test_aimd_increase_on_success():
    lim = AdaptiveLimiter(start=2, min_limit=1, max_limit=4)
    # 加性增：连续成功数 ≥ 当前 limit 才 +1
    lim.record_success(); lim.record_success()   # 2 次 → limit 2→3
    assert lim.current == 3
    lim.record_success(); lim.record_success(); lim.record_success()  # 3 次 → 3→4
    assert lim.current == 4
    for _ in range(10):
        lim.record_success()
    assert lim.current == 4           # 封顶 max，不超


def test_acquire_release_caps_concurrency():
    lim = AdaptiveLimiter(start=2, min_limit=1, max_limit=4)
    peak = {"n": 0}
    cur = {"n": 0}
    lock = threading.Lock()

    def work():
        with lim:
            with lock:
                cur["n"] += 1
                peak["n"] = max(peak["n"], cur["n"])
            import time
            time.sleep(0.05)
            with lock:
                cur["n"] -= 1

    threads = [threading.Thread(target=work) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak["n"] <= 2             # 并发不超过 limit
