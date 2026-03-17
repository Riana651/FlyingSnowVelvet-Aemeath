"""Music abstraction public API."""

from .service import MusicService, get_music_service, cleanup_music_service
from .types import MusicTrack

__all__ = [
    "MusicService",
    "MusicTrack",
    "get_music_service",
    "cleanup_music_service",
]

