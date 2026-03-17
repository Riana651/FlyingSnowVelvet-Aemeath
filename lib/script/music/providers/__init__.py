"""Built-in music providers."""

from .kugou_provider import KugouMusicProvider
from .netease_provider import NetEaseMusicProvider
from .qq_provider import QQMusicProvider

__all__ = ["NetEaseMusicProvider", "QQMusicProvider", "KugouMusicProvider"]
