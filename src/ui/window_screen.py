"""Track screen and display metric changes for a top-level widget."""

from PySide6.QtCore import QObject, Signal


SCREEN_CHANGE_DEBOUNCE_MS = 150


class WindowScreenWatcher(QObject):
    changed = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.screen = None
        self._handle = None
        self._handle_connection = None
        self._screen_connections = ()

    def update(self) -> bool:
        window = self.parent()
        handle = window.windowHandle()
        if handle is not self._handle:
            if self._handle_connection is not None:
                QObject.disconnect(self._handle_connection)
            self._handle = handle
            self._handle_connection = (
                handle.screenChanged.connect(self._screen_changed) if handle is not None else None
            )
        return self.bind_screen(handle.screen() if handle is not None else window.screen())

    def bind_screen(self, screen) -> bool:
        if screen is self.screen:
            return False
        # Connections can already have been removed by Qt after monitor removal.
        for connection in self._screen_connections:
            QObject.disconnect(connection)
        self.screen = screen
        self._screen_connections = () if screen is None else (
            screen.availableGeometryChanged.connect(self.changed),
            screen.logicalDotsPerInchChanged.connect(self.changed),
            screen.physicalDotsPerInchChanged.connect(self.changed),
        )
        return True

    def _screen_changed(self, screen):
        self.bind_screen(screen)
        self.changed.emit()
