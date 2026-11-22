"""Windows Raw Input によるバックグラウンドの縦ホイール監視。"""

import ctypes
import sys
import threading
from ctypes import wintypes


_WM_CLOSE = 0x0010
_WM_INPUT = 0x00FF
_HWND_MESSAGE = ctypes.c_void_p(-3)
_RID_INPUT = 0x10000003
_RIM_TYPEMOUSE = 0
_RI_MOUSE_WHEEL = 0x0400
_RIDEV_INPUTSINK = 0x00000100
_RIDEV_REMOVE = 0x00000001

_HANDLE = ctypes.c_void_p
_WPARAM = ctypes.c_size_t
_LPARAM = ctypes.c_ssize_t
_LRESULT = ctypes.c_ssize_t


class _RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", _HANDLE),
        ("wParam", _WPARAM),
    ]


class _RAWMOUSE(ctypes.Structure):
    # ulButtons 共用体の 4 バイト境界に合わせる。
    _fields_ = [
        ("usFlags", wintypes.USHORT),
        ("_padding", wintypes.USHORT),
        ("usButtonFlags", wintypes.USHORT),
        ("usButtonData", wintypes.USHORT),
        ("ulRawButtons", wintypes.ULONG),
        ("lLastX", wintypes.LONG),
        ("lLastY", wintypes.LONG),
        ("ulExtraInformation", wintypes.ULONG),
    ]


class _RAWINPUT(ctypes.Structure):
    # マウスのみ登録するため、データ共用体は RAWMOUSE で表現する。
    _fields_ = [("header", _RAWINPUTHEADER), ("mouse", _RAWMOUSE)]


class _RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", _HANDLE),
    ]


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", _HANDLE),
        ("hIcon", _HANDLE),
        ("hCursor", _HANDLE),
        ("hbrBackground", _HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", _HANDLE),
    ]


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", _HANDLE),
        ("message", wintypes.UINT),
        ("wParam", _WPARAM),
        ("lParam", _LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
        ("lPrivate", wintypes.DWORD),
    ]


def _bind_user32():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    pointer = ctypes.POINTER
    uint = wintypes.UINT
    dword = wintypes.DWORD
    string = wintypes.LPCWSTR
    integer = ctypes.c_int
    boolean = wintypes.BOOL
    signatures = (
        ("RegisterClassExW", [pointer(_WNDCLASSEXW)], wintypes.ATOM),
        ("UnregisterClassW", [string, _HANDLE], boolean),
        ("CreateWindowExW", [
            dword, string, string, dword, integer, integer, integer, integer,
            _HANDLE, _HANDLE, _HANDLE, ctypes.c_void_p,
        ], _HANDLE),
        ("DefWindowProcW", [_HANDLE, uint, _WPARAM, _LPARAM], _LRESULT),
        ("DestroyWindow", [_HANDLE], boolean),
        ("PostMessageW", [_HANDLE, uint, _WPARAM, _LPARAM], boolean),
        ("PostQuitMessage", [integer], None),
        ("GetMessageW", [pointer(_MSG), _HANDLE, uint, uint], boolean),
        ("DispatchMessageW", [pointer(_MSG)], _LRESULT),
        ("RegisterRawInputDevices", [pointer(_RAWINPUTDEVICE), uint, uint], boolean),
        ("GetRawInputData", [_HANDLE, uint, ctypes.c_void_p, pointer(uint), uint], uint),
        ("GetCursorPos", [pointer(wintypes.POINT)], boolean),
    )
    for name, argtypes, restype in signatures:
        function = getattr(user32, name)
        function.argtypes = argtypes
        function.restype = restype
    return user32


def _wheel_direction(device_type: int, flags: int, button_data: int) -> int:
    if device_type != _RIM_TYPEMOUSE or not flags & _RI_MOUSE_WHEEL:
        return 0
    delta = ctypes.c_short(button_data).value
    if delta == 0:
        return 0
    return 1 if delta > 0 else -1


class _Win32RawInputWheelListener:
    _TIMEOUT = 1.0

    def __init__(self, on_scroll):
        if sys.platform != "win32":
            raise OSError("Raw Input requires Windows")
        self._on_scroll = on_scroll
        self._user32 = _bind_user32()
        self._ready = threading.Event()
        self._stop_requested = threading.Event()
        self._window_lock = threading.Lock()
        self._startup_error = None
        self._thread = None
        self._hwnd = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            if self._stop_requested.is_set():
                raise RuntimeError("Previous Raw Input listener is still stopping")
            return
        self._ready.clear()
        self._stop_requested.clear()
        self._startup_error = None
        self._thread = threading.Thread(
            target=self._run, name="StashTabRawInput", daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=self._TIMEOUT):
            self._request_stop()
            raise TimeoutError("Raw Input listener startup timed out")
        if self._startup_error is not None:
            self._thread.join(timeout=self._TIMEOUT)
            raise self._startup_error

    def _request_stop(self):
        self._stop_requested.set()
        with self._window_lock:
            if self._hwnd and not self._user32.PostMessageW(self._hwnd, _WM_CLOSE, 0, 0):
                print(f"[STASH SCROLL] PostMessageW failed: {ctypes.WinError()}")

    def stop(self):
        self._request_stop()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=self._TIMEOUT)
            if thread.is_alive():
                print("[STASH SCROLL] Raw Input listener shutdown timed out")

    def _run(self):
        try:
            self._message_loop()
        except Exception as exc:
            if self._ready.is_set():
                print(f"[STASH SCROLL] Raw Input listener failed: {exc}")
            else:
                self._startup_error = exc
        finally:
            self._ready.set()

    def _message_loop(self):
        user32 = self._user32
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = _HANDLE
        instance = kernel32.GetModuleHandleW(None)
        if not instance:
            raise ctypes.WinError()

        packet = _RAWINPUT()
        packet_size = ctypes.sizeof(packet)
        header_size = ctypes.sizeof(_RAWINPUTHEADER)
        size = wintypes.UINT()
        cursor = wintypes.POINT()
        wndproc = ctypes.WINFUNCTYPE(_LRESULT, _HANDLE, wintypes.UINT, _WPARAM, _LPARAM)

        @wndproc
        def window_proc(hwnd, message, wparam, lparam):
            if message == _WM_CLOSE:
                user32.PostQuitMessage(0)
                return 0
            if message == _WM_INPUT:
                try:
                    size.value = packet_size
                    copied = user32.GetRawInputData(
                        lparam, _RID_INPUT, ctypes.byref(packet), ctypes.byref(size), header_size,
                    )
                    if copied == packet_size:
                        direction = _wheel_direction(
                            packet.header.dwType, packet.mouse.usButtonFlags, packet.mouse.usButtonData,
                        )
                        if (
                            direction
                            and not self._stop_requested.is_set()
                            and user32.GetCursorPos(ctypes.byref(cursor))
                        ):
                            self._on_scroll(cursor.x, cursor.y, 0, direction)
                except Exception as exc:
                    print(f"[STASH SCROLL] Raw Input event failed: {exc}")
                # フォアグラウンドの WM_INPUT は DefWindowProcW で後処理する。
                user32.DefWindowProcW(hwnd, message, wparam, lparam)
                return 0
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)

        name = f"PoENavi.RawInputWheel.{id(self):x}"
        window_class = _WNDCLASSEXW(
            cbSize=ctypes.sizeof(_WNDCLASSEXW),
            lpfnWndProc=ctypes.cast(window_proc, ctypes.c_void_p),
            hInstance=instance,
            lpszClassName=name,
        )
        if not user32.RegisterClassExW(ctypes.byref(window_class)):
            raise ctypes.WinError()

        hwnd = None
        registered = False
        device = _RAWINPUTDEVICE(0x01, 0x02, _RIDEV_INPUTSINK)
        device_size = ctypes.sizeof(device)
        try:
            hwnd = user32.CreateWindowExW(
                0, name, "", 0, 0, 0, 0, 0, _HWND_MESSAGE, None, instance, None,
            )
            if not hwnd:
                raise ctypes.WinError()
            with self._window_lock:
                self._hwnd = hwnd
            if self._stop_requested.is_set():
                return

            device.hwndTarget = hwnd
            if not user32.RegisterRawInputDevices(ctypes.byref(device), 1, device_size):
                raise ctypes.WinError()
            registered = True
            self._ready.set()

            message = _MSG()
            while not self._stop_requested.is_set():
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == -1:
                    raise ctypes.WinError()
                if result == 0:
                    break
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            with self._window_lock:
                self._hwnd = None
            if registered:
                device.dwFlags = _RIDEV_REMOVE
                device.hwndTarget = None
                if not user32.RegisterRawInputDevices(ctypes.byref(device), 1, device_size):
                    print(f"[STASH SCROLL] RIDEV_REMOVE failed: {ctypes.WinError()}")
            if hwnd and not user32.DestroyWindow(hwnd):
                print(f"[STASH SCROLL] DestroyWindow failed: {ctypes.WinError()}")
            if not user32.UnregisterClassW(name, instance):
                print(f"[STASH SCROLL] UnregisterClassW failed: {ctypes.WinError()}")
