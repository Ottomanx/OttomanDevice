from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MonitorOrientation(str, Enum):
    LANDSCAPE = "landscape"
    PORTRAIT = "portrait"


@dataclass(frozen=True)
class MonitorInfo:
    id: str
    number: int
    width: int
    height: int
    x: int
    y: int
    is_primary: bool

    @property
    def orientation(self) -> MonitorOrientation:
        if self.height > self.width:
            return MonitorOrientation.PORTRAIT
        return MonitorOrientation.LANDSCAPE

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "number": self.number,
            "width": self.width,
            "height": self.height,
            "is_primary": self.is_primary,
            "orientation": self.orientation.value,
        }


class MonitorChangeType(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    UPDATED = "updated"
    REORDERED = "reordered"
