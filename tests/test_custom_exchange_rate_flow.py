from concurrent.futures import Future
from copy import deepcopy
from unittest.mock import Mock

from PySide6.QtCore import Qt

from src.poetore.exchange_catalog import exchange_catalog_by_id
from src.poetore.exchange_icon_cache import IconResult
from src.poetore.exchange_rate_cache import ExchangeRateValueCache
from src.poetore.exchange_rate_settings import (
    CHAOS_ORB_ID,
    DIVINE_ORB_ID,
    EXALTED_ORB_ID,
    ExchangeRatePairStore,
    default_rate_pairs_config,
)
from src.poetore.official_exchange import DirectPairPrice, ExchangeSyncState
from src.ui import poetore_mode_window
from src.ui.exchange_rate_management_dialog import ExchangeRateManagementDialog
from src.utils.poe_version_data import POE1


class _IconCache:
    def __init__(self, path):
        self.path = path

    def request(self, _kind, _url=None, _filename=None):
        future = Future()
        future.set_result(IconResult(self.path, "placeholder", "svg"))
        return future

    def close(self, *, wait):
        pass


class _ExchangeService:
    def __init__(self, item_ids):
        self.item_ids = frozenset(item_ids)

    def direct_pair(self, _version, _league, left, right):
        return DirectPairPrice("no_trades", left, right, None, 720)

    def sync_state(self, version, league):
        return ExchangeSyncState(version, league, 720, 720, 0, False, True)

    def exchange_item_ids(self, _version, _league):
        return self.item_ids

    def queue_sync(self, *_args, **_kwargs):
        return False


def _select(dialog, item_id):
    for index in range(dialog.candidate_list.count()):
        row = dialog.candidate_list.item(index)
        if row.data(Qt.UserRole) == item_id:
            dialog.candidate_list.setCurrentRow(index)
            return
    raise AssertionError(item_id)


def test_manage_add_move_delete_and_restart_flow(qapp, tmp_path, monkeypatch):
    catalog = exchange_catalog_by_id(POE1)
    target = next(
        item_id for item_id in catalog
        if item_id not in {DIVINE_ORB_ID, CHAOS_ORB_ID, EXALTED_ORB_ID}
    )
    config = {"poe_version": POE1, "poetore": {"exchange_rate_pairs": default_rate_pairs_config()}}
    saved = []
    icon = tmp_path / "placeholder.svg"
    icon.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    icons = _IconCache(icon)
    service = _ExchangeService({target, DIVINE_ORB_ID, CHAOS_ORB_ID})
    monkeypatch.setattr(poetore_mode_window.ConfigManager, "load_config", lambda: config)
    monkeypatch.setattr(poetore_mode_window.ConfigManager, "save_config", lambda value: saved.append(deepcopy(value)))
    monkeypatch.setattr(poetore_mode_window, "ExchangeIconCache", lambda: icons)
    monkeypatch.setattr(poetore_mode_window, "ExchangeRateValueCache", lambda: ExchangeRateValueCache(tmp_path / "values.json"))
    monkeypatch.setattr("src.poetore.official_exchange.default_official_exchange_shadow_service", service)
    monkeypatch.setattr(poetore_mode_window.StashTabScrollController, "start", lambda self: None)
    monkeypatch.setattr(poetore_mode_window, "GlobalHotkeyService", Mock())
    monkeypatch.setattr(poetore_mode_window.PoetoreModeWindow, "refresh_currency_rate", lambda self, **kwargs: None)
    opened = []
    monkeypatch.setattr(ExchangeRateManagementDialog, "exec", lambda dialog: opened.append(dialog))
    window = poetore_mode_window.PoetoreModeWindow()
    panel = window.rate_panel
    store = window._rate_pair_store
    saved.clear()
    try:
        window.show()
        qapp.processEvents()
        assert not opened
        panel.manage_button.click()
        assert len(opened) == 1
        dialog = opened[0]
        assert dialog.parentWidget() is window
        _select(dialog, target)
        dialog.currency_buttons[DIVINE_ORB_ID].setChecked(True)
        dialog.add_button.click()
        assert len(panel.row_widgets) == 2
        assert len(saved) == 1

        dialog._move_up(1)
        assert store.pairs(POE1)[0].left_item_id == target
        assert len(saved) == 2
        dialog._delete(1)
        assert len(panel.row_widgets) == 1
        assert len(saved) == 3

        restarted = ExchangeRatePairStore(
            deepcopy(saved[-1]), lambda _value: None
        )
        assert restarted.pairs(POE1) == store.pairs(POE1)
        assert restarted.pairs(POE1)[0].left_item_id == target
    finally:
        window.close()
        qapp.processEvents()
