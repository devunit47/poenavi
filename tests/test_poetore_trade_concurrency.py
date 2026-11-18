from concurrent.futures import Future, ThreadPoolExecutor
import json
import threading
import time
from types import SimpleNamespace

import pytest

from src.poetore import trade


@pytest.fixture(autouse=True)
def isolate_requests(monkeypatch):
    lock, server_states = threading.Lock(), {}
    for name in ("_trade_rate_limiter", "_trade2_rate_limiter"):
        monkeypatch.setattr(trade, name, trade._TradeRateLimiter(lock, server_states))
    monkeypatch.setattr(trade, "_trade_response_cache", trade._TtlLruCache())


def response(payload=None, *, status=200, headers=None):
    return SimpleNamespace(status=status, headers=headers or {}, data=json.dumps(payload or {}).encode())


@pytest.mark.parametrize("api_path", ["trade", "trade2"])
def test_superseded_search_is_cancelled_before_sending(monkeypatch, api_path):
    def unexpected_request(*_args, **_kwargs):
        pytest.fail("A superseded generation sent a search")

    monkeypatch.setattr(trade._trade_http_pool, "request", unexpected_request)
    cancel = threading.Event()
    cancel.set()
    with trade.trade_search_scope(cancel), pytest.raises(trade.TradeSearchCancelled):
        trade._cached_request_json(f"https://www.pathofexile.com/api/{api_path}/search/Standard", {"query": {}})


@pytest.mark.parametrize("api_path", ["trade", "trade2"])
def test_new_search_sends_while_superseded_fetch_waits_for_quota(monkeypatch, api_path):
    root = f"https://www.pathofexile.com/api/{api_path}"
    limiter, _ = trade._rate_limit_context(f"{root}/fetch/first")
    monkeypatch.setattr(trade._trade_http_pool, "request", lambda *_args, **_kw: response())
    trade._cached_request_json(f"{root}/fetch/first")

    wait_entered = threading.Event()
    cancel = threading.Event()
    try_borrow = limiter.try_borrow
    sent = []

    def borrow(policy):
        wait = try_borrow(policy)
        if policy == "fetch" and wait > 0:
            wait_entered.set()
        return wait

    def request(_method, url, **_kwargs):
        sent.append(url)
        return response({"id": "latest"})

    def old_fetch():
        with trade.trade_search_scope(cancel):
            return trade._cached_request_json(f"{root}/fetch/second")

    monkeypatch.setattr(limiter, "try_borrow", borrow)
    monkeypatch.setattr(trade._trade_http_pool, "request", request)
    with ThreadPoolExecutor(max_workers=2) as pool:
        old = pool.submit(old_fetch)
        try:
            assert wait_entered.wait(1)
            latest = pool.submit(trade._cached_request_json, f"{root}/search/Standard", {"query": {}})
            assert latest.result(timeout=1)[0] == {"id": "latest"}
        finally:
            cancel.set()
        with pytest.raises(trade.TradeSearchCancelled):
            old.result(timeout=1)
    assert sent == [f"{root}/search/Standard"]


@pytest.mark.parametrize("api_path", ["trade", "trade2"])
def test_identical_inflight_request_is_shared_after_leader_is_superseded(monkeypatch, api_path):
    url = f"https://www.pathofexile.com/api/{api_path}/search/Standard"
    sent, release = threading.Event(), threading.Event()
    joined = threading.Event()
    old_cancel = threading.Event()
    calls = []

    class ObservedFuture(Future):
        def result(self, timeout=None):
            joined.set()
            return super().result(timeout)

    def request(*_args, **_kwargs):
        calls.append(True)
        sent.set()
        assert release.wait(2)
        return response({"id": "same"})

    def search(cancel):
        with trade.trade_search_scope(cancel):
            return trade._cached_request_json(url, {"query": {}}, prevent_queue=True)

    monkeypatch.setattr(trade, "Future", ObservedFuture)
    monkeypatch.setattr(trade._trade_http_pool, "request", request)
    with ThreadPoolExecutor(max_workers=2) as pool:
        previous = pool.submit(search, old_cancel)
        try:
            assert sent.wait(1)
            old_cancel.set()
            latest = pool.submit(search, threading.Event())
            assert joined.wait(1)
            assert not latest.done()
        finally:
            release.set()
        assert previous.result(timeout=1)[0] == {"id": "same"}
        assert latest.result(timeout=1) == ({"id": "same"}, {}, True)
    assert len(calls) == 1


def test_concurrent_fetches_reserve_every_advertised_window(monkeypatch):
    now = 0.0
    sent = []
    first_sent, release = threading.Event(), threading.Event()
    root = f"{trade.API_ROOT}/fetch/"
    headers = {
        "X-Rate-Limit-Policy": "shared-fetch",
        "X-Rate-Limit-Rules": "Ip,Account",
        "X-Rate-Limit-Ip": "2:1:10,2:8:20",
        "X-Rate-Limit-Ip-State": "0:1:0,0:8:0",
        "X-Rate-Limit-Account": "1:2:10",
        "X-Rate-Limit-Account-State": "0:2:0",
    }

    def sleep(seconds):
        nonlocal now
        now += seconds

    def request(_method, url, **_kwargs):
        sent.append((url, now))
        if len(sent) == 1:
            first_sent.set()
            assert release.wait(2)
        return response(headers=headers)

    monkeypatch.setattr(trade, "time", SimpleNamespace(monotonic=lambda: now, sleep=sleep))
    monkeypatch.setattr(trade._trade_http_pool, "request", request)
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(trade._request_json, root + "one")
        try:
            assert first_sent.wait(1)
            others = [pool.submit(trade._request_json, root + name) for name in ("two", "three")]
        finally:
            release.set()
        for pending in (first, *others):
            pending.result(timeout=1)
    first, second, third = sorted(at for _url, at in sent)
    assert first == 0.0
    assert second - first >= 4.0 and third - second >= 4.0
    assert third - first >= 10.0


def test_429_blocks_new_requests_until_retry_after_and_shares_server_policy(monkeypatch):
    now = 100.0
    url = f"{trade.API_ROOT}/search/Standard"
    headers = {
        "X-Rate-Limit-Policy": "shared-search",
        "X-Rate-Limit-Rules": "Ip",
        "X-Rate-Limit-Ip": "3:1:10",
        "X-Rate-Limit-Ip-State": "3:1:15",
    }
    sent = []
    trade._trade2_rate_limiter.adjust("search", {
        **headers, "X-Rate-Limit-Ip-State": "0:1:0",
    })

    def request(*_args, **_kwargs):
        sent.append(now)
        if len(sent) == 1:
            return response(status=429, headers={**headers, "Retry-After": "25"})
        return response({"id": "resumed"})

    monkeypatch.setattr(trade, "time", SimpleNamespace(monotonic=lambda: now, sleep=time.sleep))
    monkeypatch.setattr(trade._trade_http_pool, "request", request)
    with pytest.raises(trade.TradeApiError, match="利用制限に達しました"):
        trade._cached_request_json(url, {"query": {}}, prevent_queue=True)
    assert trade._trade2_rate_limiter.estimate_wait("search") == 25.0
    now += 20.0
    with pytest.raises(trade.TradeApiError, match="約5秒後"):
        trade._cached_request_json(url, {"query": {}}, prevent_queue=True)
    assert sent == [100.0]
    now += 5.0
    assert trade._cached_request_json(url, {"query": {}}, prevent_queue=True)[0] == {"id": "resumed"}
    assert sent == [100.0, 125.0]
