"""State and log helpers for PoETore hideout-stay notifications."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from src.utils.state_machine import StateMachine

BUNDLED_SOUND_OPTIONS = (
    ("standard_1", "標準音1", "hideout_focus_notification.wav"),
    ("standard_2", "標準音2", "hideout_notification_2.wav"),
    ("standard_3", "標準音3", "hideout_notification_3.wav"),
    ("standard_4", "標準音4", "hideout_notification_4.wav"),
    ("standard_5", "標準音5", "hideout_notification_5.mp3"),
)
DEFAULT_BUNDLED_SOUND_ID = BUNDLED_SOUND_OPTIONS[0][0]
_BUNDLED_SOUND_IDS = frozenset(option[0] for option in BUNDLED_SOUND_OPTIONS)

DEFAULT_HIDEOUT_NOTIFICATION_SETTINGS = {
    "duration_seconds": 60,
    "repeat": False,
    "audio_source": "bundled",
    "bundled_sound_id": DEFAULT_BUNDLED_SOUND_ID,
    "custom_audio_display_name": "",
    "custom_audio_file": "",
    "volume": 50,
}

MIN_DURATION_SECONDS = 10
MAX_DURATION_SECONDS = 60 * 60
MAX_LOG_SCAN_BYTES = 128 * 1024 * 1024
BUTTON_LABEL = "隠れ家滞在通知"

_LOG_TIMESTAMP = re.compile(
    r"(?P<date>\d{4}/\d{2}/\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2})"
)
_ZONE_JA = re.compile(r"あなたは(.+?)に入場しました。")
_ZONE_EN = re.compile(r": You have entered (.+?)\.")
_SET_SOURCE = re.compile(r"\[SCENE\] Set Source \[(.+?)\]")
_CHAPTER_ONLY = re.compile(r"(?:アクト\d+|Act\s*\d+)", re.IGNORECASE)


def normalize_hideout_notification_settings(value) -> dict:
    """Return a complete, bounded settings dictionary."""
    source = value if isinstance(value, dict) else {}
    normalized = dict(DEFAULT_HIDEOUT_NOTIFICATION_SETTINGS)
    try:
        duration = int(source.get("duration_seconds", 60))
    except (TypeError, ValueError):
        duration = 60
    normalized["duration_seconds"] = max(
        MIN_DURATION_SECONDS, min(MAX_DURATION_SECONDS, duration)
    )
    normalized["repeat"] = bool(source.get("repeat", False))
    normalized["audio_source"] = (
        "custom" if source.get("audio_source") == "custom" else "bundled"
    )
    bundled_sound_id = str(source.get("bundled_sound_id", "") or "")
    normalized["bundled_sound_id"] = (
        bundled_sound_id
        if bundled_sound_id in _BUNDLED_SOUND_IDS
        else DEFAULT_BUNDLED_SOUND_ID
    )
    normalized["custom_audio_display_name"] = str(
        source.get("custom_audio_display_name", "") or ""
    )
    custom_file = Path(str(source.get("custom_audio_file", "") or "")).name
    normalized["custom_audio_file"] = custom_file
    try:
        volume = int(source.get("volume", 50))
    except (TypeError, ValueError):
        volume = 50
    normalized["volume"] = max(0, min(100, volume))
    if not custom_file:
        normalized["audio_source"] = "bundled"
    return normalized


def is_hideout_zone(zone_name: str | None) -> bool:
    value = str(zone_name or "")
    return "隠れ家" in value or "hideout" in value.casefold()


def zone_from_log_line(line: str) -> str | None:
    """Extract a usable zone from a Client.txt line."""
    for pattern in (_ZONE_JA, _ZONE_EN, _SET_SOURCE):
        match = pattern.search(line)
        if not match:
            continue
        zone = match.group(1).strip()
        if zone in {"(null)", "(unknown)", "幕間", "Interlude"}:
            return None
        if _CHAPTER_ONLY.fullmatch(zone):
            return None
        return zone
    return None


def timestamp_from_log_line(line: str) -> datetime | None:
    match = _LOG_TIMESTAMP.search(line)
    if not match:
        return None
    try:
        return datetime.strptime(
            f"{match.group('date')} {match.group('time')}", "%Y/%m/%d %H:%M:%S"
        )
    except ValueError:
        return None


def _reverse_log_lines(path: Path, max_bytes: int = MAX_LOG_SCAN_BYTES):
    """Yield UTF-8 log lines from newest to oldest without loading the file."""
    with path.open("rb") as handle:
        handle.seek(0, 2)
        end = handle.tell()
        lower_bound = max(0, end - max(0, int(max_bytes)))
        position = end
        prefix = b""
        while position > lower_bound:
            read_size = min(64 * 1024, position - lower_bound)
            position -= read_size
            handle.seek(position)
            data = handle.read(read_size) + prefix
            parts = data.split(b"\n")
            prefix = parts.pop(0)
            for raw_line in reversed(parts):
                yield raw_line.rstrip(b"\r").decode("utf-8", errors="ignore")
        if prefix:
            yield prefix.rstrip(b"\r").decode("utf-8", errors="ignore")


def latest_zone_since_process_start(
    log_path: str | Path,
    process_started_at: datetime,
    *,
    max_bytes: int = MAX_LOG_SCAN_BYTES,
) -> str | None:
    """Return the newest zone logged during the current PoE process."""
    path = Path(log_path)
    if not path.is_file() or not isinstance(process_started_at, datetime):
        return None
    # Client.txt timestamps have second precision. Compare at that precision so a
    # first line emitted within the process-start second is not discarded.
    threshold = process_started_at.replace(tzinfo=None, microsecond=0)
    try:
        for line in _reverse_log_lines(path, max_bytes=max_bytes):
            zone = zone_from_log_line(line)
            if zone is None:
                continue
            timestamp = timestamp_from_log_line(line)
            if timestamp is None:
                continue
            if timestamp < threshold:
                return None
            return zone
    except OSError:
        return None
    return None


class HideoutTimerPhase(StrEnum):
    DISABLED = "disabled"
    AWAITING_ZONE = "awaiting_zone"
    OUTSIDE_HIDEOUT = "outside_hideout"
    IN_HIDEOUT = "in_hideout"
    NOTIFIED = "notified"


HIDEOUT_TIMER_TRANSITIONS = {
    HideoutTimerPhase.DISABLED: frozenset({
        HideoutTimerPhase.AWAITING_ZONE, HideoutTimerPhase.OUTSIDE_HIDEOUT,
        HideoutTimerPhase.IN_HIDEOUT,
    }),
    HideoutTimerPhase.AWAITING_ZONE: frozenset({
        HideoutTimerPhase.DISABLED, HideoutTimerPhase.OUTSIDE_HIDEOUT,
        HideoutTimerPhase.IN_HIDEOUT,
    }),
    HideoutTimerPhase.OUTSIDE_HIDEOUT: frozenset({
        HideoutTimerPhase.DISABLED, HideoutTimerPhase.AWAITING_ZONE,
        HideoutTimerPhase.IN_HIDEOUT,
    }),
    HideoutTimerPhase.IN_HIDEOUT: frozenset({
        HideoutTimerPhase.DISABLED, HideoutTimerPhase.AWAITING_ZONE,
        HideoutTimerPhase.OUTSIDE_HIDEOUT, HideoutTimerPhase.NOTIFIED,
    }),
    HideoutTimerPhase.NOTIFIED: frozenset({
        HideoutTimerPhase.DISABLED, HideoutTimerPhase.AWAITING_ZONE,
        HideoutTimerPhase.OUTSIDE_HIDEOUT, HideoutTimerPhase.IN_HIDEOUT,
    }),
}


@dataclass(init=False)
class HideoutTimerState:
    # Keep the dataclass fields available for repr, equality, and replace().
    duration_seconds: int = 60
    repeat: bool = False
    active: bool
    zone_known: bool
    in_hideout: bool
    started_at: float | None = None
    notified: bool
    last_due_slot: int = 0

    def __init__(
        self,
        duration_seconds: int = 60,
        repeat: bool = False,
        active: bool = False,
        zone_known: bool = False,
        in_hideout: bool = False,
        started_at: float | None = None,
        notified: bool = False,
        last_due_slot: int = 0,
    ):
        self.duration_seconds = duration_seconds
        self.repeat = repeat
        if not active:
            phase = HideoutTimerPhase.DISABLED
        elif not zone_known:
            phase = HideoutTimerPhase.AWAITING_ZONE
        elif not in_hideout:
            phase = HideoutTimerPhase.OUTSIDE_HIDEOUT
        else:
            if started_at is None:
                raise ValueError("A hideout timer requires a start time")
            phase = (
                HideoutTimerPhase.NOTIFIED
                if notified and not repeat else HideoutTimerPhase.IN_HIDEOUT
            )
        self._sm = StateMachine("hideout timer", phase, HIDEOUT_TIMER_TRANSITIONS)
        self.started_at = started_at if self.in_hideout else None
        self.last_due_slot = last_due_slot if self.in_hideout else 0

    @property
    def phase(self) -> HideoutTimerPhase:
        return self._sm.state

    @property
    def active(self) -> bool:
        return self.phase is not HideoutTimerPhase.DISABLED

    @property
    def zone_known(self) -> bool:
        return self._sm.is_in(
            HideoutTimerPhase.OUTSIDE_HIDEOUT, HideoutTimerPhase.IN_HIDEOUT,
            HideoutTimerPhase.NOTIFIED,
        )

    @property
    def in_hideout(self) -> bool:
        return self._sm.is_in(HideoutTimerPhase.IN_HIDEOUT, HideoutTimerPhase.NOTIFIED)

    @property
    def notified(self) -> bool:
        return self.phase is HideoutTimerPhase.NOTIFIED

    def _reset_timer(self, phase: HideoutTimerPhase, started_at: float | None = None) -> None:
        if phase is HideoutTimerPhase.IN_HIDEOUT and started_at is None:
            raise ValueError("A hideout timer requires a start time")
        self.started_at = started_at
        self.last_due_slot = 0
        self._sm.transition(phase, allow_same=True)

    def enable(self, current_zone: str | None, now: float) -> None:
        if current_zone is None:
            self._reset_timer(HideoutTimerPhase.AWAITING_ZONE)
        elif is_hideout_zone(current_zone):
            self._reset_timer(HideoutTimerPhase.IN_HIDEOUT, now)
        else:
            self._reset_timer(HideoutTimerPhase.OUTSIDE_HIDEOUT)

    def disable(self) -> None:
        self._reset_timer(HideoutTimerPhase.DISABLED)

    def reset_to_unknown(self) -> None:
        phase = HideoutTimerPhase.AWAITING_ZONE if self.active else HideoutTimerPhase.DISABLED
        self._reset_timer(phase)

    def enter_zone(self, zone_name: str, now: float) -> None:
        if not self.active:
            return
        if not is_hideout_zone(zone_name):
            self._reset_timer(HideoutTimerPhase.OUTSIDE_HIDEOUT)
        elif not self.in_hideout or self.started_at is None:
            self._reset_timer(HideoutTimerPhase.IN_HIDEOUT, now)

    def elapsed_seconds(self, now: float) -> int:
        if not self.in_hideout or self.started_at is None:
            return 0
        return max(0, int(now - self.started_at))

    def consume_due_notification(self, now: float) -> int | None:
        if self.phase is not HideoutTimerPhase.IN_HIDEOUT or self.started_at is None:
            return None
        slot = self.elapsed_seconds(now) // max(1, int(self.duration_seconds))
        if slot < 1:
            return None
        if self.repeat:
            if slot <= self.last_due_slot:
                return None
            self.last_due_slot = slot
            return slot
        self.last_due_slot = slot
        self._sm.transition(HideoutTimerPhase.NOTIFIED)
        return slot

    def set_duration(self, duration_seconds: int, now: float) -> None:
        self.duration_seconds = max(
            MIN_DURATION_SECONDS,
            min(MAX_DURATION_SECONDS, int(duration_seconds)),
        )
        if self.in_hideout:
            self._reset_timer(HideoutTimerPhase.IN_HIDEOUT, now)
        else:
            self.last_due_slot = 0

    def set_repeat(self, repeat: bool) -> None:
        self.repeat = bool(repeat)
        if self.repeat and self.notified:
            self._sm.transition(HideoutTimerPhase.IN_HIDEOUT)
        elif (
            not self.repeat and self.phase is HideoutTimerPhase.IN_HIDEOUT
            and self.last_due_slot > 0
        ):
            self._sm.transition(HideoutTimerPhase.NOTIFIED)

    def button_text(self, now: float) -> str:
        if not self.active:
            return f"{BUTTON_LABEL}\nOFF"
        if not self.zone_known:
            return f"{BUTTON_LABEL}\nON（エリア待ち）"
        if not self.in_hideout:
            return f"{BUTTON_LABEL}\nON"
        elapsed = self.elapsed_seconds(now)
        minutes, seconds = divmod(elapsed, 60)
        suffix = " ✓" if self.notified and not self.repeat else ""
        return f"{BUTTON_LABEL}\n{minutes}:{seconds:02d}{suffix}"
