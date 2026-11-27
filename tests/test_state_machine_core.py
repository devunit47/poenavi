from dataclasses import replace
from enum import StrEnum
from hashlib import sha256
from unittest.mock import Mock
from zipfile import ZipFile

import pytest

from src import app_composition, app_session
from src.app_mode import POENAVI_MODE, POETORE_MODE
from src.app_session import AppSessionController, AppSessionState
from src.poetore import notification_audio
from src.poetore.hideout_notification import HideoutTimerPhase, HideoutTimerState
from src.poetore.notification_audio import AudioPlaybackState, NotificationAudioPlayer
from src.update import qt_controller
from src.update.qt_controller import UpdateCheckState, UpdateController, UpdateDownloadState
from src.update.release_client import ReleaseInfo
from src.utils.global_hotkeys import (
    ForegroundContext,
    ForegroundSuppressedHotkeyService,
    SuppressedHotkeyState,
)
from src.utils.state_machine import InvalidStateTransitionError, StateMachine


class ExampleState(StrEnum):
    FIRST = "first"
    SECOND = "second"


def test_state_machine_validates_transitions_and_notifies_after_commit():
    first, second = ExampleState.FIRST, ExampleState.SECOND
    changes = []
    machine = StateMachine(
        "example", first, {first: frozenset({second}), second: frozenset()},
        on_transition=lambda previous, target: changes.append((previous, target, machine.state)),
    )

    assert machine.require(first, action="start") is first
    assert machine.can_transition(second)
    assert not machine.can_transition(first)
    assert machine.can_transition(first, allow_same=True)
    assert machine.transition(first, allow_same=True) is first
    with pytest.raises(InvalidStateTransitionError):
        machine.transition(first)
    assert changes == []

    assert machine.transition(second) is second
    assert machine.is_in(first, second)
    with pytest.raises(InvalidStateTransitionError, match="already advanced") as error:
        machine.transition(first, reason="already advanced")
    assert error.value.machine_name == "example"
    assert error.value.current_state is second
    assert error.value.target_state is first
    with pytest.raises(InvalidStateTransitionError, match=r"example \(start\).*expected"):
        machine.require(first, action="start")
    assert machine.state is second
    assert changes == [(first, second, second)]


def test_state_machine_requires_initial_state_in_table():
    with pytest.raises(ValueError, match="initial state.*missing"):
        StateMachine("example", ExampleState.FIRST, {ExampleState.SECOND: frozenset()})


def test_hideout_tracks_zone_and_due_slot_through_phase_changes():
    timer = HideoutTimerState(duration_seconds=10, repeat=False)
    timer.enter_zone("Coastal Hideout", now=0.0)
    assert timer.phase is HideoutTimerPhase.DISABLED
    assert not (timer.active or timer.zone_known or timer.in_hideout or timer.notified)
    assert timer.started_at is None

    timer.enable(None, now=0.0)
    assert timer.phase is HideoutTimerPhase.AWAITING_ZONE
    assert timer.active and not timer.zone_known
    timer.enter_zone("Kingsmarch", now=5.0)
    assert timer.phase is HideoutTimerPhase.OUTSIDE_HIDEOUT
    assert timer.zone_known and not timer.in_hideout
    timer.enter_zone("Coastal Hideout", now=6.0)
    assert timer.phase is HideoutTimerPhase.IN_HIDEOUT
    assert timer.started_at == 6.0
    assert timer.consume_due_notification(now=16.0) == 1
    assert timer.phase is HideoutTimerPhase.NOTIFIED
    assert timer.active and timer.zone_known and timer.in_hideout and timer.notified
    assert replace(timer) == timer
    timer.enter_zone("Another Hideout", now=20.0)
    assert timer.phase is HideoutTimerPhase.NOTIFIED
    assert timer.started_at == 6.0

    timer.set_repeat(True)
    assert timer.phase is HideoutTimerPhase.IN_HIDEOUT
    assert not timer.notified
    assert timer.consume_due_notification(now=20.0) is None
    assert timer.consume_due_notification(now=26.0) == 2
    timer.set_repeat(False)
    assert timer.phase is HideoutTimerPhase.NOTIFIED
    assert timer.last_due_slot == 2
    assert timer.consume_due_notification(now=36.0) is None
    timer.set_duration(20, now=36.0)
    assert timer.phase is HideoutTimerPhase.IN_HIDEOUT
    assert timer.started_at == 36.0 and timer.last_due_slot == 0
    timer.reset_to_unknown()
    assert timer.phase is HideoutTimerPhase.AWAITING_ZONE
    assert timer.started_at is None and timer.last_due_slot == 0
    timer.disable()
    assert timer.phase is HideoutTimerPhase.DISABLED
    assert timer.started_at is None


def test_hideout_rejects_missing_start_time_before_entering_hideout():
    timer = HideoutTimerState()
    with pytest.raises(ValueError, match="requires a start time"):
        timer.enable("Coastal Hideout", now=None)
    assert timer.phase is HideoutTimerPhase.DISABLED
    assert timer.started_at is None


def test_update_check_state_ignores_stale_result_after_timeout(qapp, monkeypatch):
    workers = []
    controller = UpdateController(thread_factory=lambda task: Mock(start=lambda: workers.append(task)))
    monkeypatch.setattr(qt_controller, "fetch_latest_release", lambda _: None)
    finished = Mock()
    controller.check_finished.connect(finished)
    assert controller.check_state is UpdateCheckState.IDLE

    controller.check(False)
    assert controller.check_state is UpdateCheckState.CHECKING
    assert controller.checking
    controller._expire_check()
    assert controller.check_state is UpdateCheckState.IDLE
    controller.check(True)
    workers[0]()
    assert controller.check_state is UpdateCheckState.CHECKING
    finished.assert_not_called()
    workers[1]()
    assert controller.check_state is UpdateCheckState.IDLE
    assert not controller.checking
    finished.assert_called_once_with(None, True)


def test_update_download_preserves_worker_ownership_until_cancel_completes(qapp, monkeypatch, tmp_path):
    workers = []
    controller = UpdateController(thread_factory=lambda task: Mock(start=lambda: workers.append(task)))
    release = ReleaseInfo("2.5.0", "", "page", "zip", "checksum")
    source = tmp_path / "source.zip"
    with ZipFile(source, "w") as archive:
        archive.writestr("PoENavi.exe", b"app")
        archive.writestr("PoENaviUpdater.exe", b"updater")
    content = source.read_bytes()

    def download(url, destination, _progress, _cancelled):
        if url == release.checksum_url:
            destination.write_text(
                f"{sha256(content).hexdigest()}  PoENavi.zip\n", encoding="utf-8",
            )
        else:
            destination.write_bytes(content)
        return destination

    monkeypatch.setattr(qt_controller, "download_file", download)
    notifications = []
    controller.download_ready.connect(lambda *_: notifications.append(controller.download_state))
    controller.download_cancelled.connect(lambda: notifications.append(controller.download_state))
    assert controller.download_state is UpdateDownloadState.IDLE
    try:
        controller.download(release)
        assert controller.download_state is UpdateDownloadState.DOWNLOADING
        workers.pop()()
        assert controller.download_state is UpdateDownloadState.READY
        assert not controller._downloading

        controller.download(release)
        controller.discard_download()
        assert controller.download_state is UpdateDownloadState.CANCELLING
        assert controller._downloading
        work_dir = controller._work_dir
        assert work_dir.is_dir()
        controller.download(release)
        assert len(workers) == 1
        workers.pop()()
        assert controller.download_state is UpdateDownloadState.IDLE
        assert not work_dir.exists()
        assert notifications == [UpdateDownloadState.READY, UpdateDownloadState.IDLE]

        controller.download(release)
        workers.pop()()
        assert controller.download_state is UpdateDownloadState.READY
        controller.discard_download()
        assert controller.download_state is UpdateDownloadState.IDLE
    finally:
        controller.discard_download()
        for work in workers:
            work()


def test_suppressed_hotkey_tracks_context_and_clears_pending_release(qapp):
    foreground = 10
    callbacks = {}
    hook = Mock(is_running=True)

    def make_hook(_hotkey, **options):
        callbacks.update(options)
        return hook

    service = ForegroundSuppressedHotkeyService(
        "poetore_capture", "alt+d", platform="win32",
        native_hook_factory=make_hook, foreground_getter=lambda: foreground,
        poe_window_checker=lambda hwnd: hwnd == 10,
        result_window_checker=lambda hwnd: hwnd == 20,
        poe_target_getter=lambda: 10, focus_target=lambda _: True,
    )
    commands = []
    service.command.connect(commands.append)
    assert service.state is SuppressedHotkeyState.STOPPED
    assert service.foreground_context is ForegroundContext.OUTSIDE
    service.start()
    try:
        assert service.state is SuppressedHotkeyState.ARMED
        assert service.is_running and service.is_registered
        assert service.foreground_context is ForegroundContext.POE
        assert callbacks["should_suppress"]()
        callbacks["on_event"]("pressed")
        callbacks["on_event"]("pressed")
        assert service.state is SuppressedHotkeyState.AWAITING_RELEASE
        assert service._waiting_for_release
        assert commands == []

        foreground = 20
        callbacks["on_event"]("released")
        assert service.state is SuppressedHotkeyState.ARMED
        assert service.foreground_context is ForegroundContext.RESULT
        assert commands == ["poetore_capture", "poetore_capture_released"]
        callbacks["on_event"]("pressed")
        service.stop()
        callbacks["on_event"]("released")
        assert service.state is SuppressedHotkeyState.STOPPED
        assert not service.is_running and not service._waiting_for_release
        assert len(commands) == 2
    finally:
        service.stop()


@pytest.mark.parametrize("outcome", ["switch", "restore", "restart"])
def test_app_session_finishes_switch_in_state_matching_live_window(qapp, monkeypatch, outcome):
    app = Mock()
    old_window = Mock(config={})
    new_window = Mock(config={})
    controller = AppSessionController(app, Mock())
    initial_target = (POENAVI_MODE, "poe1")
    next_target = (POETORE_MODE, "poe1")

    def create(*target):
        if controller.state is AppSessionState.IDLE:
            assert target == initial_target
            return old_window
        assert controller.state is AppSessionState.SWITCHING
        assert not controller.switch_target(*initial_target)
        if target == next_target and outcome != "switch":
            raise RuntimeError("could not create target window")
        return new_window

    monkeypatch.setattr(app_composition, "create_mode_window", create)
    monkeypatch.setattr(app_session, "save_app_target", lambda *_: {})
    monkeypatch.setattr(app_session, "switch_app_target_and_restart", lambda *_: outcome == "restart")
    assert controller.state is AppSessionState.IDLE
    assert controller.start(*initial_target) is old_window
    assert controller.state is AppSessionState.RUNNING
    assert controller.switch_target(*next_target) is (outcome != "restore")
    assert not controller._switching
    if outcome == "restart":
        assert controller.state is AppSessionState.STOPPED
        assert controller.window is None
    else:
        assert controller.state is AppSessionState.RUNNING
        assert controller.window is new_window
        assert controller.target == (next_target if outcome == "switch" else initial_target)
    app.aboutToQuit.connect.call_args.args[0]()
    assert controller.state is AppSessionState.STOPPED
    assert not controller.switch_target(*next_target)


def test_audio_stays_busy_until_stopped_worker_returns(qapp, monkeypatch, tmp_path):
    workers = []
    monkeypatch.setattr(
        notification_audio.threading, "Thread",
        lambda target, args, **_: Mock(start=lambda: workers.append(lambda: target(*args))),
    )
    player = NotificationAudioPlayer()
    played = Mock()
    monkeypatch.setattr(player, "_play_file", played)
    finished_states = []
    player.finished.connect(lambda: finished_states.append(player.state))
    path = tmp_path / "notice.wav"
    assert player.state is AudioPlaybackState.IDLE
    player.stop()
    assert player.play(path, path, 50)
    assert player.state is AudioPlaybackState.PLAYING and player.is_playing
    assert not player._stop_event.is_set()

    player.stop()
    player.stop()
    assert player.state is AudioPlaybackState.STOPPING and player.is_playing
    assert player._stop_event.is_set()
    assert not player.play(path, path, 50)
    workers.pop()()
    assert player.state is AudioPlaybackState.IDLE and not player.is_playing
    assert finished_states == [AudioPlaybackState.IDLE]
    played.assert_called_once_with(path, 50)


def test_audio_returns_to_idle_if_thread_start_fails(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(
        notification_audio.threading, "Thread",
        Mock(return_value=Mock(start=Mock(side_effect=RuntimeError("thread unavailable")))),
    )
    player = NotificationAudioPlayer()
    path = tmp_path / "notice.wav"
    with pytest.raises(RuntimeError, match="thread unavailable"):
        player.play(path, path, 50)
    assert player.state is AudioPlaybackState.IDLE and not player.is_playing
