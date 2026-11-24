import ctypes
import ctypes.wintypes as wt
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.utils import tcp_disconnect


@pytest.fixture
def admin_windows(monkeypatch):
    monkeypatch.setattr(tcp_disconnect.sys, "platform", "win32")
    monkeypatch.setattr(
        ctypes,
        "windll",
        SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: True)),
        raising=False,
    )


def test_explicit_pid_takes_precedence_and_retries_table_growth(admin_windows, monkeypatch):
    find = Mock()
    monkeypatch.setattr(tcp_disconnect, "find_poe_process", find)
    # IPv4 TCP rows for two different processes.
    table = (wt.DWORD * 13)(2, 5, 10, 11, 12, 13, 101, 5, 20, 21, 22, 23, 202)

    def get_table(buffer, size, *_args):
        if buffer is None:
            size._obj.value = ctypes.sizeof(wt.DWORD)
            return 122
        if len(buffer) < ctypes.sizeof(table):
            size._obj.value = ctypes.sizeof(table)
            return 122
        ctypes.memmove(buffer, table, ctypes.sizeof(table))
        return 0

    deleted = []

    def set_entry(row):
        deleted.append((row._obj.dwState, row._obj.dwLocalAddr))
        return 0

    api = SimpleNamespace(
        GetExtendedTcpTable=Mock(side_effect=get_table),
        SetTcpEntry=Mock(side_effect=set_entry),
    )
    dll = Mock(return_value=api)
    monkeypatch.setattr(ctypes, "WinDLL", dll, raising=False)

    assert tcp_disconnect.disconnect_poe("unused", target_pid=202)[0]
    assert deleted == [(12, 20)]
    assert api.GetExtendedTcpTable.call_count == 3
    dll.assert_called_once_with("iphlpapi")
    find.assert_not_called()


@pytest.mark.parametrize("executable", [
    None,
    r"C:\PoE1\PathOfExile.exe",
    r"C:\PoE2\PathOfExile2Steam.exe",
])
def test_log_path_never_falls_back_to_different_installation(
    executable, admin_windows, monkeypatch
):
    log = r"C:\PoE2\logs\Client.txt"
    process = (
        SimpleNamespace(pid=123, executable_path=executable, close=Mock())
        if executable else None
    )
    find = Mock(return_value=process)
    disconnect = Mock(return_value=(True, "ok"))
    monkeypatch.setattr(tcp_disconnect, "find_poe_process", find)
    monkeypatch.setattr(tcp_disconnect, "_disconnect_connections", disconnect)

    success, _ = tcp_disconnect.disconnect_poe(log)

    find.assert_called_once_with(log)
    if process is not None:
        process.close.assert_called_once_with()
    if executable and "PoE2" in executable:
        assert success
        disconnect.assert_called_once_with({123})
    else:
        assert not success
        disconnect.assert_not_called()


def test_default_selection_includes_poe2(admin_windows, monkeypatch):
    def set_entry(entry, name, pid):
        entry._obj.szExeFile = name
        entry._obj.th32ProcessID = pid
        return True

    remaining = iter([("other.exe", 99)])

    def next_entry(_, entry):
        item = next(remaining, None)
        return item is not None and set_entry(entry, *item)

    kernel = SimpleNamespace(
        CreateToolhelp32Snapshot=Mock(return_value=1),
        Process32FirstW=Mock(side_effect=lambda _, entry: set_entry(entry, "PathOfExile2.exe", 22)),
        Process32NextW=Mock(side_effect=next_entry),
        CloseHandle=Mock(),
    )
    dll = Mock(return_value=kernel)
    disconnect = Mock(return_value=(True, "ok"))
    monkeypatch.setattr(ctypes, "WinDLL", dll, raising=False)
    monkeypatch.setattr(tcp_disconnect, "_disconnect_connections", disconnect)

    assert tcp_disconnect.disconnect_poe()[0]
    disconnect.assert_called_once_with({22})
    dll.assert_called_once_with("kernel32")
    kernel.CloseHandle.assert_called_once_with(1)
