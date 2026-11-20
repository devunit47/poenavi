"""Global pytest isolation for files that PoENavi normally writes per user."""

import os
import tempfile

import pytest

_TEST_USER_DATA_DIR = tempfile.mkdtemp(prefix="poenavi-pytest-user-data-")
os.environ.setdefault("POENAVI_USER_DATA_DIR", _TEST_USER_DATA_DIR)
# 実運用用daemon writerをpytest終了時のQt teardownへ残さない。
os.environ.setdefault("POETORE_DISABLE_PERFORMANCE_LOG", "1")
# テスト中のQtウィンドウを実画面に表示しない。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def isolated_bundled_font(qapp, monkeypatch):
    from PySide6.QtGui import QFontDatabase

    font = qapp.font()
    family = qapp.property("bundledUiFontFamily")
    font_ids = []
    add_font = QFontDatabase.addApplicationFont

    def register_font(path):
        font_id = add_font(path)
        if font_id != -1:
            font_ids.append(font_id)
        return font_id

    monkeypatch.setattr(QFontDatabase, "addApplicationFont", register_font)
    yield
    qapp.setFont(font)
    qapp.setProperty("bundledUiFontFamily", family)
    for font_id in font_ids:
        QFontDatabase.removeApplicationFont(font_id)
