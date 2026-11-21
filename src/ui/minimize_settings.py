from PySide6.QtWidgets import QComboBox


def create_minimize_behavior_combo(config):
    combo = QComboBox()
    combo.addItem("タスクトレイに格納", "tray")
    combo.addItem("タスクバーに最小化", "taskbar")
    combo.setCurrentIndex(max(0, combo.findData(config.get("minimize_behavior", "tray"))))
    return combo
