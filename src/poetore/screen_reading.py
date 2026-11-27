"""Shared lifecycle and mutual exclusion for local Windows screen OCR."""

from __future__ import annotations

import threading
from enum import StrEnum

from src.poetore.expedition_ocr_probe import WindowsOcrServer
from src.utils.state_machine import StateMachine


class ScreenReadingState(StrEnum):
    IDLE = "idle"
    BUSY = "busy"
    CLOSED = "closed"


SCREEN_READING_TRANSITIONS = {
    ScreenReadingState.IDLE: frozenset({ScreenReadingState.BUSY, ScreenReadingState.CLOSED}),
    ScreenReadingState.BUSY: frozenset({ScreenReadingState.IDLE, ScreenReadingState.CLOSED}),
    ScreenReadingState.CLOSED: frozenset(),
}


class ScreenReadingCoordinator:
    """Own one OCR helper and allow only one feature scan at a time."""

    def __init__(self, ocr_server=None):
        self.ocr = ocr_server or WindowsOcrServer()
        self._lock = threading.Lock()
        self._owner: str | None = None
        self._sm = StateMachine(
            "screen reading", ScreenReadingState.IDLE, SCREEN_READING_TRANSITIONS,
        )

    @property
    def state(self) -> ScreenReadingState:
        with self._lock:
            return self._sm.state

    @property
    def owner(self) -> str | None:
        with self._lock:
            return self._owner

    def try_begin(self, owner: str) -> bool:
        with self._lock:
            if not self._sm.is_in(ScreenReadingState.IDLE):
                return False
            self._owner = owner
            self._sm.transition(ScreenReadingState.BUSY)
            return True

    def finish(self, owner: str) -> None:
        with self._lock:
            if self._sm.is_in(ScreenReadingState.BUSY) and self._owner == owner:
                self._owner = None
                self._sm.transition(ScreenReadingState.IDLE)

    def start(self) -> None:
        self.ocr.start()

    def recognize(self, images):
        return self.ocr.recognize(images)

    def close(self) -> None:
        with self._lock:
            if self._sm.is_in(ScreenReadingState.CLOSED):
                return
            self._sm.transition(ScreenReadingState.CLOSED)
            self._owner = None
        self.ocr.close(permanent=True)
