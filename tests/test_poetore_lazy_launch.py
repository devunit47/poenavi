import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from src.ui.main_window import MainWindow
from src.utils.poe_version_data import POE2


class PoetoreLazyLaunchTest(unittest.TestCase):
    def test_main_window_module_does_not_import_poetore_ui_at_startup(self):
        result = subprocess.run(
            [
                sys.executable, "-c",
                "import sys; import src.ui.main_window; "
                "print('src.poetore.ui' in sys.modules)",
            ],
            check=True, capture_output=True, text=True,
        )
        self.assertEqual(result.stdout.strip(), "False")

    def test_prepare_and_open_delegate_to_lazy_entrypoints(self):
        for version in (None, POE2):
            with self.subTest(poe_version=version):
                window = MainWindow.__new__(MainWindow)
                window.config = {}
                if version is not None:
                    window.poe_version = version
                    window.config["poe_version"] = version

                with (
                    patch("src.poetore.ui.prepare_poetore_window") as prepare_window,
                    patch("src.poetore.ui.show_poetore_window") as show_window,
                ):
                    MainWindow._prepare_poetore_window(window)
                    MainWindow.open_poetore(window)
                prepare_window.assert_called_once_with(window)
                show_window.assert_called_once_with(window)

    def test_capture_poetore_item_starts_capture(self):
        for version in (None, POE2):
            with self.subTest(poe_version=version):
                window = MainWindow.__new__(MainWindow)
                window.config = {"hotkeys": {"poetore_capture": "ctrl+shift+p"}}
                if version is not None:
                    window.poe_version = version
                    window.config["poe_version"] = version

                poetore_window = Mock()
                trace = Mock()
                with (
                    patch("src.poetore.performance.start_search_trace", return_value=trace),
                    patch(
                        "src.poetore.ui.show_poetore_window", return_value=poetore_window,
                    ) as show_window,
                ):
                    MainWindow.capture_poetore_item(window)
                show_window.assert_called_once_with(window, activate=False)
                poetore_window.capture_from_poe.assert_called_once_with(
                    trace, capture_hotkey="ctrl+shift+p",
                )
                self.assertEqual(
                    [call.args[0] for call in trace.mark.call_args_list],
                    ["hotkey_dispatched", "poetore_window_ready"],
                )

    def test_capture_release_is_forwarded_to_prepared_poetore_window(self):
        window = MainWindow.__new__(MainWindow)
        window._poetore_window = Mock()

        MainWindow.handle_hotkey(window, "poetore_capture_released")

        window._poetore_window.capture_hotkey_released.assert_called_once_with()

    def test_auto_hide_capture_uses_passive_mode(self):
        window = MainWindow.__new__(MainWindow)
        poetore_window = Mock()
        trace = Mock()
        with patch(
            "src.poetore.performance.start_search_trace", return_value=trace,
        ), patch(
            "src.poetore.ui.show_poetore_window", return_value=poetore_window,
        ):
            MainWindow.capture_poetore_item(window, auto_hide=True)

        poetore_window.capture_from_poe.assert_called_once_with(
            trace, auto_hide=True, capture_hotkey="ctrl+d",
        )


if __name__ == "__main__":
    unittest.main()
