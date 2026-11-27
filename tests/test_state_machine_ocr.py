import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage

from src.poetore import expedition_ocr_probe, expedition_rewards, heist_curio
from src.poetore.expedition_ocr_probe import WindowsOcrServer, WindowsOcrServerState
from src.poetore.expedition_rewards import ExpeditionRewardController, ExpeditionScanState
from src.poetore.heist_curio import HeistCurioController, HeistCurioState
from src.poetore.poe2 import desecration_overlay, ndlocr_pack
from src.poetore.poe2.desecration_overlay import DesecrationScanState, DesecrationTierController
from src.poetore.poe2.ndlocr_lite import NdlOcrLiteServer, NdlOcrServerState
from src.poetore.poe2.ndlocr_pack import NdlOcrPackController, PackInstallState, PackStatus
from src.poetore.screen_reading import ScreenReadingCoordinator, ScreenReadingState


def test_pack_retry_can_start_from_the_error_signal(qapp, monkeypatch):
    monkeypatch.setattr(ndlocr_pack, "pack_is_installed", lambda: False)
    attempts = []
    notifications = []
    ready = threading.Event()

    def install(*, phase, progress, cancelled):
        attempts.append(1)
        phase(PackInstallState.CHECKING)
        phase(PackInstallState.DOWNLOADING)
        progress(1, 2)
        phase(PackInstallState.INSTALLING)
        if len(attempts) == 1:
            raise OSError("download failed")

    controller = NdlOcrPackController(worker=install)

    def on_status(status):
        notifications.append((status.state, controller.state))
        if status.state is PackInstallState.ERROR:
            controller.retry()
        elif status.state is PackInstallState.READY:
            ready.set()

    controller.status_changed.connect(on_status, Qt.ConnectionType.DirectConnection)
    assert controller.state is PackInstallState.IDLE
    assert PackStatus("ready").state is PackInstallState.READY
    try:
        controller.ensure_started()
        assert ready.wait(3)
        assert len(attempts) == 2
        expected = [
            PackInstallState.CHECKING, PackInstallState.DOWNLOADING,
            PackInstallState.DOWNLOADING, PackInstallState.INSTALLING,
        ]
        assert notifications == [
            (state, state) for state in [
                *expected, PackInstallState.ERROR, *expected, PackInstallState.READY,
            ]
        ]
    finally:
        controller.close()


def test_ndlocr_ready_requires_a_live_process_and_retirement_wins_during_startup(
    tmp_path, monkeypatch,
):
    helper = tmp_path / "helper.exe"
    helper.touch()
    process = Mock(
        stdout=Mock(readline=Mock(return_value="")),
        stderr=Mock(readline=Mock(return_value="")),
    )
    process.poll.return_value = None
    server = NdlOcrLiteServer(helper=helper, process_factory=Mock(return_value=process))
    messages = []

    def reply(_timeout):
        messages.append(server.state)
        if server.state is NdlOcrServerState.STARTING:
            assert not server.is_ready
            return {"event": "ready"}
        request = json.loads(process.stdin.write.call_args.args[0])
        return {
            "event": "result", "request_id": request["request_id"],
            "ok": True, "results": [{"text": "recognized"}],
        }

    monkeypatch.setattr(server, "_next_message", reply)
    assert server.state is NdlOcrServerState.STOPPED
    try:
        assert server.recognize([b"image"])[0].text == "recognized"
        assert messages == [NdlOcrServerState.STARTING, NdlOcrServerState.READY]
        assert server.is_ready
        process.poll.return_value = 1
        assert not server.is_ready
        server.close()
        assert server.state is NdlOcrServerState.STOPPED

        def retire_while_waiting(_timeout):
            assert server.state is NdlOcrServerState.STARTING
            server.close(permanent=True)
            return {"event": "ready"}

        monkeypatch.setattr(server, "_next_message", retire_while_waiting)
        with pytest.raises(RuntimeError, match="終了済み"):
            server.recognize([b"image"])
        assert server.state is NdlOcrServerState.RETIRED
        assert not server.is_ready
        assert server.session_dir is None
    finally:
        server.close(permanent=True)


def test_windows_ocr_cancels_startup_and_can_reopen_until_retired(monkeypatch):
    server = WindowsOcrServer()
    process = Mock(stdout=None, stderr=None, poll=Mock(return_value=None))
    monkeypatch.setattr(expedition_ocr_probe, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(expedition_ocr_probe, "_windows_ocr_helper", lambda: None)
    monkeypatch.setattr(expedition_ocr_probe, "_windows_ocr_command", lambda _helper: ["helper"])
    monkeypatch.setattr(expedition_ocr_probe.subprocess, "Popen", Mock(return_value=process))

    def cancel_then_reply(*_args):
        assert server.state is WindowsOcrServerState.STARTING
        server.close()
        return '{"ready": true}'

    monkeypatch.setattr(server, "_wait_response", cancel_then_reply)
    assert server.state is WindowsOcrServerState.STOPPED
    with pytest.raises(RuntimeError, match="中断"):
        server.start()
    assert server.state is WindowsOcrServerState.STOPPED

    monkeypatch.setattr(server, "_wait_response", Mock(return_value='{"ready": true}'))
    try:
        server.start()
        assert server.state is WindowsOcrServerState.READY
    finally:
        server.close(permanent=True)
    assert server.state is WindowsOcrServerState.RETIRED
    server.close()
    with pytest.raises(RuntimeError, match="終了済み"):
        server.start()
    assert server.state is WindowsOcrServerState.RETIRED


def test_screen_reading_owner_tracks_busy_state_and_cannot_survive_close():
    ocr = Mock()
    coordinator = ScreenReadingCoordinator(ocr)
    assert coordinator.state is ScreenReadingState.IDLE
    assert coordinator.try_begin("expedition")
    assert coordinator.state is ScreenReadingState.BUSY
    assert not coordinator.try_begin("heist_curio")
    coordinator.finish("heist_curio")
    assert coordinator.owner == "expedition"
    assert coordinator.state is ScreenReadingState.BUSY
    coordinator.finish("expedition")
    assert coordinator.state is ScreenReadingState.IDLE
    assert coordinator.owner is None
    assert coordinator.try_begin("heist_curio")
    coordinator.close()
    coordinator.finish("heist_curio")
    assert coordinator.owner is None
    assert coordinator.state is ScreenReadingState.CLOSED
    assert not coordinator.try_begin("desecration")
    ocr.close.assert_called_once_with(permanent=True)


def test_desecration_open_fallback_category_display_and_close(qapp, monkeypatch):
    gate = ScreenReadingCoordinator(Mock())
    client = QRect(0, 0, 800, 600)
    region = {"left": 0, "top": 0, "right": 1, "bottom": 1}
    controller = DesecrationTierController(
        regions_getter=lambda: {
            "inventory_open_region": region, "inventory_closed_region": region,
        },
        ocr_server=gate.ocr, scan_coordinator=gate,
    )
    monkeypatch.setattr(desecration_overlay, "path_of_exile_client_rect", lambda: client)
    monkeypatch.setattr(desecration_overlay, "threading", SimpleNamespace(Thread=Mock()))
    capture_states = []

    def prepare_frame(_image):
        capture_states.append(controller.state)
        return SimpleNamespace(valid_panel=len(capture_states) > 1, bands=(), variants=())

    monkeypatch.setattr(desecration_overlay, "prepare_desecration_frame", prepare_frame)
    controller._grab = Mock(return_value=QImage())
    controller._category_overlay.show_categories = Mock()
    controller._overlay.show_tiers = Mock()
    try:
        assert controller.state is DesecrationScanState.IDLE
        assert controller.request_scan()
        assert capture_states == [
            DesecrationScanState.SCANNING_OPEN, DesecrationScanState.SCANNING_CLOSED,
        ]
        assert controller.running
        assert gate.owner == "desecration"
        controller.hide()
        assert controller.state is DesecrationScanState.SCANNING_CLOSED

        generation = controller._scan_generation
        resolution = SimpleNamespace(categories=("ring", "boots"), needs_category_choice=True)
        controller._ready.emit(resolution, client, client, (), generation)
        assert controller.state is DesecrationScanState.AWAITING_CATEGORY
        assert not controller.running
        assert gate.owner is None
        controller._category_overlay.cancelled.emit()
        assert controller.state is DesecrationScanState.DISPLAYING
        controller.hide()
        assert controller.state is DesecrationScanState.IDLE
        controller.close()

        controller._ready.emit(resolution, client, client, (), generation)
        assert controller.state is DesecrationScanState.CLOSED
        assert not controller.request_scan()
    finally:
        controller.close()


def test_expedition_stays_capturing_until_third_frame_and_ignores_late_failure(qapp, monkeypatch):
    gate = ScreenReadingCoordinator(Mock())
    client = QRect(0, 0, 800, 600)
    region = {"left": 0, "top": 0, "right": 1, "bottom": 1}
    controller = ExpeditionRewardController(
        lambda: "League", region_getter=lambda: region,
        ocr_server=gate.ocr, scan_coordinator=gate, diagnostics_enabled=False,
    )
    monkeypatch.setattr(expedition_rewards, "path_of_exile_client_rect", lambda: client)
    monkeypatch.setattr(expedition_rewards, "threading", SimpleNamespace(Thread=Mock()))
    monkeypatch.setattr(expedition_rewards, "QTimer", SimpleNamespace(singleShot=Mock()))
    controller._grab_game = Mock(return_value=QImage(2, 2, QImage.Format.Format_RGB32))
    controller._overlay.show_prices = Mock()
    failed = Mock()
    controller.failed.connect(failed)
    try:
        assert controller.state is ExpeditionScanState.IDLE
        assert controller.request_scan()
        assert controller.state is ExpeditionScanState.CAPTURING
        assert not controller.request_scan()
        controller.hide()
        assert controller.running
        controller._capture_frame()
        assert controller.state is ExpeditionScanState.CAPTURING
        controller._capture_frame()
        assert controller.state is ExpeditionScanState.PROCESSING
        assert gate.owner == "expedition"
        controller._capture_frame()
        assert controller._grab_game.call_count == 3

        generation = controller._scan_generation
        controller._ready.emit(client, [], (800, 600), (0, 0, []), 0, generation)
        assert controller.state is ExpeditionScanState.DISPLAYING
        assert not controller.running
        assert gate.owner is None
        controller.hide()
        assert controller.state is ExpeditionScanState.IDLE
        assert controller.request_scan()
        controller.close()
        controller._scan_failed.emit("stale", generation)
        failed.assert_not_called()
        assert gate.owner is None
        assert controller.state is ExpeditionScanState.CLOSED
        assert not controller.request_scan()
    finally:
        controller.close()


def test_heist_cancel_releases_gate_and_close_wins_over_worker_finally(qapp, monkeypatch):
    ocr = Mock()
    gate = ScreenReadingCoordinator(ocr)
    controller = HeistCurioController(ocr_server=ocr, scan_coordinator=gate)
    client = QRect(0, 0, 800, 600)
    monkeypatch.setattr(heist_curio, "path_of_exile_client_rect", lambda: client)
    selector = Mock(selected_rect=client)
    selection_states = []

    def select_region():
        selection_states.append(controller.state)
        return len(selection_states) > 1

    selector.exec.side_effect = select_region
    monkeypatch.setattr(heist_curio, "CurioRegionSelector", lambda _client: selector)
    monkeypatch.setattr(heist_curio, "prepare_curio_ocr_image", lambda _image: b"image")
    controller._grab = Mock(return_value=QImage(2, 2, QImage.Format.Format_RGB32))

    worker_started = threading.Event()
    release_worker = threading.Event()
    workers = []

    def create_worker(**kwargs):
        worker = threading.Thread(**kwargs)
        workers.append(worker)
        return worker

    def recognize(_images):
        worker_started.set()
        release_worker.wait(3)
        raise RuntimeError("late failure")

    monkeypatch.setattr(heist_curio, "threading", SimpleNamespace(Thread=create_worker))
    ocr.recognize.side_effect = recognize
    failed = Mock()
    controller.failed.connect(failed)
    try:
        assert controller.state is HeistCurioState.IDLE
        assert not controller.request_scan()
        assert controller.state is HeistCurioState.IDLE
        assert gate.owner is None
        assert controller.request_scan()
        assert worker_started.wait(3)
        assert selection_states == [HeistCurioState.SELECTING_REGION] * 2
        assert controller.state is HeistCurioState.PROCESSING
        assert controller.running
        controller.close()
        assert gate.try_begin("expedition")
    finally:
        release_worker.set()
        for worker in workers:
            worker.join(3)
        controller.close()

    assert not workers[0].is_alive()
    qapp.processEvents()
    failed.assert_not_called()
    assert controller.state is HeistCurioState.CLOSED
    assert not controller.running
    assert not controller.request_scan()
    assert gate.owner == "expedition"
