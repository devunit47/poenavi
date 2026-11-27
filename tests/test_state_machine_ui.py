from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPoint, QRect, QTimer, Qt
from PySide6.QtWidgets import QWidget

from src.poetore.ui import AutoHideDisplayState, ObsWindowState, PoetoreWindow
from src.poetore.window_position import PlacementContext
from src.ui.main_window import MainWindow, RunTimerState
from src.ui.mini_navi import MiniNaviObsState, MiniNaviOverlay, TopmostForegroundKind
from src.utils.poe_version_data import POE1


def test_timer_compatibility_flags_are_exclusive_without_qt_init():
    window = MainWindow.__new__(MainWindow)
    assert window.timer_state is RunTimerState.IDLE

    window.timer_ready = True
    window.is_running = False
    assert window.timer_state is RunTimerState.READY
    assert window.timer_ready and not window.is_running

    window.is_running = True
    window.timer_ready = True
    assert window.timer_state is RunTimerState.RUNNING
    assert window.is_running and not window.timer_ready

    window.is_running = False
    assert window.timer_state is RunTimerState.IDLE

    window.is_running = True
    window.lap_times = [0.0]
    window.is_running = False
    window.timer_ready = False
    assert window.timer_state is RunTimerState.PAUSED
    assert not window.is_running and not window.timer_ready


def test_restored_timer_resumes_and_resets(monkeypatch):
    window = MainWindow.__new__(MainWindow)
    window.poe_version = POE1
    window.config = {"confirm_reset": False}
    window.timer = Mock()
    window.current_zone = ""
    window.update_text = Mock()
    window.update_lap_display = Mock()
    window._save_timer_state = Mock()
    window._clear_saved_timer = Mock()
    window._load_timer_state_payload = Mock(return_value={"accumulated_time": 10.0})
    window._set_part2 = Mock()
    window._update_visit_btn = Mock()
    window.map_thumbnail = Mock()
    clock = Mock(return_value=100.0)
    monkeypatch.setattr("src.ui.main_window.time.time", clock)

    window._restore_timer_state()
    assert window.timer_state is RunTimerState.PAUSED

    window.start_timer()
    assert window.timer_state is RunTimerState.RUNNING
    clock.return_value = 102.0
    window.stop_timer()
    assert window.timer_state is RunTimerState.PAUSED
    assert window.accumulated_time == 12.0

    window.reset_timer()
    assert window.timer_state is RunTimerState.IDLE
    assert window.accumulated_time == 0.0


@pytest.mark.parametrize("release_before_show", [True, False])
def test_auto_hide_remembers_release_across_result_display(qtbot, monkeypatch, release_before_show):
    window = PoetoreWindow()
    qtbot.addWidget(window)
    context = PlacementContext(QRect(0, 0, 800, 600), QPoint(500, 400))
    monkeypatch.setattr("src.poetore.ui.capture_placement_context", lambda: context)
    monkeypatch.setattr("pynput.keyboard.Controller", Mock())
    monkeypatch.setattr(QTimer, "singleShot", Mock())
    monkeypatch.setattr(window, "_send_copy", Mock())
    monkeypatch.setattr(window, "_start_outside_click_listener", Mock())
    monkeypatch.setattr(window, "_global_cursor_point", QPoint)

    window.capture_from_poe(auto_hide=True, capture_hotkey="ctrl+d")
    assert window.auto_hide_state is AutoHideDisplayState.INACTIVE
    if release_before_show:
        window.capture_hotkey_released()
        assert window.auto_hide_state is AutoHideDisplayState.INACTIVE

    window.show_at_context(context, activate=False)
    if not release_before_show:
        assert window.auto_hide_state is AutoHideDisplayState.PASSIVE_HOLDING
        window.capture_hotkey_released()
    assert window.auto_hide_state is AutoHideDisplayState.PASSIVE_RELEASED
    assert window._passive_hotkey_display and not window._auto_hide_interactive

    window._handle_global_mouse_move(context.cursor_pos.x() + 41, context.cursor_pos.y())
    assert window.auto_hide_state is AutoHideDisplayState.INACTIVE
    assert not window.isVisible()


def test_poetore_obs_expands_and_collapse_ends_auto_hide_interaction(qtbot, monkeypatch):
    window = PoetoreWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(window, "_start_outside_click_listener", Mock())
    assert window.obs_window_state is ObsWindowState.DISABLED

    window.set_obs_streaming_mode(True)
    assert window.obs_window_state is ObsWindowState.COLLAPSED
    hwnd = window.winId()
    window._expand_for_obs()
    assert window.obs_window_state is ObsWindowState.EXPANDING
    assert window._obs_transitioning and not window._obs_collapsed
    assert not window.isVisible()

    window.show_at_context(activate=False)
    assert window.obs_window_state is ObsWindowState.EXPANDED
    assert window.auto_hide_state is AutoHideDisplayState.PASSIVE_HOLDING
    window._enter_auto_hide_interactive()
    assert window.auto_hide_state is AutoHideDisplayState.INTERACTIVE
    assert window._auto_hide_interactive and not window._passive_hotkey_display

    window.collapse_for_obs()
    assert window.obs_window_state is ObsWindowState.COLLAPSED
    assert window.auto_hide_state is AutoHideDisplayState.INACTIVE
    assert window.winId() == hwnd

    window._expand_for_obs()
    window.set_obs_streaming_mode(False)
    assert window.obs_window_state is ObsWindowState.DISABLED
    assert not (window._obs_streaming_mode or window._obs_transitioning or window._obs_collapsed)
    assert window.windowType() == Qt.Tool


@pytest.fixture
def mini_navi(qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.config = {"mini_guide_overlay": {"enabled": True, "topmost_mode": "always"}}
    overlay = MiniNaviOverlay(parent)
    qtbot.addWidget(overlay)
    qtbot.addWidget(overlay.lock_button_window)
    return overlay


def test_mini_navi_obs_state_follows_content(mini_navi):
    assert mini_navi.obs_state is MiniNaviObsState.WAITING
    assert mini_navi._obs_waiting
    hwnd = mini_navi.winId()

    mini_navi.update_content({"text": "次のエリアへ進む", "direction": "e"})
    assert mini_navi.obs_state is MiniNaviObsState.ACTIVE
    assert not mini_navi._obs_waiting

    mini_navi.update_content(None)
    assert mini_navi.obs_state is MiniNaviObsState.WAITING
    assert mini_navi._obs_waiting
    assert mini_navi.winId() == hwnd


def test_mini_navi_topmost_foreground_kinds(mini_navi, monkeypatch):
    own_hwnd = int(mini_navi.winId())
    poe_hwnd = max(own_hwnd, int(mini_navi.lock_button_window.winId())) + 1
    other_hwnd = poe_hwnd + 1
    monkeypatch.setattr("src.ui.mini_navi.is_path_of_exile_window", lambda hwnd: hwnd == poe_hwnd)
    assert mini_navi._last_topmost_foreground_kind is TopmostForegroundKind.UNKNOWN

    for foreground, behind, kind, active in (
        (None, None, TopmostForegroundKind.NONE, False),
        (own_hwnd, None, TopmostForegroundKind.MINI_NAVI, False),
        (own_hwnd, poe_hwnd, TopmostForegroundKind.MINI_NAVI_OVER_POE, True),
        (poe_hwnd, None, TopmostForegroundKind.POE, True),
        (other_hwnd, None, TopmostForegroundKind.OTHER, False),
    ):
        monkeypatch.setattr("src.ui.mini_navi.get_foreground_window", Mock(return_value=foreground))
        monkeypatch.setattr("src.ui.mini_navi.get_next_visible_window_after", Mock(return_value=behind))
        assert mini_navi._poe_is_active_context() is active
        assert mini_navi._last_topmost_foreground_kind is kind
        assert mini_navi._last_topmost_foreground_kind == kind.value
