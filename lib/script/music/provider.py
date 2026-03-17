"""Music provider abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .types import MusicTrack


class MusicProvider(ABC):
    """Provider interface for external music platform integrations."""

    provider_name: str = ""

    @abstractmethod
    def search(self, keyword: str, mode: str = "song", limit: int = 25) -> list[MusicTrack]:
        """Search tracks from provider and return normalized results."""

