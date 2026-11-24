from src.utils import log_watcher


def test_poll_waits_for_complete_utf8_line(tmp_path):
    path = tmp_path / "Client.txt"
    initial = b": You have entered The Coast.\r\n"
    pending = "[SCENE] Set Source [海岸]\r\n".encode()
    split = pending.index("海".encode()) + 1
    path.write_bytes(initial + pending[:split])
    watcher = log_watcher.LogWatcher(str(path))
    zones = []
    watcher.zone_entered.connect(zones.append)

    watcher._poll()
    watcher._poll()
    assert zones == ["The Coast"]
    assert watcher._file_pos == len(initial)

    with path.open("ab") as log:
        log.write(pending[split:-1])
    watcher._poll()
    assert zones == ["The Coast"]
    with path.open("ab") as log:
        log.write(pending[-1:])
    watcher._poll()
    assert zones == ["The Coast", "海岸"]


def test_poll_bounds_reads_after_truncation_and_skips_oversized_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(log_watcher, "MAX_POLL_BYTES", 16)
    path = tmp_path / "Client.txt"
    path.write_bytes(b"old\n" * 25)
    watcher = log_watcher.LogWatcher(str(path))
    watcher._file_pos = path.stat().st_size
    lines = []
    monkeypatch.setattr(watcher, "_parse_line", lines.append)
    path.write_bytes(b"one\ntwo\n" + b"x" * 20 + b"\nthree\nfour\n")

    watcher._poll()
    assert lines == ["one", "two"]
    assert watcher._file_pos == 8
    watcher._poll()
    assert lines == ["one", "two"]
    assert watcher._file_pos == 24
    watcher._poll()
    assert lines == ["one", "two", "three", "four"]
