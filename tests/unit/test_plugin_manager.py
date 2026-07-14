from __future__ import annotations

import textwrap
import threading
from pathlib import Path

import pytest

from ottomandevice.core.event_bus import EventBus
from ottomandevice.core.exceptions import PluginError
from ottomandevice.core.plugin_manager import PluginManager
from ottomandevice.plugins.base import (
    AIPlugin,
    AudioPlugin,
    BasePlugin,
    CameraPlugin,
    DevicePlugin,
    PluginMetadata,
    PluginState,
)


@pytest.fixture
def bus() -> EventBus:
    event_bus = EventBus(max_history=100)
    yield event_bus
    event_bus.shutdown()


@pytest.fixture(autouse=True)
def reset_plugin_manager() -> None:
    PluginManager.reset_instance()
    yield
    PluginManager.reset_instance()


def _write_plugin_package(
    root: Path,
    *,
    package_name: str,
    plugin_id: str,
    dependencies: tuple[str, ...] = (),
    base: str = "BasePlugin",
    fail_phase: str | None = None,
) -> None:
    package_dir = root / package_name
    package_dir.mkdir(parents=True, exist_ok=True)
    fail_install = "raise RuntimeError('install failed')" if fail_phase == "install" else "pass"
    fail_initialize = "raise RuntimeError('initialize failed')" if fail_phase == "initialize" else "pass"
    fail_start = "raise RuntimeError('start failed')" if fail_phase == "start" else "pass"
    content = textwrap.dedent(
        f"""
        from ottomandevice.plugins.base import {base}, PluginMetadata

        class SamplePlugin({base}):
            PLUGIN_METADATA = PluginMetadata(
                id="{plugin_id}",
                name="{plugin_id.title()} Plugin",
                version="1.0.0",
                author="test",
                dependencies={dependencies!r},
                description="test plugin",
            )

            def __init__(self) -> None:
                self.events: list[str] = []

            @property
            def metadata(self) -> PluginMetadata:
                return self.PLUGIN_METADATA

            def install(self) -> None:
                self.events.append("install")
                {fail_install}

            def initialize(self) -> None:
                self.events.append("initialize")
                {fail_initialize}

            def start(self) -> None:
                self.events.append("start")
                {fail_start}

            def stop(self) -> None:
                self.events.append("stop")

            def uninstall(self) -> None:
                self.events.append("uninstall")

        plugin_class = SamplePlugin
        """
    ).strip() + "\n"
    (package_dir / "__init__.py").write_text(content, encoding="utf-8")


def test_plugin_interfaces_are_base_plugins() -> None:
    assert issubclass(DevicePlugin, BasePlugin)
    assert issubclass(AIPlugin, BasePlugin)
    assert issubclass(CameraPlugin, BasePlugin)
    assert issubclass(AudioPlugin, BasePlugin)


def test_discover_and_load_plugins(tmp_path: Path, bus: EventBus) -> None:
    _write_plugin_package(tmp_path, package_name="alpha", plugin_id="alpha")
    _write_plugin_package(tmp_path, package_name="beta", plugin_id="beta", dependencies=("alpha",))

    manager = PluginManager(plugins_root=tmp_path, event_bus=bus)
    discovered = manager.discover()

    assert discovered == ["alpha", "beta"]
    manager.load_all()

    alpha = manager.get_plugin("alpha")
    beta = manager.get_plugin("beta")
    assert alpha is not None and beta is not None
    assert alpha.events == ["install", "initialize", "start"]
    assert beta.events == ["install", "initialize", "start"]
    assert manager.load_order == ("alpha", "beta")
    assert manager.get_state("alpha") == PluginState.STARTED


def test_dependency_resolution_errors(tmp_path: Path, bus: EventBus) -> None:
    _write_plugin_package(tmp_path, package_name="child", plugin_id="child", dependencies=("missing",))

    manager = PluginManager(plugins_root=tmp_path, event_bus=bus)
    manager.discover()

    with pytest.raises(PluginError, match="missing plugin"):
        manager.load_all()


def test_circular_dependency_detection(tmp_path: Path, bus: EventBus) -> None:
    _write_plugin_package(tmp_path, package_name="one", plugin_id="one", dependencies=("two",))
    _write_plugin_package(tmp_path, package_name="two", plugin_id="two", dependencies=("one",))

    manager = PluginManager(plugins_root=tmp_path, event_bus=bus)
    manager.discover()

    with pytest.raises(PluginError, match="Circular"):
        manager.load_all()


def test_lifecycle_events_are_published(tmp_path: Path, bus: EventBus) -> None:
    _write_plugin_package(tmp_path, package_name="eventful", plugin_id="eventful")
    received: list[str] = []
    bus.subscribe("Plugin*", lambda event: received.append(event.event_type))

    manager = PluginManager(plugins_root=tmp_path, event_bus=bus)
    manager.discover()
    manager.load_all()
    manager.shutdown()

    assert received == [
        "PluginInstalled",
        "PluginInitialized",
        "PluginStarted",
        "PluginStopped",
        "PluginUninstalled",
    ]


def test_install_failure_publishes_plugin_failed(tmp_path: Path, bus: EventBus) -> None:
    _write_plugin_package(tmp_path, package_name="broken", plugin_id="broken", fail_phase="install")
    received: list[str] = []

    bus.subscribe("PluginFailed", lambda event: received.append(event.event_type))

    manager = PluginManager(plugins_root=tmp_path, event_bus=bus)
    manager.discover()

    with pytest.raises(PluginError):
        manager.load_all()

    assert received == ["PluginFailed"]
    assert manager.get_state("broken") == PluginState.FAILED


def test_shutdown_stops_plugins_in_reverse_order(tmp_path: Path, bus: EventBus) -> None:
    _write_plugin_package(tmp_path, package_name="alpha", plugin_id="alpha")
    _write_plugin_package(tmp_path, package_name="beta", plugin_id="beta", dependencies=("alpha",))

    manager = PluginManager(plugins_root=tmp_path, event_bus=bus)
    manager.discover()
    manager.load_all()
    manager.shutdown()

    assert manager.get_plugin("alpha") is None
    assert manager.get_plugin("beta") is None
    assert manager.get_state("alpha") == PluginState.UNINSTALLED
    assert manager.get_state("beta") == PluginState.UNINSTALLED


def test_plugin_manager_singleton_is_thread_safe(bus: EventBus) -> None:
    instances: list[PluginManager] = []

    def worker() -> None:
        instances.append(PluginManager.get_instance(event_bus=bus))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(instances) == 8
    assert all(instance is instances[0] for instance in instances)


def test_individual_lifecycle_methods(tmp_path: Path, bus: EventBus) -> None:
    _write_plugin_package(tmp_path, package_name="solo", plugin_id="solo")

    manager = PluginManager(plugins_root=tmp_path, event_bus=bus)
    manager.discover()

    manager.install("solo")
    assert manager.get_state("solo") == PluginState.INSTALLED

    manager.initialize("solo")
    assert manager.get_state("solo") == PluginState.INITIALIZED

    manager.start("solo")
    assert manager.get_state("solo") == PluginState.STARTED

    manager.stop("solo")
    assert manager.get_state("solo") == PluginState.STOPPED

    manager.uninstall("solo")
    assert manager.get_state("solo") == PluginState.UNINSTALLED
