"""Win32 low-level keyboard hook for one conditionally suppressed hotkey."""

from __future__ import annotations

import ctypes
import queue
import sys
import threading
from ctypes import wintypes

from src.utils.internal_key_input import is_internal_key_input


WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
WH_KEYBOARD_LL = 13
LLKHF_INJECTED = 0x00000010
HC_ACTION = 0

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5
VK_LWIN = 0x5B
VK_RWIN = 0x5C

MODIFIER_GROUPS = {
    "ctrl": {VK_CONTROL, VK_LCONTROL, VK_RCONTROL},
    "alt": {VK_MENU, VK_LMENU, VK_RMENU},
    "shift": {VK_SHIFT, VK_LSHIFT, VK_RSHIFT},
    "win": {VK_LWIN, VK_RWIN},
}


def pressed_modifiers() -> tuple[str, ...]:
    """Read the current Windows modifier state outside the keyboard hook."""
    if sys.platform != "win32":
        return ()
    get_key_state = ctypes.windll.user32.GetAsyncKeyState
    return tuple(
        name for name, keys in MODIFIER_GROUPS.items()
        if any(get_key_state(key) & 0x8000 for key in keys)
    )


NAMED_VIRTUAL_KEYS = {
    "space": 0x20, "pageup": 0x21, "pagedown": 0x22,
    "end": 0x23, "home": 0x24, "left": 0x25, "up": 0x26,
    "right": 0x27, "down": 0x28, "insert": 0x2D,
}


def _parse_hotkey(
    hotkey: str, *, allow_unmodified: bool = False,
) -> tuple[frozenset[str], int]:
    parts = [
        part.strip().casefold()
        for part in str(hotkey or "").split("+")
        if part.strip()
    ]
    aliases = {"control": "ctrl"}
    parts = [aliases.get(part, part) for part in parts]
    modifiers = parts[:-1]
    key = parts[-1] if parts else ""
    if not modifiers and not allow_unmodified:
        raise ValueError("suppressed hotkey requires Ctrl, Alt, or Shift")
    if (
        any(part not in {"ctrl", "alt", "shift"} for part in modifiers)
        or len(set(modifiers)) != len(modifiers)
        or key in {"ctrl", "alt", "shift", "win", "meta"}
    ):
        raise ValueError(
            "suppressed hotkey must use Ctrl/Alt/Shift and one regular key"
        )
    if len(key) == 1 and key.isascii() and key.isalnum():
        target_vk = ord(key.upper())
    elif key in NAMED_VIRTUAL_KEYS:
        target_vk = NAMED_VIRTUAL_KEYS[key]
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        target_vk = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError(f"unsupported suppressed hotkey key: {key}")
    return frozenset(modifiers), target_vk


class HotkeyEventProcessor:
    """Track modifier and target state for the native keyboard hook."""

    def __init__(
        self, required_modifier_groups, target_vk: int, should_suppress, on_event,
    ):
        if required_modifier_groups is None:
            required_modifier_groups = frozenset()
        elif isinstance(required_modifier_groups, int):
            required_modifier_groups = {
                VK_CONTROL: frozenset({"ctrl"}),
                VK_MENU: frozenset({"alt"}),
                VK_SHIFT: frozenset({"shift"}),
            }.get(required_modifier_groups, frozenset())
        self.required_modifier_groups = frozenset(required_modifier_groups)
        self.target_vk = target_vk
        self.should_suppress = should_suppress
        self.on_event = on_event
        self.reset()

    def reset(self) -> None:
        self._pressed_modifier_vks = {False: set(), True: set()}
        self._suppressed_target_source = None

    def process(self, vk_code: int, is_down: bool, *, injected: bool = False) -> bool:
        if injected and is_internal_key_input():
            return False
        if any(vk_code in keys for keys in MODIFIER_GROUPS.values()):
            pressed = self._pressed_modifier_vks[injected]
            if is_down:
                pressed.add(vk_code)
            else:
                pressed.discard(vk_code)
            return False
        if vk_code != self.target_vk:
            return False
        if self._suppressed_target_source is not None:
            if self._suppressed_target_source != injected:
                return False
            if not is_down:
                self._suppressed_target_source = None
                self.on_event("released")
            return True
        if is_down:
            # External remappers can supply either or both parts of a hotkey.
            pressed = self._pressed_modifier_vks[False] | self._pressed_modifier_vks[True]
            groups = {name for name, keys in MODIFIER_GROUPS.items() if pressed & keys}
            if groups == self.required_modifier_groups and self.should_suppress():
                self._suppressed_target_source = injected
                self.on_event("pressed")
                return True
        return False


class Win32SuppressedHotkeyHook:
    """Own and run a WH_KEYBOARD_LL hook on a dedicated message-loop thread."""

    def __init__(
        self, hotkey: str, *, should_suppress, on_event,
        allow_unmodified: bool = False,
    ):
        modifier_groups, target_vk = _parse_hotkey(
            hotkey, allow_unmodified=allow_unmodified,
        )
        self._processor = HotkeyEventProcessor(
            modifier_groups, target_vk, should_suppress, on_event,
        )
        self._thread = None
        self._thread_id = 0
        self._hook = None
        self._callback = None
        self._startup = queue.Queue(maxsize=1)
        self._stop_requested = threading.Event()
        self._thread_lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and self._hook)

    def start(self, timeout: float = 3.0) -> None:
        with self._thread_lock:
            if self._thread and self._thread.is_alive():
                if self._stop_requested.is_set():
                    raise RuntimeError("Previous Win32 hotkey hook is still stopping")
                return
            self._stop_requested.clear()
            self._processor.reset()
            startup = self._startup = queue.Queue(maxsize=1)
            thread = self._thread = threading.Thread(
                target=self._run, name="PoENaviWin32Hotkey", daemon=True,
            )
            thread.start()
        try:
            result = startup.get(timeout=timeout)
        except queue.Empty:
            self._request_stop(thread)
            raise
        if isinstance(result, BaseException):
            raise result

    def _request_stop(self, thread) -> None:
        with self._thread_lock:
            if self._thread is not thread:
                return
            self._stop_requested.set()
            if self._thread_id:
                ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def stop(self, timeout: float = 3.0) -> None:
        thread = self._thread
        if not thread:
            return
        self._request_stop(thread)
        if thread is threading.current_thread():
            return
        thread.join(timeout)
        if thread.is_alive():
            return
        with self._thread_lock:
            if self._thread is thread:
                self._thread = None
                self._hook = None
                self._callback = None

    def _run(self) -> None:
        started = False
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            user32.SetWindowsHookExW.restype = ctypes.c_void_p
            user32.SetWindowsHookExW.argtypes = [
                ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
            ]
            user32.CallNextHookEx.restype = ctypes.c_ssize_t
            user32.CallNextHookEx.argtypes = [
                ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM,
            ]
            user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
            kernel32.GetModuleHandleW.restype = ctypes.c_void_p
            kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

            class KBDLLHOOKSTRUCT(ctypes.Structure):
                _fields_ = [
                    ("vkCode", wintypes.DWORD),
                    ("scanCode", wintypes.DWORD),
                    ("flags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_void_p),
                ]

            callback_type = ctypes.WINFUNCTYPE(
                ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM,
            )

            def hook_proc(code, message, data_ptr):
                if code == HC_ACTION and not self._stop_requested.is_set():
                    data = ctypes.cast(
                        data_ptr, ctypes.POINTER(KBDLLHOOKSTRUCT),
                    ).contents
                    is_down = message in (WM_KEYDOWN, WM_SYSKEYDOWN)
                    is_up = message in (WM_KEYUP, WM_SYSKEYUP)
                    if (is_down or is_up) and self._processor.process(
                        int(data.vkCode), is_down,
                        injected=bool(data.flags & LLKHF_INJECTED),
                    ):
                        return 1
                return user32.CallNextHookEx(self._hook, code, message, data_ptr)

            message = wintypes.MSG()
            # Create the queue before publishing an ID that stop() can post to.
            user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
            with self._thread_lock:
                self._thread_id = int(kernel32.GetCurrentThreadId())
            if self._stop_requested.is_set():
                raise RuntimeError("Win32 hotkey hook startup was cancelled")
            self._callback = callback_type(hook_proc)
            self._hook = user32.SetWindowsHookExW(
                WH_KEYBOARD_LL, self._callback, kernel32.GetModuleHandleW(None), 0,
            )
            if not self._hook:
                raise ctypes.WinError()
            started = True
            self._startup.put(True)
            while not self._stop_requested.is_set():
                if user32.GetMessageW(ctypes.byref(message), None, 0, 0) <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        except BaseException as exc:
            if not started:
                self._startup.put(exc)
        finally:
            try:
                if self._hook:
                    user32.UnhookWindowsHookEx(self._hook)
            finally:
                self._hook = None
                with self._thread_lock:
                    self._thread_id = 0
