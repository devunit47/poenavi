from dataclasses import dataclass
from pathlib import Path
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Qt, Signal, Slot

from src.update.artifacts import (
    DownloadCancelled,
    download_file,
    parse_checksum,
    validate_update_archive,
    verify_sha256,
)
from src.update.release_client import (
    CHECK_TIMEOUT_MESSAGE,
    RELEASE_CHECK_TIMEOUT_SECONDS,
    SOCKET_TIMEOUT_SECONDS,
    ReleaseInfo,
    fetch_latest_release,
)
from src.version import APP_VERSION


# Allow for an in-flight socket wait and delivery of the result to the UI.
CHECK_TIMEOUT_MS = (RELEASE_CHECK_TIMEOUT_SECONDS + SOCKET_TIMEOUT_SECONDS + 5) * 1000
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _VerifiedDownload:
    archive: Path
    release: ReleaseInfo
    checksum: str


class UpdateController(QObject):
    check_started = Signal()
    check_finished = Signal(object, bool)
    check_failed = Signal(str, bool)
    _check_result = Signal(object, object, object)
    download_progress = Signal(int, int)
    download_ready = Signal(object, object)
    download_failed = Signal(str)
    download_cancelled = Signal()
    _download_result = Signal(object, object)

    def __init__(self, parent=None, thread_factory=None):
        super().__init__(parent)
        self._thread_factory = thread_factory or (
            lambda target: threading.Thread(target=target, daemon=True)
        )
        self._active_check: tuple[object, bool] | None = None
        self._check_timer = QTimer(self)
        self._check_timer.setSingleShot(True)
        self._check_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._check_timer.timeout.connect(self._expire_check)
        self._check_result.connect(self._finish_check)
        self._downloading = False
        self._download_result.connect(self._finish_download)
        self._cancel = threading.Event()
        self._validation_lock = threading.Lock()
        self._work_dir: Path | None = None
        self._ready_download: _VerifiedDownload | None = None
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._discard_download_on_quit)
        if getattr(sys, "frozen", False) and sys.platform == "win32":
            cleanup_timer = threading.Timer(10, self._cleanup_stale_update_dirs)
            cleanup_timer.daemon = True
            try:
                cleanup_timer.start()
            except Exception:
                logger.warning("古い更新用一時フォルダーの削除を開始できませんでした。", exc_info=True)

    @staticmethod
    def _cleanup_stale_update_dirs() -> None:
        temp_dir = Path(tempfile.gettempdir())
        for path in temp_dir.glob("PoENavi-Updater-*"):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)

    @property
    def checking(self) -> bool:
        return self._active_check is not None

    def check(self, manual: bool) -> None:
        if self.checking:
            return
        check_id = object()
        self._active_check = check_id, manual
        self._check_timer.start(CHECK_TIMEOUT_MS)
        self.check_started.emit()

        def work():
            try:
                release = fetch_latest_release(APP_VERSION)
            except Exception as exc:
                self._check_result.emit(check_id, None, str(exc))
            else:
                self._check_result.emit(check_id, release, None)

        try:
            self._thread_factory(work).start()
        except Exception as exc:
            self._finish_check(check_id, None, str(exc))

    @Slot()
    def _expire_check(self):
        if self._active_check is not None:
            self._finish_check(self._active_check[0], None, CHECK_TIMEOUT_MESSAGE)

    @Slot(object, object, object)
    def _finish_check(self, check_id, release, error):
        # A timed-out worker can still return after another check has started.
        if self._active_check is None or self._active_check[0] is not check_id:
            return
        _, manual = self._active_check
        self._check_timer.stop()
        self._active_check = None
        if error is None:
            self.discard_download()
            self.check_finished.emit(release, manual)
        else:
            self.check_failed.emit(error, manual)

    def download(self, release: ReleaseInfo) -> None:
        if self._downloading:
            return
        cached = self._ready_download
        if cached is not None and cached.release != release:
            self.discard_download()
            cached = None
        self._ready_download = None
        self._downloading = True
        self._cancel.clear()

        def work():
            try:
                # A release can replace both assets at the same URLs.
                checksum_file = download_file(
                    release.checksum_url,
                    work_dir / "PoENavi.zip.sha256",
                    lambda _done, _total: None,
                    self._cancel.is_set,
                )
                with self._validation_lock:
                    if self._cancel.is_set():
                        raise DownloadCancelled()
                    expected = parse_checksum(checksum_file.read_text(encoding="utf-8"))
                    archive = None
                    if cached is not None:
                        try:
                            if verify_sha256(cached.archive, expected):
                                archive = cached.archive
                        except OSError:
                            pass
                needs_download = archive is None
                if needs_download:
                    if self._cancel.is_set():
                        raise DownloadCancelled()
                    archive = download_file(
                        release.zip_url,
                        work_dir / "PoENavi.zip",
                        self.download_progress.emit,
                        self._cancel.is_set,
                    )
                with self._validation_lock:
                    if self._cancel.is_set():
                        raise DownloadCancelled()
                    if needs_download and not verify_sha256(archive, expected):
                        raise ValueError("ダウンロードした ZIP の SHA-256 が一致しません。")
                    validate_update_archive(archive)
            except Exception as exc:
                self._download_result.emit(None, exc)
            else:
                self._download_result.emit(_VerifiedDownload(archive, release, expected), None)

        try:
            if self._work_dir is None:
                self._work_dir = Path(tempfile.mkdtemp(prefix=f"PoENavi-{release.version}-"))
            work_dir = self._work_dir
            self._thread_factory(work).start()
        except Exception as exc:
            self._finish_download(None, exc)

    @Slot(object, object)
    def _finish_download(self, ready, error):
        self._downloading = False
        if self._cancel.is_set() or isinstance(error, DownloadCancelled):
            self.discard_download()
            self.download_cancelled.emit()
        elif error is not None:
            self.discard_download()
            self.download_failed.emit(str(error))
        else:
            self._ready_download = ready
            self.download_ready.emit(ready.archive, ready.release)

    def cancel_download(self) -> None:
        self._cancel.set()

    def discard_download(self) -> None:
        self._ready_download = None
        if self._downloading:
            # The worker still owns the files until it reports completion.
            self.cancel_download()
            return
        self._remove_work_dir()

    @Slot()
    def _discard_download_on_quit(self) -> None:
        self.cancel_download()
        self._ready_download = None
        # On Windows an open ZIP can prevent deletion. Wait for local validation
        # to close it before Qt stops delivering queued worker results.
        with self._validation_lock:
            self._remove_work_dir()

    def _remove_work_dir(self) -> None:
        if self._work_dir is not None:
            shutil.rmtree(self._work_dir, ignore_errors=True)
            self._work_dir = None

    def launch_updater(self, archive: Path) -> None:
        if not getattr(sys, "frozen", False) or sys.platform != "win32":
            raise RuntimeError(
                "自動更新は Windows exe 版でのみ利用できます。"
            )
        ready = self._ready_download
        if ready is None or ready.archive != Path(archive):
            raise ValueError("更新 ZIP を確認できません。更新を確認してダウンロードし直してください。")

        install_dir = Path(sys.executable).resolve().parent
        source = install_dir / "PoENaviUpdater.exe"
        if not source.is_file():
            raise RuntimeError("PoENaviUpdater.exe が見つかりません。")

        updater_work = Path(tempfile.mkdtemp(prefix="PoENavi-Updater-"))
        updater_work.mkdir(parents=True, exist_ok=True)
        updater = updater_work / "PoENaviUpdater.exe"
        staged_archive = updater_work / "PoENavi.zip"
        try:
            shutil.copy2(source, updater)
            shutil.copy2(ready.archive, staged_archive)
            if not verify_sha256(staged_archive, ready.checksum):
                raise ValueError("適用する ZIP の SHA-256 が一致しません。")
            validate_update_archive(staged_archive)
            subprocess.Popen(
                [
                    str(updater),
                    "--pid",
                    str(os.getpid()),
                    "--archive",
                    str(staged_archive),
                    "--install-dir",
                    str(install_dir),
                    "--work-dir",
                    str(updater_work),
                ],
                cwd=str(updater_work),
            )
        except Exception:
            shutil.rmtree(updater_work, ignore_errors=True)
            raise

        self.discard_download()
