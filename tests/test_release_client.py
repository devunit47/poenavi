import io
import json
from http.client import IncompleteRead

import pytest

from src.update.release_client import (
    RELEASES_API,
    fetch_latest_release,
    parse_latest_release,
    parse_version,
)


def release_payload(tag="v2.5.0", *, draft=False, prerelease=False, assets=None):
    if assets is None:
        assets = [
            {
                "name": "PoENavi.zip",
                "browser_download_url": "https://github.com/buri34/poenavi/releases/download/v2.5.0/PoENavi.zip",
            },
            {
                "name": "PoENavi.zip.sha256",
                "browser_download_url": "https://github.com/buri34/poenavi/releases/download/v2.5.0/PoENavi.zip.sha256",
            },
        ]
    return {
        "tag_name": tag,
        "name": f"PoENavi {tag}",
        "body": "変更内容",
        "html_url": f"https://github.com/buri34/poenavi/releases/tag/{tag}",
        "draft": draft,
        "prerelease": prerelease,
        "assets": assets,
    }


@pytest.mark.parametrize("value, expected", [("2.4.0", (2, 4, 0)), ("v10.2.3", (10, 2, 3))])
def test_parse_version(value, expected):
    assert parse_version(value) == expected


@pytest.mark.parametrize("value", ["2.4", "2.4.0-beta", "release-2.4.0", ""])
def test_parse_version_rejects_non_release_tags(value):
    with pytest.raises(ValueError):
        parse_version(value)


def test_parse_latest_release_returns_new_stable_release():
    release = parse_latest_release(release_payload(), "2.4.0")
    assert release is not None
    assert release.version == "2.5.0"
    assert release.notes == "変更内容"
    assert release.zip_url.endswith("PoENavi.zip")
    assert release.checksum_url.endswith("PoENavi.zip.sha256")


@pytest.mark.parametrize(
    "payload",
    [
        release_payload(tag="v2.4.0"),
        release_payload(draft=True),
        release_payload(prerelease=True),
        release_payload(
            assets=[
                {
                    "name": "PoENavi.zip",
                    "browser_download_url": "https://github.com/file",
                }
            ]
        ),
    ],
)
def test_parse_latest_release_ignores_ineligible_release(payload):
    assert parse_latest_release(payload, "2.4.0") is None


def test_fetch_latest_release_sends_user_agent_and_timeout():
    calls = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    def opener(request, timeout):
        calls.append((request, timeout))
        return Response(json.dumps(release_payload()).encode("utf-8"))

    release = fetch_latest_release("2.4.0", opener=opener)
    assert release is not None
    assert release.version == "2.5.0"
    assert calls[0][0].full_url == RELEASES_API
    assert calls[0][0].get_header("User-agent") == "PoENavi-Updater"
    assert calls[0][1] == 10


def test_fetch_latest_release_limits_total_time_while_data_keeps_arriving(monkeypatch):
    elapsed = 0
    monkeypatch.delenv("POENAVI_UPDATE_TEST_TAG", raising=False)
    monkeypatch.setattr("src.update.release_client.monotonic", lambda: elapsed)

    class SlowResponse(io.BytesIO):
        def read1(self, size):
            nonlocal elapsed
            elapsed += 8
            return super().read1(1)

    response = SlowResponse(json.dumps(release_payload()).encode("utf-8"))

    def opener(_request, timeout):
        nonlocal elapsed
        assert timeout == 10
        elapsed += 8
        return response

    with pytest.raises(TimeoutError, match="更新確認がタイムアウトしました。"):
        fetch_latest_release("2.4.0", opener=opener)

    assert elapsed == 32
    assert response.closed


def test_fetch_latest_release_rejects_incomplete_body_with_content_length(monkeypatch):
    monkeypatch.delenv("POENAVI_UPDATE_TEST_TAG", raising=False)
    response = io.BytesIO(json.dumps(release_payload()).encode("utf-8"))
    response.length = 1

    with pytest.raises(IncompleteRead):
        fetch_latest_release("2.4.0", opener=lambda _request, timeout: response)


def test_fetch_test_release_uses_tag_endpoint_and_allows_prerelease(monkeypatch):
    calls = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    def opener(request, timeout):
        calls.append((request, timeout))
        payload = release_payload(prerelease=True)
        return Response(json.dumps(payload).encode("utf-8"))

    monkeypatch.setenv("POENAVI_UPDATE_TEST_TAG", "v2.5.0")
    release = fetch_latest_release("2.4.0", opener=opener)

    assert release is not None
    assert release.version == "2.5.0"
    assert calls[0][0].full_url.endswith("/releases/tags/v2.5.0")


def test_fetch_test_release_rejects_invalid_environment_tag(monkeypatch):
    monkeypatch.setenv("POENAVI_UPDATE_TEST_TAG", "../../latest")

    with pytest.raises(ValueError):
        fetch_latest_release("2.4.0", opener=lambda *_args, **_kwargs: None)
