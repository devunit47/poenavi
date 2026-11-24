import ctypes
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.utils.internal_key_input import internal_key_input
from src.utils.win32_suppressed_hotkey import (
    HotkeyEventProcessor,
    VK_CONTROL,
    VK_LCONTROL,
    VK_LMENU,
    VK_MENU,
    VK_RCONTROL,
    VK_SHIFT,
    WM_QUIT,
    _parse_hotkey,
    Win32SuppressedHotkeyHook,
)


def test_parse_hotkey_accepts_required_modifier_and_regular_key():
    assert _parse_hotkey("Alt+D") == (frozenset({"alt"}), ord("D"))
    assert _parse_hotkey("ctrl+1") == (frozenset({"ctrl"}), ord("1"))
    assert _parse_hotkey("ctrl+F5") == (frozenset({"ctrl"}), 0x74)
    assert _parse_hotkey("alt+Space") == (frozenset({"alt"}), 0x20)
    assert _parse_hotkey("Shift+Ctrl+Alt+R") == (
        frozenset({"ctrl", "alt", "shift"}), ord("R")
    )


def test_parse_hotkey_accepts_single_key_only_when_explicitly_enabled():
    assert _parse_hotkey("D", allow_unmodified=True) == (frozenset(), ord("D"))
    assert _parse_hotkey("F5", allow_unmodified=True) == (frozenset(), 0x74)
    with pytest.raises(ValueError):
        _parse_hotkey("D")


@pytest.mark.parametrize("hotkey", ["d", "win+d", "alt+escape", "ctrl+", "ctrl+ctrl+d"])
def test_parse_hotkey_rejects_unsupported_bindings(hotkey):
    with pytest.raises(ValueError):
        _parse_hotkey(hotkey)


def test_processor_suppresses_target_only_in_allowed_context():
    allowed = {"value": False}
    events = []
    processor = HotkeyEventProcessor(
        VK_MENU, ord("D"), lambda: allowed["value"], events.append,
    )

    assert processor.process(VK_LMENU, True) is False
    assert processor.process(ord("D"), True) is False
    assert processor.process(ord("D"), False) is False

    allowed["value"] = True
    assert processor.process(ord("D"), True) is True
    assert processor.process(ord("D"), True) is True  # auto-repeat
    assert processor.process(ord("D"), False) is True
    assert processor.process(VK_LMENU, False) is False
    assert events == ["pressed", "released"]


def test_processor_suppresses_unmodified_target_without_modifier():
    events = []
    processor = HotkeyEventProcessor(
        None, ord("D"), lambda: True, events.append,
    )
    assert processor.process(ord("D"), True) is True
    assert processor.process(ord("D"), True) is True
    assert processor.process(ord("D"), False) is True
    assert events == ["pressed", "released"]


def test_processor_does_not_treat_modified_key_as_unmodified_hotkey():
    events = []
    processor = HotkeyEventProcessor(
        None, ord("D"), lambda: True, events.append,
    )
    assert processor.process(VK_CONTROL, True) is False
    assert processor.process(ord("D"), True) is False
    assert processor.process(ord("D"), False) is False
    assert processor.process(VK_CONTROL, False) is False
    assert events == []


def test_processor_requires_exact_modifier_set_for_multi_modifier_hotkey():
    events = []
    processor = HotkeyEventProcessor(
        frozenset({"ctrl", "alt", "shift"}), ord("R"),
        lambda: True, events.append,
    )
    for modifier in (VK_CONTROL, VK_MENU, VK_SHIFT):
        assert processor.process(modifier, True) is False
    assert processor.process(ord("R"), True) is True
    assert processor.process(ord("R"), False) is True
    assert events == ["pressed", "released"]


def test_processor_rejects_extra_modifier():
    events = []
    processor = HotkeyEventProcessor(
        frozenset({"ctrl", "alt"}), ord("R"), lambda: True, events.append,
    )
    for modifier in (VK_CONTROL, VK_MENU, VK_SHIFT):
        processor.process(modifier, True)
    assert processor.process(ord("R"), True) is False
    assert processor.process(ord("R"), False) is False
    assert events == []


@pytest.mark.parametrize("first, second", [(VK_LCONTROL, VK_RCONTROL), (VK_RCONTROL, VK_LCONTROL)])
def test_processor_keeps_ctrl_active_until_both_sides_are_released(first, second):
    events = []
    processor = HotkeyEventProcessor(VK_CONTROL, ord("D"), lambda: True, events.append)

    processor.process(first, True)
    processor.process(second, True)
    processor.process(first, False)
    assert processor.process(ord("D"), True) is True
    assert processor.process(ord("D"), False) is True

    processor.process(second, False)
    assert processor.process(ord("D"), True) is False
    assert events == ["pressed", "released"]


def test_processor_recognizes_injected_modifier_from_external_software():
    events = []
    processor = HotkeyEventProcessor(
        VK_MENU, ord("D"), lambda: True, events.append,
    )
    assert processor.process(VK_MENU, True, injected=True) is False
    assert processor.process(ord("D"), True) is True
    assert processor.process(ord("D"), False) is True
    assert processor.process(VK_MENU, False, injected=True) is False
    assert events == ["pressed", "released"]


def test_processor_recognizes_fully_injected_hotkey_from_external_software():
    events = []
    processor = HotkeyEventProcessor(
        VK_MENU, ord("D"), lambda: True, events.append,
    )
    assert processor.process(VK_MENU, True, injected=True) is False
    assert processor.process(ord("D"), True, injected=True) is True
    assert processor.process(ord("D"), False, injected=True) is True
    assert processor.process(VK_MENU, False, injected=True) is False
    assert events == ["pressed", "released"]


def test_processor_leaves_internal_input_unsuppressed_when_callback_rejects_it():
    events = []
    processor = HotkeyEventProcessor(
        VK_CONTROL, ord("C"), lambda: False, events.append,
    )
    assert processor.process(VK_CONTROL, True, injected=True) is False
    assert processor.process(ord("C"), True, injected=True) is False
    assert processor.process(ord("C"), False, injected=True) is False
    assert processor.process(VK_CONTROL, False, injected=True) is False
    assert events == []


def test_injected_key_up_does_not_release_a_physical_key():
    events = []
    processor = HotkeyEventProcessor(VK_CONTROL, ord("D"), lambda: True, events.append)
    processor.process(VK_LCONTROL, True)
    assert processor.process(VK_LCONTROL, False, injected=True) is False
    assert processor.process(ord("D"), True) is True
    assert processor.process(ord("D"), True, injected=True) is False
    assert processor.process(ord("D"), False, injected=True) is False
    assert events == ["pressed"]
    assert processor.process(ord("D"), False) is True
    assert events == ["pressed", "released"]


def test_processor_ignores_internal_injected_input_before_updating_state():
    events = []
    processor = HotkeyEventProcessor(VK_CONTROL, ord("D"), lambda: True, events.append)

    with internal_key_input(cooldown_seconds=0):
        assert processor.process(VK_CONTROL, True, injected=True) is False
        assert processor.process(ord("D"), True, injected=True) is False
    assert processor.process(ord("D"), True) is False

    processor.process(VK_CONTROL, True)
    with internal_key_input(cooldown_seconds=0):
        assert processor.process(ord("D"), True, injected=True) is False
    assert events == []


def test_stop_timeout_keeps_callback_and_hook_alive(monkeypatch):
    hook = Win32SuppressedHotkeyHook(
        "alt+d", should_suppress=lambda: True, on_event=lambda _event: None,
    )
    user32 = Mock()
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=user32), raising=False)
    thread = Mock()
    thread.is_alive.return_value = True
    callback, native_hook = object(), object()
    hook._thread = thread
    hook._thread_id = 7
    hook._callback = callback
    hook._hook = native_hook

    hook.stop(timeout=0)

    assert hook._stop_requested.is_set()
    thread.join.assert_called_once_with(0)
    user32.PostThreadMessageW.assert_called_once_with(7, WM_QUIT, 0, 0)
    assert hook._thread is thread
    assert hook._callback is callback
    assert hook._hook is native_hook
    with pytest.raises(RuntimeError, match="still stopping"):
        hook.start()


@pytest.mark.parametrize("stop_before_queue", [True, False])
def test_stop_before_message_loop_is_honored(monkeypatch, stop_before_queue):
    hook = Win32SuppressedHotkeyHook(
        "alt+d", should_suppress=lambda: True, on_event=lambda _event: None,
    )
    user32 = Mock()
    user32.GetMessageW.return_value = 0
    kernel32 = Mock()
    kernel32.GetCurrentThreadId.return_value = 7
    monkeypatch.setattr(
        ctypes, "windll", SimpleNamespace(user32=user32, kernel32=kernel32), raising=False,
    )
    monkeypatch.setattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE, raising=False)

    def stop_before_loop(*_args):
        hook.stop(timeout=0)
        return 123

    if stop_before_queue:
        user32.PeekMessageW.side_effect = stop_before_loop
        with pytest.raises(RuntimeError, match="startup was cancelled"):
            hook.start()
        user32.PostThreadMessageW.assert_not_called()
        user32.SetWindowsHookExW.assert_not_called()
    else:
        user32.SetWindowsHookExW.side_effect = stop_before_loop
        hook.start()
        user32.PostThreadMessageW.assert_called_once_with(7, WM_QUIT, 0, 0)

    hook.stop()
    user32.GetMessageW.assert_not_called()
    if not stop_before_queue:
        user32.UnhookWindowsHookEx.assert_called_once_with(123)
    assert not hook.is_running
    assert hook._callback is None


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 hook smoke test")
def test_native_hook_can_start_and_stop_on_windows():
    hook = Win32SuppressedHotkeyHook(
        "alt+f24", should_suppress=lambda: False, on_event=lambda _event: None,
    )
    hook.start()
    assert hook.is_running
    hook.stop()
    assert not hook.is_running
