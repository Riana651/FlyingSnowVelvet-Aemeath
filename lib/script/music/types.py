"""Music abstraction shared types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MusicTrack:
    """A normalized music track model used by provider adapters."""

    provider: str
    track_id: int | str
    title: str
    artist: str = ""
    duration_ms: int | None = None
    display: str = ""
    raw: dict[str, Any] | None = None

