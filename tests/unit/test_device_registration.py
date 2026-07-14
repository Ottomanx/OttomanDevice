from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from device import resolve_device_id


@pytest.fixture()
def device_id_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "device_id"
    monkeypatch.setattr("device.DEVICE_ID_PATH", path)
    return path


def test_resolve_device_id_reuses_local_file(device_id_path: Path) -> None:
    device_id_path.parent.mkdir(parents=True, exist_ok=True)
    device_id_path.write_text("local-device-id", encoding="utf-8")
    supabase = MagicMock()

    resolved = resolve_device_id(supabase, "Workstation", device_id_path)

    assert resolved == "local-device-id"
    supabase.table.assert_not_called()


def test_resolve_device_id_reuses_existing_registration(device_id_path: Path) -> None:
    supabase = MagicMock()
    table = supabase.table.return_value
    table.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[{"device_id": "existing-device-id"}]
    )

    resolved = resolve_device_id(supabase, "Workstation", device_id_path)

    assert resolved == "existing-device-id"
    assert device_id_path.read_text(encoding="utf-8") == "existing-device-id"
    table.select.assert_called_once_with("device_id")
    table.select.return_value.eq.assert_called_once_with("computer_name", "Workstation")


def test_resolve_device_id_creates_new_id_when_no_match(device_id_path: Path) -> None:
    supabase = MagicMock()
    table = supabase.table.return_value
    table.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[]
    )

    resolved = resolve_device_id(supabase, "Workstation", device_id_path)

    assert resolved
    assert device_id_path.read_text(encoding="utf-8") == resolved
