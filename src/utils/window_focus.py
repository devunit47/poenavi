"""Windows foreground-window helpers for search-string paste experiments."""

import ctypes
import sys
import time
from ctypes import wintypes
from functools import cache
from pathlib import PureWindowsPath


SW_RESTORE = 9


@cache
def _window_api():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    hwnd = wintypes.HWND
    dword = wintypes.DWORD
    bool_type = wintypes.BOOL
    int_type = ctypes.c_int
    dword_pointer = ctypes.POINTER(dword)
    signatures = (
        (user32, (
            ("GetWindowThreadProcessId", [hwnd, dword_pointer], dword),
            ("GetForegroundWindow", [], hwnd),
            ("GetWindowRect", [hwnd, ctypes.POINTER(wintypes.RECT)], bool_type),
            ("IsWindow", [hwnd], bool_type),
            ("IsIconic", [hwnd], bool_type),
            ("ShowWindow", [hwnd, int_type], bool_type),
            ("BringWindowToTop", [hwnd], bool_type),
            ("SetForegroundWindow", [hwnd], bool_type),
            ("SetFocus", [hwnd], hwnd),
            ("AttachThreadInput", [dword, dword, bool_type], bool_type),
            ("GetWindow", [hwnd, wintypes.UINT], hwnd),
            ("IsWindowVisible", [hwnd], bool_type),
            ("GetWindowTextLengthW", [hwnd], int_type),
            ("GetParent", [hwnd], hwnd),
            ("keybd_event", [wintypes.BYTE, wintypes.BYTE, dword, ctypes.c_size_t], None),
        )),
        (kernel32, (
            ("OpenProcess", [dword, bool_type, dword], wintypes.HANDLE),
            ("QueryFullProcessImageNameW", [
                wintypes.HANDLE, dword, wintypes.LPWSTR, dword_pointer,
            ], bool_type),
            ("CloseHandle", [wintypes.HANDLE], bool_type),
            ("GetCurrentThreadId", [], dword),
            ("GetCurrentProcessId", [], dword),
        )),
    )
    for dll, functions in signatures:
        for name, argtypes, restype in functions:
            function = getattr(dll, name)
            function.argtypes = argtypes
            function.restype = restype
    return user32, kernel32


def _restore_window_if_minimized(user32, hwnd) -> bool:
    """Restore hwnd only when Windows reports that it is minimized."""
    if not user32.IsIconic(hwnd):
        return False
    user32.ShowWindow(hwnd, SW_RESTORE)
    return True


def is_path_of_exile_process_name(process_name: str) -> bool:
    """Path of Exileの実行ファイル名だけを安全な送信先として受け入れる。"""
    name = PureWindowsPath(process_name or "").name.lower()
    return name.startswith("pathofexile") and name.endswith(".exe")


def is_path_of_exile_window(hwnd) -> bool:
    """指定ウィンドウがPath of Exileプロセスのものか確認する。"""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        user32, kernel32 = _window_api()
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        if not pid.value:
            return False

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not process:
            return False
        try:
            size = wintypes.DWORD(32768)
            path = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(size)):
                return False
            return is_path_of_exile_process_name(path.value)
        finally:
            kernel32.CloseHandle(process)
    except Exception as exc:
        print(f"[WINDOW] Path of Exile process check failed: {exc}")
        return False


def get_foreground_window():
    """Return the current foreground window handle, or None outside Windows."""
    if sys.platform != "win32":
        return None
    try:
        user32, _ = _window_api()
        hwnd = user32.GetForegroundWindow()
        return int(hwnd) if hwnd else None
    except Exception as exc:
        print(f"[WINDOW] GetForegroundWindow failed: {exc}")
        return None


def get_window_rect(hwnd):
    """Return a window's outer bounds as (x, y, width, height)."""
    if sys.platform != "win32" or not hwnd:
        return None
    try:
        user32, _ = _window_api()
        rect = wintypes.RECT()
        if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            return None
        return (
            rect.left,
            rect.top,
            rect.right - rect.left,
            rect.bottom - rect.top,
        )
    except Exception as exc:
        print(f"[WINDOW] GetWindowRect failed: {exc}")
        return None


def focus_window(hwnd, wait_seconds=0.12):
    """Best-effort foreground restore for a previously captured HWND."""
    if sys.platform != "win32" or not hwnd:
        return False

    try:
        user32, kernel32 = _window_api()

        hwnd = wintypes.HWND(hwnd)
        if not user32.IsWindow(hwnd):
            print("[WINDOW] target window no longer exists")
            return False

        _restore_window_if_minimized(user32, hwnd)

        foreground = user32.GetForegroundWindow()
        current_thread = kernel32.GetCurrentThreadId()
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)
        foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0

        attached_target = False
        attached_foreground = False
        if target_thread and target_thread != current_thread:
            attached_target = bool(user32.AttachThreadInput(current_thread, target_thread, True))
        if foreground_thread and foreground_thread != current_thread:
            attached_foreground = bool(user32.AttachThreadInput(current_thread, foreground_thread, True))

        def hwnd_value(value):
            return int(getattr(value, "value", value) or 0)

        def request_foreground():
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetFocus(hwnd)

        try:
            request_foreground()
        finally:
            if attached_foreground:
                user32.AttachThreadInput(current_thread, foreground_thread, False)
            if attached_target:
                user32.AttachThreadInput(current_thread, target_thread, False)

        target_value = hwnd_value(hwnd)
        deadline = time.time() + max(wait_seconds, 0.5)
        while time.time() < deadline:
            if hwnd_value(user32.GetForegroundWindow()) == target_value:
                return True
            time.sleep(0.05)

        # Windows のフォアグラウンド制限で失敗することがあるため、Alt入力で解除して再試行する。
        VK_MENU = 0x12
        KEYEVENTF_KEYUP = 0x0002
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        request_foreground()
        time.sleep(wait_seconds)
        return hwnd_value(user32.GetForegroundWindow()) == target_value
    except Exception as exc:
        print(f"[WINDOW] focus_window failed: {exc}")
        return False


def get_next_visible_window_after(hwnd, skip_current_process=False):
    """Return the next visible top-level window behind hwnd in Z-order on Windows.

    When skip_current_process is True, skip windows owned by this process. This is useful
    when a PoENavi popout/tool window is foreground and the target should be the game
    window behind all PoENavi windows.
    """
    if sys.platform != "win32" or not hwnd:
        return None
    try:
        user32, kernel32 = _window_api()
        GW_HWNDNEXT = 2
        current_pid = int(kernel32.GetCurrentProcessId())

        def window_pid(window):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
            return int(pid.value or 0)

        current = user32.GetWindow(wintypes.HWND(hwnd), GW_HWNDNEXT)
        while current:
            if user32.IsWindowVisible(current) and not user32.GetParent(current):
                # タイトルなしの補助ウィンドウは候補から外す。
                if user32.GetWindowTextLengthW(current) > 0:
                    if not skip_current_process or window_pid(current) != current_pid:
                        return int(current)
            current = user32.GetWindow(current, GW_HWNDNEXT)
    except Exception as exc:
        print(f"[WINDOW] get_next_visible_window_after failed: {exc}")
    return None
