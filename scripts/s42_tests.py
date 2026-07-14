from __future__ import annotations

import json
import platform
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ottomandevice.core.event_bus import EventBus
from ottomandevice.core.exceptions import DeviceIdentityError
from ottomandevice.device.certificate import DeviceCertificate
from ottomandevice.device.identity import DeviceIdentity, get_device_uuid
from ottomandevice.device.profile import DeviceProfile
from ottomandevice.device.registry import DeviceRegistry


@pytest.fixture
def bus() -> EventBus:
    event_bus = EventBus(max_history=100)
    yield event_bus
    event_bus.shutdown()


def _write_plugin_package(root: Path, plugin_id: str) -> None:
    package_dir = root / plugin_id
    package_dir.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent(
        f"""
        from ottomandevice.plugins.base import BasePlugin, PluginMetadata

        class SamplePlugin(BasePlugin):
            PLUGIN_METADATA = PluginMetadata(
                id="{plugin_id}",
                name="{plugin_id.title()}",
                version="1.0.0",
                author="test",
            )

            @property
            def metadata(self) -> PluginMetadata:
                return self.PLUGIN_METADATA

            def install(self) -> None:
                pass

            def initialize(self) -> None:
                pass

            def start(self) -> None:
                pass

            def stop(self) -> None:
                pass

            def uninstall(self) -> None:
                pass

        plugin_class = SamplePlugin
        """
    ).strip() + "\n"
    (package_dir / "__init__.py").write_text(content, encoding="utf-8")


def test_device_identity_creates_device_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / "device.json"
    cert_dir = tmp_path / "device"
    monkeypatch.setattr("ottomandevice.device.identity.DEVICE_JSON_PATH", store)
    monkeypatch.setattr("ottomandevice.device.identity.LEGACY_DEVICE_ID_PATH", tmp_path / "device_id")
    monkeypatch.setattr("ottomandevice.device.certificate.CERTIFICATE_DIR", cert_dir)
    monkeypatch.setattr("ottomandevice.device.certificate.PRIVATE_KEY_PATH", cert_dir / "private.key")
    monkeypatch.setattr("ottomandevice.device.certificate.PUBLIC_KEY_PATH", cert_dir / "public.key")
    monkeypatch.setattr("ottomandevice.device.certificate.METADATA_PATH", cert_dir / "certificate.json")

    identity = DeviceIdentity.load(store_path=store)

    assert store.exists()
    payload = json.loads(store.read_text(encoding="utf-8"))
    assert payload["device_uuid"]
    assert payload["installation_id"]
    assert payload["first_boot_timestamp"]
    assert payload["hostname"] == platform.node()
    assert identity.device_uuid == payload["device_uuid"]


def test_device_identity_reuses_existing_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / "device.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(
        json.dumps(
            {
                "device_uuid": "11111111-1111-1111-1111-111111111111",
                "installation_id": "22222222-2222-2222-2222-222222222222",
                "first_boot_timestamp": "2026-07-14T05:00:00+00:00",
                "hostname": "test-host",
            }
        ),
        encoding="utf-8",
    )

    identity = DeviceIdentity.load(store_path=store)

    assert identity.device_uuid == "11111111-1111-1111-1111-111111111111"
    assert identity.installation_id == "22222222-2222-2222-2222-222222222222"
    assert get_device_uuid(store_path=store) == identity.device_uuid


def test_device_identity_migrates_legacy_device_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / "device.json"
    legacy = tmp_path / "device_id"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("legacy-device-id", encoding="utf-8")
    monkeypatch.setattr("ottomandevice.device.identity.LEGACY_DEVICE_ID_PATH", legacy)

    identity = DeviceIdentity.load(store_path=store)

    assert identity.device_uuid == "legacy-device-id"
    assert store.exists()


def test_device_certificate_ensure_creates_material(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cert_dir = tmp_path / "device"
    monkeypatch.setattr("ottomandevice.device.certificate.CERTIFICATE_DIR", cert_dir)
    monkeypatch.setattr("ottomandevice.device.certificate.PRIVATE_KEY_PATH", cert_dir / "private.key")
    monkeypatch.setattr("ottomandevice.device.certificate.PUBLIC_KEY_PATH", cert_dir / "public.key")
    monkeypatch.setattr("ottomandevice.device.certificate.METADATA_PATH", cert_dir / "certificate.json")

    certificate = DeviceCertificate.ensure("device-uuid")

    assert certificate.fingerprint
    assert certificate.public_key
    assert (cert_dir / "private.key").exists()
    assert (cert_dir / "certificate.json").exists()

    reloaded = DeviceCertificate.ensure("device-uuid")
    assert reloaded.fingerprint == certificate.fingerprint


def test_device_profile_collects_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / "device.json"
    store.write_text(
        json.dumps(
            {
                "device_uuid": "profile-device",
                "installation_id": "install-id",
                "first_boot_timestamp": "2026-07-14T05:00:00+00:00",
                "hostname": "profile-host",
            }
        ),
        encoding="utf-8",
    )
    identity = DeviceIdentity.load(store_path=store)
    profile = DeviceProfile.collect(identity)

    assert profile.device_uuid == "profile-device"
    assert profile.hostname == "profile-host"
    assert profile.os
    assert profile.architecture
    assert profile.cpu
    assert profile.ram_mb > 0
    assert profile.application_version
    assert profile.runtime_version


def test_device_profile_includes_plugins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ottomandevice.core.plugin_manager import PluginManager

    store = tmp_path / "device.json"
    store.write_text(
        json.dumps(
            {
                "device_uuid": "plugin-device",
                "installation_id": "install-id",
                "first_boot_timestamp": "2026-07-14T05:00:00+00:00",
                "hostname": "plugin-host",
            }
        ),
        encoding="utf-8",
    )
    plugins_root = tmp_path / "plugins"
    _write_plugin_package(plugins_root, "alpha")

    identity = DeviceIdentity.load(store_path=store)
    manager = PluginManager(plugins_root=plugins_root, event_bus=EventBus(max_history=10))
    manager.discover()
    manager.load_all()

    profile = DeviceProfile.collect(identity, plugin_manager=manager)

    assert len(profile.plugins) == 1
    assert profile.plugins[0].id == "alpha"


def test_device_registry_registers_and_reuses(bus: EventBus, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / "device.json"
    cert_dir = tmp_path / "device"
    monkeypatch.setattr("ottomandevice.device.identity.DEVICE_JSON_PATH", store)
    monkeypatch.setattr("ottomandevice.device.certificate.CERTIFICATE_DIR", cert_dir)
    monkeypatch.setattr("ottomandevice.device.certificate.PRIVATE_KEY_PATH", cert_dir / "private.key")
    monkeypatch.setattr("ottomandevice.device.certificate.PUBLIC_KEY_PATH", cert_dir / "public.key")
    monkeypatch.setattr("ottomandevice.device.certificate.METADATA_PATH", cert_dir / "certificate.json")

    identity = DeviceIdentity.load(store_path=store)
    certificate = DeviceCertificate.ensure(identity.device_uuid)
    identity = identity.with_certificate_fingerprint(certificate.fingerprint)
    identity.persist(store_path=store)

    supabase = MagicMock()
    table = supabase.table.return_value
    table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    table.upsert.return_value.execute.return_value = MagicMock(data=[])

    received: list[str] = []
    bus.subscribe("Device*", lambda event: received.append(event.event_type))

    registry = DeviceRegistry(
        supabase=supabase,
        identity=identity,
        certificate=certificate,
        event_bus=bus,
    )
    result = registry.register()

    assert result.is_new is True
    assert result.device_uuid == identity.device_uuid
    assert "DeviceRegistered" in received
    table.upsert.assert_called_once()


def test_device_registry_publishes_failure(bus: EventBus, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / "device.json"
    cert_dir = tmp_path / "device"
    monkeypatch.setattr("ottomandevice.device.identity.DEVICE_JSON_PATH", store)
    monkeypatch.setattr("ottomandevice.device.certificate.CERTIFICATE_DIR", cert_dir)
    monkeypatch.setattr("ottomandevice.device.certificate.PRIVATE_KEY_PATH", cert_dir / "private.key")
    monkeypatch.setattr("ottomandevice.device.certificate.PUBLIC_KEY_PATH", cert_dir / "public.key")
    monkeypatch.setattr("ottomandevice.device.certificate.METADATA_PATH", cert_dir / "certificate.json")

    identity = DeviceIdentity.load(store_path=store)
    certificate = DeviceCertificate.ensure(identity.device_uuid)

    supabase = MagicMock()
    table = supabase.table.return_value
    table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    table.upsert.return_value.execute.side_effect = RuntimeError("cloud unavailable")

    received: list[str] = []
    bus.subscribe("DeviceRegistrationFailed", lambda event: received.append(event.event_type))

    registry = DeviceRegistry(
        supabase=supabase,
        identity=identity,
        certificate=certificate,
        event_bus=bus,
    )

    with pytest.raises(DeviceIdentityError):
        registry.register()

    assert received == ["DeviceRegistrationFailed"]


def test_device_registry_updates_profile(bus: EventBus, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cert_dir = tmp_path / "device"
    monkeypatch.setattr("ottomandevice.device.certificate.CERTIFICATE_DIR", cert_dir)
    monkeypatch.setattr("ottomandevice.device.certificate.PRIVATE_KEY_PATH", cert_dir / "private.key")
    monkeypatch.setattr("ottomandevice.device.certificate.PUBLIC_KEY_PATH", cert_dir / "public.key")
    monkeypatch.setattr("ottomandevice.device.certificate.METADATA_PATH", cert_dir / "certificate.json")

    store = tmp_path / "device.json"
    store.write_text(
        json.dumps(
            {
                "device_uuid": "update-device",
                "installation_id": "install-id",
                "first_boot_timestamp": "2026-07-14T05:00:00+00:00",
                "hostname": "update-host",
            }
        ),
        encoding="utf-8",
    )
    identity = DeviceIdentity.load(store_path=store)
    certificate = DeviceCertificate.ensure(identity.device_uuid)
    profile = DeviceProfile.collect(identity)

    supabase = MagicMock()
    table = supabase.table.return_value
    table.upsert.return_value.execute.return_value = MagicMock(data=[])

    received: list[str] = []
    bus.subscribe("DeviceProfileUpdated", lambda event: received.append(event.event_type))

    registry = DeviceRegistry(
        supabase=supabase,
        identity=identity,
        certificate=certificate,
        event_bus=bus,
    )
    registry.update_profile(profile)

    assert received == ["DeviceProfileUpdated"]
    table.upsert.assert_called_once()
