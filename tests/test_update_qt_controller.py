from dataclasses import replace
import hashlib
import sys
from pathlib import Path
from threading import Thread
from unittest.mock import Mock
from zipfile import ZipFile

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from src.update.qt_controller import UpdateController
from src.update.release_client import ReleaseInfo


@pytest.fixture(scope="module", autouse=True)
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


class ImmediateThread:
    def __init__(self, target):
        self.target = target

    def start(self):
        self.target()


@pytest.fixture
def release_download(tmp_path, monkeypatch):
    release = ReleaseInfo(
        "2.5.0", "notes", "https://github.com/page",
        "https://github.com/a.zip", "https://github.com/a.sha256",
    )
    source = tmp_path / "release.zip"

    def publish(content):
        with ZipFile(source, "w") as archive:
            archive.writestr("PoENavi.exe", content)
            archive.writestr("PoENaviUpdater.exe", b"updater")
        return source.read_bytes()

    def download(url, destination, _progress, _cancelled):
        if url == release.checksum_url:
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            destination.write_text(f"{digest}  PoENavi.zip", encoding="utf-8")
        else:
            assert url == release.zip_url
            destination.write_bytes(source.read_bytes())
        return destination

    fetch_asset = Mock(side_effect=download)
    monkeypatch.setattr("src.update.qt_controller.download_file", fetch_asset)
    return release, publish, fetch_asset


def test_check_emits_release_and_manual_flag(monkeypatch):
    release = ReleaseInfo(
        "2.5.0",
        "notes",
        "https://github.com/page",
        "https://github.com/a.zip",
        "https://github.com/a.sha256",
    )
    controller = UpdateController(thread_factory=ImmediateThread)
    received = []
    controller.check_finished.connect(
        lambda value, manual: received.append((value, manual))
    )
    monkeypatch.setattr(
        "src.update.qt_controller.fetch_latest_release",
        lambda _version: release,
    )

    controller.check(True)

    assert received == [(release, True)]


def test_worker_completion_keeps_check_in_flight_until_qt_delivers_result(qt_app, monkeypatch):
    workers = []

    def make_thread(target):
        worker = Thread(target=target, daemon=True)
        workers.append(worker)
        return worker

    fetch = Mock(return_value=None)
    monkeypatch.setattr("src.update.qt_controller.fetch_latest_release", fetch)
    controller = UpdateController(thread_factory=make_thread)
    received = Mock()
    controller.check_finished.connect(received)

    controller.check(False)
    workers[0].join(timeout=5)
    assert not workers[0].is_alive()
    assert controller.checking

    controller.check(True)
    assert len(workers) == 1
    assert fetch.call_count == 1
    received.assert_not_called()

    qt_app.processEvents()

    assert not controller.checking
    received.assert_called_once_with(None, False)


def test_timed_out_worker_cannot_complete_a_retry(monkeypatch):
    monkeypatch.setattr("src.update.qt_controller.CHECK_TIMEOUT_MS", 1, raising=False)
    workers = []
    controller = UpdateController(thread_factory=lambda target: Mock(start=lambda: workers.append(target)))
    monkeypatch.setattr("src.update.qt_controller.fetch_latest_release", lambda _: None)
    failed, finished = Mock(), Mock()
    controller.check_failed.connect(failed)
    controller.check_finished.connect(finished)
    loop = QEventLoop()
    controller.check_failed.connect(loop.quit)

    controller.check(False)
    QTimer.singleShot(1000, loop, loop.quit)
    loop.exec()

    failed.assert_called_once()
    assert not controller.checking
    controller.check(True)
    workers[0]()
    assert controller.checking
    finished.assert_not_called()
    workers[1]()
    finished.assert_called_once_with(None, True)
    assert not controller.checking


def test_republished_release_downloads_new_zip_when_checksum_changes(release_download):
    release, publish, fetch_asset = release_download
    controller = UpdateController(thread_factory=ImmediateThread)
    downloads = []
    controller.download_ready.connect(lambda path, _: downloads.append(path.read_bytes()))
    original = publish(b"old app")
    try:
        controller.download(release)
        replacement = publish(b"new app under the same tag")
        controller.download(release)

        assert downloads == [original, replacement]
        assert [call.args[0] for call in fetch_asset.call_args_list].count(release.zip_url) == 2
    finally:
        controller.discard_download()


@pytest.mark.parametrize("withdrawn", [True, False])
def test_successful_check_discards_previous_download(release_download, monkeypatch, withdrawn):
    release, publish, _ = release_download
    publish(b"old app")
    controller = UpdateController(thread_factory=ImmediateThread)
    ready = Mock()
    controller.download_ready.connect(ready)
    monkeypatch.setattr(
        "src.update.qt_controller.fetch_latest_release", lambda _: None if withdrawn else release,
    )
    try:
        controller.download(release)
        archive = ready.call_args.args[0]
        directory_exists = []
        controller.check_finished.connect(lambda *_: directory_exists.append(archive.parent.exists()))
        controller.check(False)

        assert directory_exists == [False]
    finally:
        controller.discard_download()


def test_withdrawal_discards_download_that_finishes_after_check(release_download, monkeypatch):
    release, publish, _ = release_download
    publish(b"old app")
    workers = []
    controller = UpdateController(thread_factory=lambda target: Mock(start=lambda: workers.append(target)))
    ready, cancelled = Mock(), Mock()
    controller.download_ready.connect(ready)
    controller.download_cancelled.connect(cancelled)
    monkeypatch.setattr("src.update.qt_controller.fetch_latest_release", lambda _: None)
    try:
        controller.download(release)
        controller.check(False)
        finish_download, finish_check = workers
        finish_check()
        finish_download()

        ready.assert_not_called()
        cancelled.assert_called_once_with()
    finally:
        controller.discard_download()


@pytest.mark.parametrize("tampered", [False, True])
def test_launch_updater_validates_staged_zip_and_uses_argument_list(
    tmp_path,
    monkeypatch,
    release_download,
    tampered,
):
    release, publish, _ = release_download
    original = publish(b"new app")
    install = tmp_path / "ぽえなび" / "PoENavi"
    install.mkdir(parents=True)
    (install / "PoENavi.exe").write_text("app", encoding="utf-8")
    (install / "PoENaviUpdater.exe").write_text("updater", encoding="utf-8")
    updater_work = tmp_path / "updater-work"
    launched = []
    controller = UpdateController(thread_factory=ImmediateThread)
    ready = Mock()
    controller.download_ready.connect(ready)
    controller.download(release)
    archive = ready.call_args.args[0]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", str(install / "PoENavi.exe"))
    monkeypatch.setattr(
        "src.update.qt_controller.tempfile.mkdtemp",
        lambda prefix: str(updater_work),
    )
    monkeypatch.setattr(
        "src.update.qt_controller.subprocess.Popen",
        lambda args, cwd: launched.append((args, cwd)),
    )

    if tampered:
        archive.write_bytes(publish(b"a structurally valid but different ZIP"))
        try:
            with pytest.raises(ValueError, match="SHA-256"):
                controller.launch_updater(archive)
            assert launched == []
            assert not updater_work.exists()
        finally:
            controller.discard_download()
        return

    controller.launch_updater(archive)
    args, cwd = launched[0]
    assert args[0] == str(updater_work / "PoENaviUpdater.exe")
    assert args[args.index("--install-dir") + 1] == str(install)
    staged_archive = Path(args[args.index("--archive") + 1])
    assert staged_archive == updater_work / "PoENavi.zip"
    assert staged_archive.read_bytes() == original
    assert cwd == str(updater_work)
    assert not archive.parent.exists()


def test_cleanup_stale_update_directories(tmp_path, monkeypatch):
    stale = tmp_path / "PoENavi-Updater-old"
    stale.mkdir()
    (stale / "PoENaviUpdater.exe").write_text("old", encoding="utf-8")
    unrelated = tmp_path / "other-app"
    unrelated.mkdir()
    monkeypatch.setattr(
        "src.update.qt_controller.tempfile.gettempdir",
        lambda: str(tmp_path),
    )

    UpdateController._cleanup_stale_update_dirs()

    assert not stale.exists()
    assert unrelated.exists()


def test_download_reuses_verified_archive_after_reading_current_checksum(release_download):
    release, publish, fetch_asset = release_download
    publish(b"unchanged app")
    controller = UpdateController(thread_factory=ImmediateThread)
    ready = Mock()
    controller.download_ready.connect(ready)
    try:
        controller.download(release)
        first = ready.call_args
        controller.download(release)

        assert ready.call_args_list == [first, first]
        assert first.args[0].is_file()
        urls = [call.args[0] for call in fetch_asset.call_args_list]
        assert urls.count(release.zip_url) == 1
        assert urls.count(release.checksum_url) == 2
    finally:
        controller.discard_download()


def test_download_discards_archive_for_different_release(release_download):
    release, publish, _ = release_download
    publish(b"app")
    newer = replace(release, version="2.6.0")
    controller = UpdateController(thread_factory=ImmediateThread)
    ready = Mock()
    controller.download_ready.connect(ready)
    try:
        controller.download(release)
        first_archive = ready.call_args.args[0]
        controller.download(newer)

        assert ready.call_args.args[0].is_file()
        assert ready.call_args.args[1] == newer
        assert not first_archive.parent.exists()
    finally:
        controller.discard_download()
