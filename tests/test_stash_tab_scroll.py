import ctypes
import sys
from unittest.mock import Mock

import pytest

from src.utils.raw_input_wheel import (
    _RAWINPUT,
    _RAWINPUTDEVICE,
    _RAWINPUTHEADER,
    _RAWMOUSE,
    _Win32RawInputWheelListener,
    _wheel_direction,
)
from src.utils.stash_tab_scroll import StashTabScrollController, is_stash_area


def test_awakened_stash_area_ratio_is_used():
    rect = (100, 200, 1920, 1080)
    assert is_stash_area(300, 400, rect)
    assert not is_stash_area(900, 400, rect)
    assert not is_stash_area(300, 250, rect)
    assert not is_stash_area(300, 400, None)


def test_ctrl_wheel_outside_stash_sends_one_directional_key():
    tapped = []
    controller = StashTabScrollController(
        foreground_window=lambda: 123,
        is_poe_window=lambda _hwnd: True,
        window_rect=lambda _hwnd: (0, 0, 1920, 1080),
        ctrl_pressed=lambda: True,
        tap_key=tapped.append,
    )

    controller.handle_scroll(1200, 500, 0, 1)
    controller.handle_scroll(1200, 500, 0, -1)

    assert tapped == ["left", "right"]


def test_scroll_is_ignored_when_disabled_ctrl_released_or_poe_inactive():
    tapped = []
    variants = (
        StashTabScrollController(
            enabled=False,
            foreground_window=lambda: 123,
            is_poe_window=lambda _hwnd: True,
            ctrl_pressed=lambda: True,
            tap_key=tapped.append,
        ),
        StashTabScrollController(
            foreground_window=lambda: 123,
            is_poe_window=lambda _hwnd: True,
            ctrl_pressed=lambda: False,
            tap_key=tapped.append,
        ),
        StashTabScrollController(
            foreground_window=lambda: 123,
            is_poe_window=lambda _hwnd: False,
            ctrl_pressed=lambda: True,
            tap_key=tapped.append,
        ),
    )
    for controller in variants:
        controller.handle_scroll(1200, 500, 0, -1)

    assert tapped == []


def test_scroll_inside_stash_is_left_to_poe_native_handling():
    tapped = []
    controller = StashTabScrollController(
        foreground_window=lambda: 123,
        is_poe_window=lambda _hwnd: True,
        window_rect=lambda _hwnd: (0, 0, 1920, 1080),
        ctrl_pressed=lambda: True,
        tap_key=tapped.append,
    )

    controller.handle_scroll(300, 500, 0, -1)

    assert tapped == []


@pytest.mark.parametrize(
    ("device_type", "flags", "button_data", "direction"),
    [
        (0, 0x0400, 120, 1),
        (0, 0x0400, 65416, -1),
        (0, 0x0400, 0, 0),
        (0, 0x0401, 1, 1),
        (0, 0x0800, 120, 0),
        (0, 0, 120, 0),
        (1, 0x0400, 120, 0),
    ],
)
def test_raw_input_wheel_direction(device_type, flags, button_data, direction):
    assert _wheel_direction(device_type, flags, button_data) == direction


def test_disabled_controller_starts_and_stops_listener_on_settings_change():
    factory = Mock()
    controller = StashTabScrollController(enabled=False, listener_factory=factory)

    controller.start()
    factory.assert_not_called()

    controller.set_enabled(True)
    factory.assert_called_once_with(on_scroll=controller.handle_scroll)
    factory.return_value.start.assert_called_once_with()

    controller.set_enabled(False)
    factory.return_value.stop.assert_called_once_with()


def test_enabling_controller_before_start_or_after_stop_does_not_start_listener():
    factory = Mock()
    controller = StashTabScrollController(enabled=False, listener_factory=factory)

    controller.set_enabled(True)
    factory.assert_not_called()

    controller.start()
    factory.return_value.start.assert_called_once_with()
    controller.stop()
    factory.return_value.stop.assert_called_once_with()

    controller.set_enabled(False)
    controller.set_enabled(True)
    factory.return_value.start.assert_called_once_with()
    factory.return_value.stop.assert_called_once_with()


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Win32 Raw Input")
def test_win32_raw_input_layout_and_listener_lifecycle(capsys):
    pointer_size = ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(_RAWINPUTHEADER) == 8 + 2 * pointer_size
    assert ctypes.sizeof(_RAWMOUSE) == 24
    assert _RAWMOUSE.usButtonFlags.offset == 4
    assert _RAWMOUSE.usButtonData.offset == 6
    assert _RAWINPUT.mouse.offset == ctypes.sizeof(_RAWINPUTHEADER)
    assert ctypes.sizeof(_RAWINPUT) == 32 + 2 * pointer_size
    assert ctypes.sizeof(_RAWINPUTDEVICE) == 8 + pointer_size

    listener = _Win32RawInputWheelListener(on_scroll=Mock())
    for _ in range(2):
        try:
            listener.start()
            assert listener._hwnd
            assert listener._thread.is_alive()
        finally:
            listener.stop()
        assert not listener._thread.is_alive()
        assert listener._hwnd is None
    assert "[STASH SCROLL]" not in capsys.readouterr().out
