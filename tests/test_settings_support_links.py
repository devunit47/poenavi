import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from src.ui import app_info_widget
from src.ui.settings_dialog import SettingsDialog
from src.version import APP_VERSION


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_patreon_support_button_opens_configured_url(monkeypatch, qapp):
    opened_urls = []
    monkeypatch.setattr(app_info_widget.webbrowser, "open", opened_urls.append)
    dialog = SettingsDialog(current_config={})

    buttons = {
        button.text(): button
        for button in dialog.findChildren(QPushButton)
    }
    assert "OFUSE（おふせ）で応援する" in buttons
    assert "Ko-fi で応援する" in buttons
    assert "Patreon で応援する" in buttons

    buttons["Patreon で応援する"].click()

    assert opened_urls == ["https://www.patreon.com/cw/Buri8857"]
    dialog.close()


def test_app_information_update_button_uses_injected_callback(qapp):
    calls = []
    dialog = SettingsDialog(
        current_config={},
        update_check_callback=lambda: calls.append("checked"),
    )

    button = dialog.findChild(QPushButton, "appInfoUpdateButton")
    assert button is not None
    assert button.text() == "アップデートを確認"
    assert button.isEnabled()

    button.click()

    assert calls == ["checked"]
    dialog.close()


def test_app_information_displays_disclaimer_and_ndlocr_attribution(qapp):
    dialog = SettingsDialog(current_config={})

    assert dialog.findChild(QLabel, "appInfoVersion").text() == f"ぽえなび v{APP_VERSION} (Fork)"
    assert any("buri34/poenavi" in label.text() for label in dialog.findChildren(QLabel))

    disclaimer = dialog.findChild(QLabel, "appDisclaimerLabel")
    assert disclaimer is not None
    assert "ぽえなびは無料の非公式ツール" in disclaimer.text()
    assert "提携・承認関係はありません" in disclaimer.text()
    assert all("ぽえとれについて" not in label.text() for label in dialog.findChildren(QLabel))

    label = dialog.findChild(QLabel, "ndlocrLicenseLabel")
    assert label is not None
    assert "NDLOCR-Lite 1.3.1" in label.text()
    assert "国立国会図書館" in label.text()
    assert "CC BY 4.0" in label.text()
    assert "公認・提携製品ではありません" in label.text()
    dialog.close()
