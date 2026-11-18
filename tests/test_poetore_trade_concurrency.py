from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from email.utils import formatdate
import json
import threading
import time
from types import SimpleNamespace

import pytest
import urllib3

from src.poetore import trade


@pytest.fixture(autouse=True)
def isolate_requests(monkeypatch):
    traffic = trade._TradeRateLimitTraffic()
    for name in ("_trade_rate_limiter", "_trade2_rate_limiter"):
        monkeypatch.setattr(trade, name, trade._TradeRateLimiter(traffic))
    monkeypatch.setattr(trade, "_trade_response_cache", trade._TtlLruCache())


def response(payload=None, *, status=200, headers=None):
    return SimpleNamespace(status=status, headers=headers or {}, data=json.dumps(payload or {}).encode())


def ip_quota(maximum, active, *, policy="shared"):
    headers = {"X-Rate-Limit-Ip": f"{maximum}:10:0", "X-Rate-Limit-Ip-State": f"{active}:10:0"}
    if policy is not None:
        headers["X-Rate-Limit-Policy"] = policy
    return headers


@pytest.mark.parametrize("route_known", [False, True])
def test_unnamed_quota_blocks_other_routes_across_games(monkeypatch, route_known):
    now = 100.0
    search = f"{trade.API_ROOT}/search/Standard"
    fetch = "https://www.pathofexile.com/api/trade2/fetch/old"
    sent = []

    def sleep(seconds):
        nonlocal now
        now += seconds

    def request(_method, url, **_kwargs):
        sent.append((url, now))
        if url == search:
            return response(headers={
                **ip_quota(20, 1, policy=None),
                "X-Rate-Limit-Account": "1:10:0",
                "X-Rate-Limit-Account-State": "1:10:0",
            })
        return response()

    monkeypatch.setattr(trade, "time", SimpleNamespace(monotonic=lambda: now, sleep=sleep))
    monkeypatch.setattr(trade._trade_http_pool, "request", request)
    if route_known:
        trade._trade2_rate_limiter.adjust("fetch", ip_quota(20, 0, policy="poe2-fetch"))
    trade._request_json(search, {})
    assert trade._trade2_rate_limiter.estimate_wait("fetch") == 12.0
    trade._request_json(fetch)
    assert sent == [(search, 100.0), (fetch, 112.0)]
    assert trade._trade_rate_limiter.estimate_wait("search") == 12.0


def test_unnamed_rule_counts_other_responses_received_during_discovery(monkeypatch):
    now = 100.0
    monkeypatch.setattr(trade, "time", SimpleNamespace(monotonic=lambda: now))
    limiter = trade._trade_rate_limiter
    for endpoint in ("fetch", "search"):
        limiter.adjust(endpoint, ip_quota(10, 0, policy=endpoint))
    discovering = limiter.try_reserve("fetch")
    other = limiter.try_reserve("search")
    now = 101.0
    limiter.adjust("search", ip_quota(10, 1, policy="search"), reservation=other)
    now = 102.0
    limiter.adjust("fetch", ip_quota(2, 1, policy=None), reservation=discovering)
    assert limiter.try_reserve("search") == 11.0


def test_overlapping_reports_do_not_charge_completed_reservations_twice(monkeypatch):
    now = 100.0
    monkeypatch.setattr(trade, "time", SimpleNamespace(monotonic=lambda: now))
    limiter = trade._trade_rate_limiter
    for endpoint in ("fetch", "search"):
        limiter.adjust(endpoint, ip_quota(5, 0))
    pending = [limiter.try_reserve("fetch") for _ in range(3)]
    assert all(isinstance(reservation, trade._TradeReservation) for reservation in pending)

    now = 101.0
    limiter.adjust("fetch", ip_quota(5, 3), reservation=pending[0])
    # Until there is a report for every request, they could have reached the
    # server after the first snapshot.
    assert limiter.try_reserve("search") == 12.0
    now = 102.0
    for reservation in pending[1:]:
        limiter.adjust("fetch", ip_quota(5, 3), reservation=reservation)
    assert limiter.estimate_wait("search") == 0
    latest = [limiter.try_reserve("search") for _ in range(2)]
    assert all(isinstance(reservation, trade._TradeReservation) for reservation in latest)
    assert limiter.try_reserve("search") > 0


@pytest.mark.parametrize("other_active", [None, 1])
def test_overlapping_lower_or_missing_state_does_not_free_quota(monkeypatch, other_active):
    now = 100.0
    monkeypatch.setattr(trade, "time", SimpleNamespace(monotonic=lambda: now))
    limiter = trade._trade_rate_limiter
    limiter.adjust("fetch", ip_quota(4, 0))
    first, second = [limiter.try_reserve("fetch") for _ in range(2)]
    limiter.adjust("fetch", ip_quota(4, 3), reservation=first)
    now = 101.0
    headers = ip_quota(4, other_active) if other_active is not None else {}
    limiter.adjust("fetch", headers, reservation=second)
    if other_active is None:
        # The headerless request could have reached the server after the 3/4 snapshot.
        assert limiter.try_reserve("fetch") == 11.0
    else:
        # The lower snapshot could be older even when it arrives last.
        assert isinstance(limiter.try_reserve("fetch"), trade._TradeReservation)
        assert limiter.try_reserve("fetch") == 11.0


@pytest.mark.parametrize("route_known", [False, True])
def test_cancellation_after_reservation_returns_unsent_slot(monkeypatch, route_known):
    now = 100.0
    monkeypatch.setattr(trade, "time", SimpleNamespace(monotonic=lambda: now))
    limiter = trade._trade_rate_limiter
    if route_known:
        limiter.adjust("fetch", ip_quota(1, 0))
    reserve = limiter.try_reserve
    cancel = threading.Event()
    slot_returned = limiter._traffic.response_received
    sent = []

    def reserve_then_cancel(endpoint):
        result = reserve(endpoint)
        assert isinstance(result, trade._TradeReservation)
        cancel.set()
        return result

    def request(_method, url, **_kwargs):
        sent.append(url)
        return response(headers=ip_quota(1, 1))

    monkeypatch.setattr(trade._trade_http_pool, "request", request)
    monkeypatch.setattr(limiter, "try_reserve", reserve_then_cancel)
    with trade.trade_search_scope(cancel), pytest.raises(trade.TradeSearchCancelled):
        trade._request_json(f"{trade.API_ROOT}/fetch/obsolete")
    assert slot_returned.is_set()
    monkeypatch.setattr(limiter, "try_reserve", reserve)
    latest = f"{trade.API_ROOT}/fetch/current"
    trade._request_json(latest)
    assert sent == [latest]


@pytest.mark.parametrize("shared_policy", [False, True])
def test_new_search_overlaps_inflight_fetch_with_available_quota(monkeypatch, shared_policy):
    root = trade.API_ROOT
    headers = {"X-Rate-Limit-Rules": "Ip", "X-Rate-Limit-Ip": "5:10:0"}
    for route in ("search", "fetch"):
        trade._trade_rate_limiter.adjust(route, {
            **headers, "X-Rate-Limit-Policy": "shared" if shared_policy else route,
        })
    old_sent, release_old, new_sent, cancel = (threading.Event() for _ in range(4))

    def make_request(_pool, _connection, _method, url, **_kwargs):
        if "/fetch/" in url:
            old_sent.set()
            assert release_old.wait(3)
        else:
            new_sent.set()
        return urllib3.HTTPResponse(status=200, body=b"{}", headers=headers)

    def old_fetch():
        with trade.trade_search_scope(cancel):
            return trade._request_json(f"{root}/fetch/old")

    monkeypatch.setattr(urllib3.HTTPSConnectionPool, "_make_request", make_request)
    with ThreadPoolExecutor(max_workers=2) as pool:
        old = pool.submit(old_fetch)
        try:
            assert old_sent.wait(1)
            cancel.set()
            latest = pool.submit(trade._cached_request_json, f"{root}/search/Standard", {"query": {}})
            assert new_sent.wait(1)
        finally:
            release_old.set()
        old.result(timeout=1)
        latest.result(timeout=1)


def test_shared_policy_keeps_an_inflight_reservation_past_the_send_window(monkeypatch):
    now = 100.0
    headers = {
        "X-Rate-Limit-Policy": "shared",
        "X-Rate-Limit-Rules": "Ip",
        "X-Rate-Limit-Ip": "5:10:0",
    }
    limiter = trade._trade_rate_limiter
    for endpoint in ("search", "fetch"):
        limiter.adjust(endpoint, headers)
    monkeypatch.setattr(trade, "time", SimpleNamespace(monotonic=lambda: now))
    for _ in range(5):
        assert isinstance(limiter.try_reserve("fetch"), trade._TradeReservation)
    now += 20
    assert isinstance(limiter.try_reserve("search"), threading.Event)


def test_first_fetch_waits_for_shared_quota_and_blocks_search_until_policy_is_known(monkeypatch):
    now = 100.0
    search = f"{trade.API_ROOT}/search/Standard"
    fetch = f"{trade.API_ROOT}/fetch/old"
    headers = {
        "X-Rate-Limit-Policy": "shared",
        "X-Rate-Limit-Rules": "Ip",
        "X-Rate-Limit-Ip": "1:10:0",
    }
    sent = []
    fetch_sent, release_fetch, search_waiting = (threading.Event() for _ in range(3))
    limiter = trade._trade_rate_limiter
    try_reserve = limiter.try_reserve

    def sleep(seconds):
        nonlocal now
        now += seconds

    def request(_method, url, **_kwargs):
        sent.append((url, now))
        if url == fetch:
            fetch_sent.set()
            assert release_fetch.wait(3)
        return response(headers=headers)

    def observe_reservation(endpoint):
        result = try_reserve(endpoint)
        if endpoint == "search" and not isinstance(result, trade._TradeReservation):
            search_waiting.set()
        return result

    monkeypatch.setattr(trade, "time", SimpleNamespace(monotonic=lambda: now, sleep=sleep))
    monkeypatch.setattr(trade._trade_http_pool, "request", request)
    monkeypatch.setattr(limiter, "try_reserve", observe_reservation)
    trade._request_json(search, {"query": {}})
    with ThreadPoolExecutor(max_workers=2) as pool:
        previous = pool.submit(trade._request_json, fetch)
        try:
            assert fetch_sent.wait(1)
            assert sent == [(search, 100.0), (fetch, 112.0)]
            latest = pool.submit(trade._request_json, search, {"query": {}})
            assert search_waiting.wait(1)
            assert len(sent) == 2
        finally:
            release_fetch.set()
        previous.result(timeout=1)
        latest.result(timeout=1)
    assert sent == [(search, 100.0), (fetch, 112.0), (search, 124.0)]


@pytest.mark.parametrize("repeats_headers", [True, False])
def test_known_rate_limit_accounts_for_late_server_arrival(monkeypatch, repeats_headers):
    url = f"{trade.API_ROOT}/fetch/one"
    headers = {
        "X-Rate-Limit-Rules": "Ip",
        "X-Rate-Limit-Ip": "1:10:0",
        "X-Rate-Limit-Ip-State": "1:10:0",
    }
    now = 0.0
    arrivals = []

    def sleep(seconds):
        nonlocal now
        now += seconds

    def request(*_args, **_kwargs):
        if not arrivals:
            sleep(4.0)
        arrivals.append(now)
        return response(headers=headers if repeats_headers else {})

    monkeypatch.setattr(trade, "time", SimpleNamespace(monotonic=lambda: now, sleep=sleep))
    monkeypatch.setattr(trade._trade_http_pool, "request", request)
    trade._trade_rate_limiter.adjust("fetch", {**headers, "X-Rate-Limit-Ip-State": "0:10:0"})
    trade._request_json(url)
    trade._request_json(url)
    assert arrivals[1] - arrivals[0] >= 10.0


def test_first_paired_catalog_lookup_reloads_both_independently_cached_locales(monkeypatch):
    monkeypatch.setattr(trade, "_item_catalogs_cache", trade._TradeItemCatalogSnapshot())
    english, japanese = "Leather Cap", "革の帽子"
    requests = []

    def request(url):
        requests.append(url)
        base = english if url.startswith(trade.API_ROOT) else japanese
        return {"result": [{"id": "armour", "entries": [{"type": base}]}]}, {}

    monkeypatch.setattr(trade, "_request_json", request)
    assert trade._trade_item_entries() == ({"type": english},)
    assert trade._jp_trade_item_entries() == ({"type": japanese},)
    english, japanese = "Wool Shoes", "ウールの靴"
    assert list(trade._aligned_trade_item_pairs()) == [({"type": english}, {"type": japanese})]
    assert requests == [
        f"{trade.API_ROOT}/data/items", f"{trade.JP_API_ROOT}/data/items",
        f"{trade.JP_API_ROOT}/data/items", f"{trade.API_ROOT}/data/items",
    ]


def test_item_without_mods_preserves_the_warm_stat_index(monkeypatch):
    from src.poetore.parser import parse_item_text

    entries = ({"type": "explicit", "id": "explicit.stat_3299347043", "text": "最大ライフ +#"},)
    monkeypatch.setattr(trade, "_stat_entries_cache", entries)
    monkeypatch.setattr(trade, "_stat_entry_indexes_cache", None)
    trade._trade_stat_entry_indexes(entries)
    warm_index = trade._stat_entry_indexes_cache

    currency = parse_item_text("Item Class: Stackable Currency\nRarity: Currency\nChaos Orb\n")
    trade.resolve_trade_stat_filters(currency)
    assert trade._stat_entry_indexes_cache is warm_index

    armour = parse_item_text(
        "Item Class: Helmets\nRarity: Rare\nDread Visage\nLeather Cap\n"
        "--------\nItem Level: 68\n--------\n+25 to maximum Life\n"
    )
    assert armour.modifiers
    trade.resolve_trade_stat_filters(armour)
    assert trade._stat_entry_indexes_cache is warm_index


def test_aligned_catalog_reader_keeps_both_locales_across_refresh(monkeypatch):
    monkeypatch.setattr(trade, "_item_catalogs_cache", trade._TradeItemCatalogSnapshot())
    catalog_rows = {
        trade.API_ROOT: ("Leather Cap", "Wool Shoes"),
        trade.JP_API_ROOT: ("革の帽子", "ウールの靴"),
    }
    expected = list(zip(catalog_rows[trade.API_ROOT], catalog_rows[trade.JP_API_ROOT]))
    japanese_read, resume = threading.Event(), threading.Event()

    def request(url):
        rows = catalog_rows[url.removesuffix("/data/items")]
        return {"result": [{"id": "armour", "entries": [{"type": base} for base in rows]}]}, {}

    class ObservedGroups(tuple):
        def __iter__(self):
            if threading.current_thread() is not threading.main_thread():
                japanese_read.set()
                assert resume.wait(3)
            return super().__iter__()

    load = trade._load_trade_item_catalog

    def observe_load(api_root):
        catalog = load(api_root)
        if api_root == trade.JP_API_ROOT:
            return replace(catalog, groups=ObservedGroups(catalog.groups))
        return catalog

    def read_pairs():
        return [(english["type"], japanese["type"]) for english, japanese in trade._aligned_trade_item_pairs()]

    monkeypatch.setattr(trade, "_request_json", request)
    monkeypatch.setattr(trade, "_load_trade_item_catalog", observe_load)
    assert read_pairs() == expected
    with ThreadPoolExecutor(max_workers=1) as pool:
        old = pool.submit(read_pairs)
        try:
            assert japanese_read.wait(1)
            for locale in catalog_rows:
                catalog_rows[locale] = catalog_rows[locale][::-1]
            trade._clear_trade_item_catalog_cache()
            assert read_pairs() == expected[::-1]
        finally:
            resume.set()
        assert old.result(timeout=1) == expected


def test_english_identity_keeps_catalog_snapshot_between_base_and_unique_name(monkeypatch):
    monkeypatch.setattr(trade, "_item_catalogs_cache", trade._TradeItemCatalogSnapshot())
    item = trade.ParsedItem("靴", "ユニーク", "破滅の軌跡", "メッシュブーツ", "armour")
    english = "Mesh Boots", "Wake of Destruction"
    base_resolved, resume = threading.Event(), threading.Event()
    translate_type = trade._english_trade_item_type

    def request(url):
        base, name = english if url.startswith(trade.API_ROOT) else (item.base_type, item.name)
        return {"result": [{"id": "armour", "entries": [
            {"type": base, "name": name, "flags": {"unique": True}},
        ]}]}, {}

    def pause_after_base(*args, **kwargs):
        base = translate_type(*args, **kwargs)
        if threading.current_thread() is not threading.main_thread():
            base_resolved.set()
            assert resume.wait(3)
        return base

    def resolve():
        return trade.english_trade_identity(item, item.base_type, item.name)

    monkeypatch.setattr(trade, "_request_json", request)
    monkeypatch.setattr(trade, "_english_trade_item_type", pause_after_base)
    with ThreadPoolExecutor(max_workers=1) as pool:
        old = pool.submit(resolve)
        try:
            assert base_resolved.wait(1)
            english = "New Mesh Boots", "New Wake of Destruction"
            trade._clear_trade_item_catalog_cache()
            assert resolve() == english
        finally:
            resume.set()
        assert old.result(timeout=1) == ("Mesh Boots", "Wake of Destruction")


@pytest.mark.parametrize("retry_after", ["25", formatdate(1_800_000_025, usegmt=True)])
def test_catalog_429_delays_next_catalog_request(monkeypatch, retry_after):
    now = 100.0
    sent = []

    def sleep(seconds):
        nonlocal now
        now += seconds

    def request(_method, url, **_kwargs):
        sent.append((url, now))
        if len(sent) == 1:
            return response(status=429, headers={"Retry-After": retry_after})
        return response({"result": []})

    monkeypatch.setattr(trade, "time", SimpleNamespace(
        monotonic=lambda: now, time=lambda: 1_800_000_000 + now - 100.0, sleep=sleep,
    ))
    monkeypatch.setattr(trade._trade_http_pool, "request", request)
    items = f"{trade.API_ROOT}/data/items"
    stats = f"{trade.JP_API_ROOT}/data/stats"
    with pytest.raises(trade.TradeApiError, match="利用制限に達しました"):
        trade._request_json(items)
    assert trade._request_json(stats)[0] == {"result": []}
    assert sent == [(items, 100.0), (stats, 125.0)]


def test_first_catalog_429_with_only_policy_and_retry_after_blocks_search(monkeypatch):
    now = 100.0
    sent = []
    items = f"{trade.API_ROOT}/data/items"
    search = f"{trade.API_ROOT}/search/Standard"

    def request(_method, url, **_kwargs):
        sent.append((url, now))
        if url == items:
            return response(status=429, headers={
                "X-Rate-Limit-Policy": "shared", "Retry-After": "60",
            })
        return response({"id": "resumed"}, headers={"X-Rate-Limit-Policy": "shared"})

    monkeypatch.setattr(trade, "time", SimpleNamespace(monotonic=lambda: now))
    monkeypatch.setattr(trade._trade_http_pool, "request", request)
    with pytest.raises(trade.TradeApiError, match="利用制限に達しました"):
        trade._request_json(items)
    assert trade._trade_rate_limiter.estimate_wait("search") == 60
    now += 55
    with pytest.raises(trade.TradeApiError, match="約5秒後"):
        trade._cached_request_json(search, {"query": {}}, prevent_queue=True)
    assert sent == [(items, 100.0)]
    now += 5
    assert trade._cached_request_json(search, {"query": {}}, prevent_queue=True)[0] == {"id": "resumed"}
    assert sent == [(items, 100.0), (search, 160.0)]


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
    try_reserve = limiter.try_reserve
    sent = []

    def observe_wait(policy):
        result = try_reserve(policy)
        if policy == "fetch" and isinstance(result, float):
            wait_entered.set()
        return result

    def request(_method, url, **_kwargs):
        sent.append(url)
        return response({"id": "latest"})

    def old_fetch():
        with trade.trade_search_scope(cancel):
            return trade._cached_request_json(f"{root}/fetch/second")

    monkeypatch.setattr(limiter, "try_reserve", observe_wait)
    monkeypatch.setattr(trade._trade_http_pool, "request", request)
    with ThreadPoolExecutor(max_workers=2) as pool:
        old = pool.submit(old_fetch)
        try:
            assert wait_entered.wait(1)
            latest = pool.submit(
                trade._cached_request_json, f"{root}/search/Standard", {"query": {}}, prevent_queue=True,
            )
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


@pytest.mark.parametrize("retry_after", ["25", formatdate(1_800_000_025, usegmt=True)])
def test_429_blocks_new_requests_until_retry_after_and_shares_server_policy(monkeypatch, retry_after):
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
            return response(status=429, headers={**headers, "Retry-After": retry_after})
        return response({"id": "resumed"})

    monkeypatch.setattr(trade, "time", SimpleNamespace(
        monotonic=lambda: now, time=lambda: 1_800_000_000 + now - 100.0, sleep=time.sleep,
    ))
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
