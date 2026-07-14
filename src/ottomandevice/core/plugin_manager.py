from __future__ import annotations

import importlib
import importlib.util
import inspect
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ottomandevice.core.event_bus import (
    EventBus,
    PluginFailed,
    PluginInitialized,
    PluginInstalled,
    PluginStarted,
    PluginStopped,
    PluginUninstalled,
)
from ottomandevice.core.exceptions import PluginError
from ottomandevice.plugins.base import BasePlugin, PluginMetadata, PluginState


@dataclass
class ManagedPlugin:
    """Tracked plugin entry managed by the plugin manager."""

    plugin_id: str
    plugin_class: type[BasePlugin]
    metadata: PluginMetadata
    module_name: str
    instance: BasePlugin | None = None
    state: PluginState = PluginState.DISCOVERED
    error: str | None = None


class PluginManager:
    """Thread-safe plugin discovery, dependency resolution, and lifecycle manager."""

    _instance: PluginManager | None = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        *,
        plugins_package: str = "ottomandevice.plugins",
        plugins_root: Path | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._plugins_package = plugins_package
        self._plugins_root = plugins_root
        self._event_bus = event_bus or EventBus.get_instance()
        self._lock = threading.RLock()
        self._plugins: dict[str, ManagedPlugin] = {}
        self._load_order: list[str] = []

    @classmethod
    def get_instance(
        cls,
        *,
        plugins_package: str = "ottomandevice.plugins",
        plugins_root: Path | None = None,
        event_bus: EventBus | None = None,
    ) -> PluginManager:
        """Return the process-wide plugin manager singleton."""
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(
                    plugins_package=plugins_package,
                    plugins_root=plugins_root,
                    event_bus=event_bus,
                )
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton. Intended for tests."""
        with cls._instance_lock:
            cls._instance = None

    @property
    def plugins(self) -> dict[str, ManagedPlugin]:
        """Return a snapshot of managed plugins keyed by plugin id."""
        with self._lock:
            return dict(self._plugins)

    @property
    def load_order(self) -> tuple[str, ...]:
        """Return the resolved plugin load order."""
        with self._lock:
            return tuple(self._load_order)

    def discover(self) -> list[str]:
        """Discover plugins from the configured plugins root."""
        with self._lock:
            root = self._resolve_plugins_root()
            discovered: list[str] = []

            for entry in sorted(root.iterdir()):
                if not entry.is_dir() or entry.name.startswith("_"):
                    continue
                if entry.name == "__pycache__":
                    continue

                plugin_id = self._register_plugin_from_path(entry)
                if plugin_id is not None:
                    discovered.append(plugin_id)

            return discovered

    def load_all(self) -> None:
        """Discover, resolve dependencies, and run the full plugin lifecycle."""
        with self._lock:
            if not self._plugins:
                self.discover()

            order = self._resolve_dependencies()
            self._load_order = order

            for plugin_id in order:
                self._install_locked(plugin_id)
            for plugin_id in order:
                self._initialize_locked(plugin_id)
            for plugin_id in order:
                self._start_locked(plugin_id)

    def install(self, plugin_id: str) -> None:
        """Install a discovered plugin."""
        with self._lock:
            self._install_locked(plugin_id)

    def initialize(self, plugin_id: str) -> None:
        """Initialize an installed plugin."""
        with self._lock:
            self._initialize_locked(plugin_id)

    def start(self, plugin_id: str) -> None:
        """Start an initialized plugin."""
        with self._lock:
            self._start_locked(plugin_id)

    def stop(self, plugin_id: str) -> None:
        """Stop a started plugin."""
        with self._lock:
            self._stop_locked(plugin_id)

    def uninstall(self, plugin_id: str) -> None:
        """Uninstall a plugin and release its resources."""
        with self._lock:
            self._uninstall_locked(plugin_id)

    def shutdown(self) -> None:
        """Stop and uninstall all managed plugins in reverse dependency order."""
        with self._lock:
            order = list(self._load_order) or list(self._plugins.keys())

            for plugin_id in reversed(order):
                managed = self._plugins.get(plugin_id)
                if managed is None:
                    continue
                if managed.state == PluginState.STARTED:
                    self._stop_locked(plugin_id)

            for plugin_id in reversed(order):
                managed = self._plugins.get(plugin_id)
                if managed is None:
                    continue
                if managed.state in {PluginState.STOPPED, PluginState.INITIALIZED, PluginState.INSTALLED}:
                    self._uninstall_locked(plugin_id)

    def get_state(self, plugin_id: str) -> PluginState | None:
        """Return the lifecycle state for a plugin id."""
        with self._lock:
            managed = self._plugins.get(plugin_id)
            return managed.state if managed is not None else None

    def get_plugin(self, plugin_id: str) -> BasePlugin | None:
        """Return the active plugin instance, if loaded."""
        with self._lock:
            managed = self._plugins.get(plugin_id)
            return managed.instance if managed is not None else None

    def _resolve_plugins_root(self) -> Path:
        if self._plugins_root is not None:
            if not self._plugins_root.exists():
                raise PluginError(f"Plugins root does not exist: {self._plugins_root}")
            return self._plugins_root

        package = importlib.import_module(self._plugins_package)
        package_path = getattr(package, "__path__", None)
        if not package_path:
            raise PluginError(f"Plugins package has no path: {self._plugins_package}")
        return Path(package_path[0])

    def _register_plugin_from_path(self, path: Path) -> str | None:
        module, module_name = self._import_plugin_module(path)
        plugin_class = self._resolve_plugin_class(module)
        if plugin_class is None:
            return None

        metadata = self._extract_metadata(plugin_class)
        if metadata.id in self._plugins:
            raise PluginError(f"Duplicate plugin id discovered: {metadata.id}")

        self._plugins[metadata.id] = ManagedPlugin(
            plugin_id=metadata.id,
            plugin_class=plugin_class,
            metadata=metadata,
            module_name=module_name,
        )
        return metadata.id

    def _import_plugin_module(self, path: Path) -> tuple[Any, str]:
        if self._plugins_root is None:
            module_name = f"{self._plugins_package}.{path.name}"
            module = importlib.import_module(module_name)
            return module, module_name

        init_file = path / "__init__.py"
        plugin_file = path / "plugin.py"
        if plugin_file.exists():
            file_path = plugin_file
        elif init_file.exists():
            file_path = init_file
        else:
            raise PluginError(f"Plugin package missing entrypoint: {path}")

        module_name = f"_ottomandevice_plugin_{path.name}"
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise PluginError(f"Unable to load plugin module from {file_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module, module_name

    @staticmethod
    def _resolve_plugin_class(module: Any) -> type[BasePlugin] | None:
        plugin_class = getattr(module, "plugin_class", None)
        if plugin_class is not None and inspect.isclass(plugin_class) and issubclass(plugin_class, BasePlugin):
            return plugin_class

        candidates: list[type[BasePlugin]] = []
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj is BasePlugin:
                continue
            if issubclass(obj, BasePlugin) and obj.__module__ == module.__name__:
                candidates.append(obj)

        if len(candidates) == 1:
            return candidates[0]
        return None

    @staticmethod
    def _extract_metadata(plugin_class: type[BasePlugin]) -> PluginMetadata:
        class_metadata = getattr(plugin_class, "PLUGIN_METADATA", None)
        if isinstance(class_metadata, PluginMetadata):
            return class_metadata

        instance = plugin_class()
        return instance.metadata

    def _resolve_dependencies(self) -> list[str]:
        if not self._plugins:
            return []

        in_degree: dict[str, int] = {plugin_id: 0 for plugin_id in self._plugins}
        dependents: dict[str, list[str]] = {plugin_id: [] for plugin_id in self._plugins}

        for plugin_id, managed in self._plugins.items():
            for dependency in managed.metadata.dependencies:
                if dependency not in self._plugins:
                    raise PluginError(
                        f"Plugin '{plugin_id}' depends on missing plugin '{dependency}'"
                    )
                in_degree[plugin_id] += 1
                dependents[dependency].append(plugin_id)

        ready = sorted(plugin_id for plugin_id, degree in in_degree.items() if degree == 0)
        order: list[str] = []

        while ready:
            current = ready.pop(0)
            order.append(current)
            for dependent in sorted(dependents[current]):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    ready.append(dependent)
            ready.sort()

        if len(order) != len(self._plugins):
            raise PluginError("Circular plugin dependency detected")

        return order

    def _get_managed(self, plugin_id: str) -> ManagedPlugin:
        managed = self._plugins.get(plugin_id)
        if managed is None:
            raise PluginError(f"Unknown plugin: {plugin_id}")
        return managed

    def _publish(self, event: Any) -> None:
        self._event_bus.publish(event)

    def _install_locked(self, plugin_id: str) -> None:
        managed = self._get_managed(plugin_id)
        if managed.state != PluginState.DISCOVERED:
            return

        try:
            managed.instance = managed.plugin_class()
            managed.instance.install()
            managed.state = PluginState.INSTALLED
            self._publish(
                PluginInstalled(
                    plugin_id=managed.metadata.id,
                    name=managed.metadata.name,
                    version=managed.metadata.version,
                )
            )
        except Exception as exc:
            managed.state = PluginState.FAILED
            managed.error = str(exc)
            self._publish(
                PluginFailed(
                    plugin_id=plugin_id,
                    phase="install",
                    error=str(exc),
                )
            )
            raise PluginError(f"Failed to install plugin '{plugin_id}': {exc}") from exc

    def _initialize_locked(self, plugin_id: str) -> None:
        managed = self._get_managed(plugin_id)
        if managed.state != PluginState.INSTALLED:
            return
        if managed.instance is None:
            raise PluginError(f"Plugin '{plugin_id}' is not instantiated")

        try:
            managed.instance.initialize()
            managed.state = PluginState.INITIALIZED
            self._publish(PluginInitialized(plugin_id=managed.metadata.id))
        except Exception as exc:
            managed.state = PluginState.FAILED
            managed.error = str(exc)
            self._publish(
                PluginFailed(
                    plugin_id=plugin_id,
                    phase="initialize",
                    error=str(exc),
                )
            )
            raise PluginError(f"Failed to initialize plugin '{plugin_id}': {exc}") from exc

    def _start_locked(self, plugin_id: str) -> None:
        managed = self._get_managed(plugin_id)
        if managed.state != PluginState.INITIALIZED:
            return
        if managed.instance is None:
            raise PluginError(f"Plugin '{plugin_id}' is not instantiated")

        try:
            managed.instance.start()
            managed.state = PluginState.STARTED
            self._publish(PluginStarted(plugin_id=managed.metadata.id))
        except Exception as exc:
            managed.state = PluginState.FAILED
            managed.error = str(exc)
            self._publish(
                PluginFailed(
                    plugin_id=plugin_id,
                    phase="start",
                    error=str(exc),
                )
            )
            raise PluginError(f"Failed to start plugin '{plugin_id}': {exc}") from exc

    def _stop_locked(self, plugin_id: str) -> None:
        managed = self._get_managed(plugin_id)
        if managed.state != PluginState.STARTED:
            return
        if managed.instance is None:
            return

        try:
            managed.instance.stop()
            managed.state = PluginState.STOPPED
            self._publish(PluginStopped(plugin_id=managed.metadata.id))
        except Exception as exc:
            managed.state = PluginState.FAILED
            managed.error = str(exc)
            self._publish(
                PluginFailed(
                    plugin_id=plugin_id,
                    phase="stop",
                    error=str(exc),
                )
            )
            raise PluginError(f"Failed to stop plugin '{plugin_id}': {exc}") from exc

    def _uninstall_locked(self, plugin_id: str) -> None:
        managed = self._get_managed(plugin_id)
        if managed.state == PluginState.UNINSTALLED:
            return
        if managed.instance is None:
            managed.state = PluginState.UNINSTALLED
            return

        try:
            managed.instance.uninstall()
            managed.state = PluginState.UNINSTALLED
            managed.instance = None
            self._publish(PluginUninstalled(plugin_id=managed.metadata.id))
        except Exception as exc:
            managed.state = PluginState.FAILED
            managed.error = str(exc)
            self._publish(
                PluginFailed(
                    plugin_id=plugin_id,
                    phase="uninstall",
                    error=str(exc),
                )
            )
            raise PluginError(f"Failed to uninstall plugin '{plugin_id}': {exc}") from exc
