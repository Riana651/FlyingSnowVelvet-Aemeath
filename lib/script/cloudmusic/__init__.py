"""cloudmusic 包公开接口"""

from lib.script.cloudmusic.manager import (
    CloudMusicManager,
    clear_all_history_and_login_data,
    get_cloud_music_manager,
    cleanup_cloud_music_manager,
)

__all__ = [
    "CloudMusicManager",
    "clear_all_history_and_login_data",
    "get_cloud_music_manager",
    "cleanup_cloud_music_manager",
]
