import ctypes
from ctypes import wintypes
from types import SimpleNamespace
from unittest.mock import Mock, call

from src.utils import window_focus
from src.utils.window_focus import SW_RESTORE, _restore_window_if_minimized


def test_minimized_window_is_restored_before_focusing():
    user32 = Mock()
    user32.IsIconic.return_value = True
    hwnd = 123

    restored = _restore_window_if_minimized(user32, hwnd)

    assert restored is True
    user32.ShowWindow.assert_called_once_with(hwnd, SW_RESTORE)


def test_non_minimized_window_is_not_restored():
    user32 = Mock()
    user32.IsIconic.return_value = False
    hwnd = 123

    restored = _restore_window_if_minimized(user32, hwnd)

    assert restored is False
    user32.ShowWindow.assert_not_called()


def test_window_helpers_share_pointer_signature_without_mutating_windll(monkeypatch):
    user32 = Mock()
    kernel32 = Mock()
    shared_user32 = Mock()
    shared_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=shared_user32), raising=False)
    load_dll = Mock(side_effect=[user32, kernel32])
    monkeypatch.setattr(ctypes, "WinDLL", load_dll, raising=False)
    monkeypatch.setattr(window_focus, "sys", SimpleNamespace(platform="win32"))

    expected = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

    def get_thread_id(_window, pid_pointer):
        assert user32.GetWindowThreadProcessId.argtypes == expected
        assert user32.GetWindowThreadProcessId.restype is wintypes.DWORD
        if pid_pointer is not None:
            ctypes.cast(pid_pointer, expected[1]).contents.value = 42
        return 7

    user32.GetWindowThreadProcessId.side_effect = get_thread_id
    user32.GetForegroundWindow.return_value = 123
    user32.IsIconic.return_value = False
    user32.GetWindow.return_value = 456
    user32.GetParent.return_value = None
    user32.GetWindowTextLengthW.return_value = 10
    kernel32.GetCurrentThreadId.return_value = 7
    kernel32.GetCurrentProcessId.return_value = 99
    kernel32.OpenProcess.return_value = 777

    def query_image(_process, _flags, path, _size):
        path.value = r"C:\Games\PathOfExile.exe"
        return True

    kernel32.QueryFullProcessImageNameW.side_effect = query_image
    window_focus._window_api.cache_clear()
    try:
        assert window_focus.focus_window(123)
        assert window_focus.is_path_of_exile_window(123)
        assert window_focus.get_next_visible_window_after(123, skip_current_process=True) == 456
        assert window_focus.focus_window(123)
    finally:
        window_focus._window_api.cache_clear()

    assert user32.GetWindowThreadProcessId.call_count == 6
    assert load_dll.call_args_list == [
        call("user32", use_last_error=True), call("kernel32", use_last_error=True),
    ]
    assert shared_user32.GetWindowThreadProcessId.argtypes == [wintypes.HWND, ctypes.c_void_p]
    shared_user32.GetWindowThreadProcessId.assert_not_called()
    assert user32.SetFocus.restype is wintypes.HWND
    assert kernel32.QueryFullProcessImageNameW.argtypes == [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, expected[1],
    ]
    kernel32.CloseHandle.assert_called_once_with(777)
