"""Camera plugin package for OttomanDevice."""

from ottomandevice.plugins.camera.capture import CameraCapture, FrameResult
from ottomandevice.plugins.camera.device import CameraDevice
from ottomandevice.plugins.camera.health import CameraHealth, CameraHealthSnapshot
from ottomandevice.plugins.camera.manager import CameraManager
from ottomandevice.plugins.camera.plugin import OttomanCameraPlugin

plugin_class = OttomanCameraPlugin

__all__ = [
    "CameraCapture",
    "CameraDevice",
    "CameraHealth",
    "CameraHealthSnapshot",
    "CameraManager",
    "FrameResult",
    "OttomanCameraPlugin",
    "plugin_class",
]
