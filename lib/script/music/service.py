"""Music service facade.

This module provides a single entry-point for all music platform interactions.
Callers should avoid importing provider-specific modules directly.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from config.config import CLOUD_MUSIC
from lib.core.logger import get_logger

from .provider import MusicProvider
from .providers import KugouMusicProvider, NetEaseMusicProvider, QQMusicProvider
from .types import MusicTrack

logger = get_logger(__name__)

_instance: Optional["MusicService"] = None
_PROVIDER_ORDER: tuple[str, ...] = ("netease", "qq", "kugou")
_CONFIG_DICT_FILE_MAP: dict[str, str] = {
    "CLOUD_MUSIC": "config_music.py",
}
_PROVIDER_MODE_LABELS: dict[str, str] = {
    "netease": "网易模式",
    "qq": "QQ模式",
    "kugou": "酷狗模式",
}


class MusicService:
    """Facade for provider search + playback backend access."""

    def __init__(self):
        self._providers: dict[str, MusicProvider] = {
            "netease": NetEaseMusicProvider(),
            "qq": QQMusicProvider(),
            "kugou": KugouMusicProvider(),
        }
        default_provider = _PROVIDER_ORDER[0]
        requested = str(CLOUD_MUSIC.get("provider", default_provider) or default_provider).strip().lower()
        if requested not in self._providers:
            logger.warning("[MusicService] 未知 provider=%s，回退 netease", requested)
            requested = default_provider
        self._provider_name = requested
        CLOUD_MUSIC["provider"] = requested
        logger.info("[MusicService] 当前 provider=%s", self._provider_name)

    # ------------------------------------------------------------------
    # Provider routing
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def provider_mode_label(self) -> str:
        return _PROVIDER_MODE_LABELS.get(self._provider_name, f"{self._provider_name.upper()}模式")

    def available_providers(self) -> list[str]:
        ordered = [name for name in _PROVIDER_ORDER if name in self._providers]
        extras = [name for name in self._providers.keys() if name not in ordered]
        return ordered + extras

    def set_provider(self, provider_name: str, persist: bool = False) -> bool:
        normalized = str(provider_name or "").strip().lower()
        if normalized not in self._providers:
            return False
        if normalized == self._provider_name:
            CLOUD_MUSIC["provider"] = normalized
            mgr = self._get_backend_manager()
            if mgr is not None and hasattr(mgr, "refresh_login_status"):
                try:
                    mgr.refresh_login_status()
                except Exception:
                    pass
            if persist:
                self._persist_provider_config(normalized)
            return True

        # netease / qq / kugou 共用同一个 cloudmusic backend，切换平台不销毁后端，
        # 以保留各平台已恢复的登录会话，避免频繁切换后重复登录。
        old_provider = self._provider_name
        should_keep_backend = {old_provider, normalized}.issubset({"netease", "qq", "kugou"})
        if not should_keep_backend:
            self.cleanup_backend()
        self._provider_name = normalized
        CLOUD_MUSIC["provider"] = normalized
        mgr = self.initialize()
        if mgr is not None and hasattr(mgr, "refresh_login_status"):
            try:
                mgr.refresh_login_status()
            except Exception:
                pass
        logger.info("[MusicService] provider 已切换: %s", normalized)
        if persist:
            self._persist_provider_config(normalized)
        return True

    def cycle_provider(self, persist: bool = False) -> str | None:
        providers = self.available_providers()
        if not providers:
            return None
        try:
            idx = providers.index(self._provider_name)
        except ValueError:
            idx = 0
        target = providers[(idx + 1) % len(providers)]
        if not self.set_provider(target, persist=persist):
            return None
        return target

    def get_provider(self) -> MusicProvider:
        return self._providers[self._provider_name]

    def search(self, keyword: str, mode: str = "song", limit: int = 25) -> list[MusicTrack]:
        return self.get_provider().search(keyword, mode=mode, limit=limit)

    def search_first(self, keyword: str, mode: str = "song", limit: int = 20) -> MusicTrack | None:
        tracks = self.search(keyword, mode=mode, limit=limit)
        return tracks[0] if tracks else None

    # ------------------------------------------------------------------
    # Playback backend bridge (current provider implementation)
    # ------------------------------------------------------------------

    def _get_backend_manager(self):
        if self._provider_name in {"netease", "qq", "kugou"}:
            from lib.script.cloudmusic.manager import get_cloud_music_manager

            return get_cloud_music_manager()
        return None

    def initialize(self):
        """Ensure current provider backend is initialized."""
        return self._get_backend_manager()

    def cleanup_backend(self):
        if self._provider_name in {"netease", "qq", "kugou"}:
            try:
                from lib.script.cloudmusic.manager import cleanup_cloud_music_manager

                cleanup_cloud_music_manager()
            except Exception as e:
                logger.warning("[MusicService] 清理音乐 backend 失败: %s", e)

    def is_playing(self) -> bool:
        mgr = self._get_backend_manager()
        return bool(getattr(mgr, "is_playing", False)) if mgr is not None else False

    def is_paused(self) -> bool:
        mgr = self._get_backend_manager()
        return bool(getattr(mgr, "is_paused", False)) if mgr is not None else False

    def is_logged_in(self) -> bool:
        mgr = self._get_backend_manager()
        return bool(getattr(mgr, "is_logged_in", False)) if mgr is not None else False

    def play_mode(self) -> str:
        mgr = self._get_backend_manager()
        if mgr is None:
            return "list_loop"
        return str(getattr(mgr, "play_mode", "list_loop"))

    def get_volume(self) -> float:
        mgr = self._get_backend_manager()
        if mgr is None:
            return 0.0
        try:
            return float(getattr(mgr, "_volume", 0.0))
        except Exception:
            return 0.0

    def get_volume_percent(self) -> int:
        return int(round(self.get_volume() * 100))

    def queue_snapshot(self) -> list:
        mgr = self._get_backend_manager()
        if mgr is None:
            return []
        return list(getattr(mgr, "queue", []))

    def current_index(self) -> int:
        mgr = self._get_backend_manager()
        if mgr is None:
            return -1
        try:
            return int(getattr(mgr, "current_index", -1))
        except Exception:
            return -1

    def move_queue_item(self, index: int, direction: int) -> int:
        mgr = self._get_backend_manager()
        if mgr is None:
            return -1
        return int(mgr.move_queue_item(index, direction))

    def remove_queue_item(self, index: int) -> bool:
        mgr = self._get_backend_manager()
        if mgr is None:
            return False
        return bool(mgr.remove_queue_item(index))

    def remove_song_from_history(self, song_id) -> bool:
        mgr = self._get_backend_manager()
        if mgr is None:
            return False
        try:
            return bool(mgr.remove_song_from_history(song_id))
        except Exception:
            return False

    def next_track(self):
        mgr = self._get_backend_manager()
        if mgr is not None:
            mgr.next_track()

    def clear_queue(self):
        mgr = self._get_backend_manager()
        if mgr is not None:
            mgr.clear_queue()

    def pause(self):
        mgr = self._get_backend_manager()
        if mgr is not None:
            mgr.pause()

    # ------------------------------------------------------------------
    # Config persistence
    # ------------------------------------------------------------------

    @staticmethod
    def _config_path(dict_name: str = "") -> Path:
        config_root = Path(__file__).resolve().parents[3] / "config"
        filename = _CONFIG_DICT_FILE_MAP.get(str(dict_name or "").strip(), "config.py")
        return config_root / filename

    @staticmethod
    def _py_literal_any(value) -> str:
        if isinstance(value, bool):
            return "True" if value else "False"
        if isinstance(value, (int, float, str)):
            return repr(value)
        return repr(value)

    @staticmethod
    def _replace_config_dict_item(text: str, dict_name: str, key: str, py_literal: str) -> str:
        block_pattern = re.compile(
            rf"(?ms)^(\s*{re.escape(dict_name)}\s*=\s*\{{)(.*?)(^\s*\}})",
        )
        block_match = block_pattern.search(text)
        if not block_match:
            raise ValueError(f"未找到配置字典: {dict_name}")

        body = block_match.group(2)
        item_pattern = re.compile(rf"(?m)^(\s*'{re.escape(key)}'\s*:\s*).*(,\s*(?:#.*)?)$")
        if not item_pattern.search(body):
            raise ValueError(f"未找到配置项: {dict_name}.{key}")
        new_body = item_pattern.sub(lambda m: f"{m.group(1)}{py_literal}{m.group(2)}", body, count=1)
        return text[:block_match.start(2)] + new_body + text[block_match.end(2):]

    def _persist_provider_config(self, provider_name: str) -> bool:
        try:
            cfg_path = self._config_path("CLOUD_MUSIC")
            text = cfg_path.read_text(encoding="utf-8")
            text = self._replace_config_dict_item(
                text,
                "CLOUD_MUSIC",
                "provider",
                self._py_literal_any(provider_name),
            )
            tmp_path = cfg_path.with_suffix(".py.tmp")
            tmp_path.write_text(text, encoding="utf-8")
            tmp_path.replace(cfg_path)
            return True
        except Exception as e:
            logger.warning("[MusicService] 保存 provider 到配置失败: %s", e)
            return False


def get_music_service() -> MusicService:
    global _instance
    if _instance is None:
        _instance = MusicService()
    return _instance


def cleanup_music_service():
    global _instance
    if _instance is None:
        return
    _instance.cleanup_backend()
    _instance = None
