from unittest.mock import Mock

import pytest

from src.poetore.expedition_ocr_probe import WindowsOcrServer
from src.poetore.poe2.ndlocr_lite import NdlOcrLiteServer
from src.poetore.screen_reading import ScreenReadingCoordinator


def test_screen_reading_coordinator_serializes_features_and_releases_owner():
    ocr = Mock()
    coordinator = ScreenReadingCoordinator(ocr)

    assert coordinator.try_begin("expedition")
    assert not coordinator.try_begin("desecration")
    coordinator.finish("desecration")
    assert coordinator.owner == "expedition"
    coordinator.finish("expedition")
    assert coordinator.try_begin("desecration")


def test_screen_reading_coordinator_delegates_and_closes():
    ocr = Mock()
    ocr.recognize.return_value = ["ok"]
    coordinator = ScreenReadingCoordinator(ocr)

    coordinator.start()
    assert coordinator.recognize([b"image"]) == ["ok"]
    coordinator.try_begin("expedition")
    coordinator.close()

    ocr.start.assert_called_once_with()
    ocr.recognize.assert_called_once_with([b"image"])
    ocr.close.assert_called_once_with(permanent=True)
    assert coordinator.owner is None
    assert not coordinator.try_begin("desecration")


@pytest.mark.parametrize("make_server", [WindowsOcrServer, NdlOcrLiteServer])
def test_retired_ocr_server_rejects_late_worker_request(make_server):
    server = make_server()
    server.close(permanent=True)
    with pytest.raises(RuntimeError, match="終了済み"):
        server.recognize([b"image"])
