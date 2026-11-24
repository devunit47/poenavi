"""PoEクライアントのTCP接続を強制切断してログアウトする（Windows専用）"""

import sys
from pathlib import PureWindowsPath

from src.utils.poe_process import find_poe_process
from src.utils.window_focus import is_path_of_exile_process_name


def disconnect_poe(
    log_path: str | None = None, *, target_pid: int | None = None
) -> tuple[bool, str]:
    """PoEのTCP接続を強制切断する。戻り値: (成功bool, メッセージstr)"""
    if sys.platform != "win32":
        return (False, "Windows専用機能です")

    import ctypes

    # --- 管理者権限チェック ---
    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        is_admin = False
    if not is_admin:
        return (False, "管理者権限が必要です。PoENaviを「管理者として実行」してください。")

    if target_pid is not None:
        return _disconnect_connections({target_pid})
    if log_path is not None:
        process = find_poe_process(log_path)
        if process is None:
            return (False, "指定されたログに対応するPoEプロセスが見つかりません")
        try:
            # find_poe_process は候補が1件なら別のインストール先も返し得る。
            if PureWindowsPath(process.executable_path).parent != PureWindowsPath(log_path).parent.parent:
                return (False, "指定されたログに対応するPoEプロセスが見つかりません")
            return _disconnect_connections({process.pid})
        finally:
            process.close()

    poe_pids = _find_poe_pids()
    if poe_pids is None:
        return (False, "プロセス一覧の取得に失敗しました")
    if not poe_pids:
        return (False, "PoEのプロセスが見つかりません")
    return _disconnect_connections(poe_pids)


def _find_poe_pids() -> set[int] | None:
    import ctypes
    import ctypes.wintypes as wt

    # --- 定数 ---
    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    # --- プロセス列挙用構造体 ---
    MAX_PATH = 260

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wt.DWORD),
            ("cntUsage", wt.DWORD),
            ("th32ProcessID", wt.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wt.DWORD),
            ("cntThreads", wt.DWORD),
            ("th32ParentProcessID", wt.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wt.DWORD),
            ("szExeFile", ctypes.c_wchar * MAX_PATH),
        ]

    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    kernel32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wt.BOOL
    kernel32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wt.BOOL
    kernel32.CloseHandle.argtypes = [wt.HANDLE]
    kernel32.CloseHandle.restype = wt.BOOL

    poe_pids = set()

    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        return None

    try:
        pe = PROCESSENTRY32W()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if kernel32.Process32FirstW(snap, ctypes.byref(pe)):
            while True:
                if is_path_of_exile_process_name(pe.szExeFile):
                    poe_pids.add(pe.th32ProcessID)
                if not kernel32.Process32NextW(snap, ctypes.byref(pe)):
                    break
    finally:
        kernel32.CloseHandle(snap)

    return poe_pids


def _disconnect_connections(poe_pids: set[int]) -> tuple[bool, str]:
    import ctypes
    import ctypes.wintypes as wt

    TCP_TABLE_OWNER_PID_ALL = 5
    AF_INET = 2
    MIB_TCP_STATE_DELETE_TCB = 12
    NO_ERROR = 0
    ERROR_INSUFFICIENT_BUFFER = 122

    # --- TCP接続テーブル用構造体 ---
    class MIB_TCPROW_OWNER_PID(ctypes.Structure):
        _fields_ = [
            ("dwState", wt.DWORD),
            ("dwLocalAddr", wt.DWORD),
            ("dwLocalPort", wt.DWORD),
            ("dwRemoteAddr", wt.DWORD),
            ("dwRemotePort", wt.DWORD),
            ("dwOwningPid", wt.DWORD),
        ]

    class MIB_TCPTABLE_OWNER_PID(ctypes.Structure):
        _fields_ = [
            ("dwNumEntries", wt.DWORD),
            ("table", MIB_TCPROW_OWNER_PID * 1),
        ]

    # SetTcpEntry に渡す構造体（dwOwningPid なし）
    class MIB_TCPROW(ctypes.Structure):
        _fields_ = [
            ("dwState", wt.DWORD),
            ("dwLocalAddr", wt.DWORD),
            ("dwLocalPort", wt.DWORD),
            ("dwRemoteAddr", wt.DWORD),
            ("dwRemotePort", wt.DWORD),
        ]

    iphlpapi = ctypes.WinDLL("iphlpapi")
    iphlpapi.GetExtendedTcpTable.argtypes = [
        wt.LPVOID, ctypes.POINTER(wt.DWORD), wt.BOOL, wt.ULONG, ctypes.c_int, wt.ULONG
    ]
    iphlpapi.GetExtendedTcpTable.restype = wt.DWORD
    iphlpapi.SetTcpEntry.argtypes = [ctypes.POINTER(MIB_TCPROW)]
    iphlpapi.SetTcpEntry.restype = wt.DWORD

    # --- TCP接続テーブル取得 ---
    buf_size = wt.DWORD(0)
    buf = None
    ret = iphlpapi.GetExtendedTcpTable(
        buf, ctypes.byref(buf_size), False, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0
    )
    for _ in range(5):
        if ret != ERROR_INSUFFICIENT_BUFFER:
            break
        buf = ctypes.create_string_buffer(buf_size.value)
        ret = iphlpapi.GetExtendedTcpTable(
            buf, ctypes.byref(buf_size), False, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0
        )
    if ret != NO_ERROR:
        return (False, f"TCP接続テーブルの取得に失敗しました (error={ret})")
    if buf is None:
        return (False, "PoEのTCP接続が見つかりませんでした")

    table = ctypes.cast(buf, ctypes.POINTER(MIB_TCPTABLE_OWNER_PID)).contents
    num_entries = table.dwNumEntries

    # テーブルの全エントリにアクセスするため、正しいサイズで再キャスト
    class MIB_TCPTABLE_OWNER_PID_FULL(ctypes.Structure):
        _fields_ = [
            ("dwNumEntries", wt.DWORD),
            ("table", MIB_TCPROW_OWNER_PID * num_entries),
        ]

    full_table = ctypes.cast(buf, ctypes.POINTER(MIB_TCPTABLE_OWNER_PID_FULL)).contents

    # --- PoEの接続を切断 ---
    disconnected = 0
    errors = 0
    for i in range(num_entries):
        row = full_table.table[i]
        if row.dwOwningPid in poe_pids:
            tcp_row = MIB_TCPROW()
            tcp_row.dwState = MIB_TCP_STATE_DELETE_TCB
            tcp_row.dwLocalAddr = row.dwLocalAddr
            tcp_row.dwLocalPort = row.dwLocalPort
            tcp_row.dwRemoteAddr = row.dwRemoteAddr
            tcp_row.dwRemotePort = row.dwRemotePort
            ret = iphlpapi.SetTcpEntry(ctypes.byref(tcp_row))
            if ret == NO_ERROR:
                disconnected += 1
            else:
                errors += 1

    if disconnected > 0:
        msg = f"{disconnected}本のTCP接続を切断しました"
        if errors > 0:
            msg += f"（{errors}本は失敗）"
        return (True, msg)
    elif errors > 0:
        return (False, f"TCP接続の切断に失敗しました（{errors}本）")
    else:
        return (False, "PoEのTCP接続が見つかりませんでした")
