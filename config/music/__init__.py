"""音乐配置模块"""
from config.music.history import (
    get_music_history,
    cleanup_music_history,
    MusicHistory,
)
from config.music.volume_config import (
    get_volume_config,
    cleanup_volume_config,
    VolumeConfig,
)

__all__ = [
    "get_music_history",
    "cleanup_music_history",
    "MusicHistory",
    "get_volume_config",
    "cleanup_volume_config",
    "VolumeConfig",
]
