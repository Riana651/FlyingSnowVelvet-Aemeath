"""网易云音乐管理器 - 缓存、格式检测与元信息 Mixin"""

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from lib.core.event.center import EventType, Event
from lib.core.logger import get_logger

from ._constants import (
    _CACHE_DIR,
    _CACHE_PLATFORM_DIRS,
    _AUDIO_EXT_CANDIDATES,
    _CONTENT_TYPE_EXT_MAP,
)

logger = get_logger(__name__)


class _CacheMixin:
    """缓存管理、音频格式检测与元信息读写。"""

    @staticmethod
    def _cache_platform_from_song_id(song_id) -> str:
        if isinstance(song_id, int):
            return "netease"
        if isinstance(song_id, str):
            text = song_id.strip().lower()
            if text.startswith("qq:"):
                return "qq"
            if text.startswith("kugou:"):
                return "kugou"
            if text.startswith("local::"):
                return "local"
            if text.startswith("netease:"):
                return "netease"
        return "other"

    @staticmethod
    def _cache_dir_for_platform(platform: str) -> Path:
        normalized = str(platform or "").strip().lower()
        if normalized not in _CACHE_PLATFORM_DIRS:
            normalized = "other"
        cache_dir = _CACHE_DIR / normalized
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    def _cache_dir_for_song(self, song_id) -> Path:
        return self._cache_dir_for_platform(self._cache_platform_from_song_id(song_id))

    @staticmethod
    def _iter_platform_cache_dirs() -> list[Path]:
        dirs: list[Path] = []
        for name in _CACHE_PLATFORM_DIRS:
            path = _CACHE_DIR / name
            if path.exists() and path.is_dir():
                dirs.append(path)
        # 兼容未来新增平台目录：遍历 temp 下其余子目录。
        if _CACHE_DIR.exists():
            for path in _CACHE_DIR.iterdir():
                if not path.is_dir():
                    continue
                if path in dirs:
                    continue
                dirs.append(path)
        return dirs

    # ------------------------------------------------------------------
    # 缓存大小管理
    # ------------------------------------------------------------------

    def _check_and_clean_cache(self):
        """检查缓存大小，超过 500MB 时清理缓存文件夹。"""
        MAX_CACHE_SIZE_MB = 500

        try:
            total_size = 0
            for cache_dir in self._iter_platform_cache_dirs():
                for file_path in cache_dir.rglob("*"):
                    if not file_path.is_file():
                        continue
                    try:
                        total_size += file_path.stat().st_size
                    except OSError:
                        continue

            total_size_mb = total_size / (1024 * 1024)

            if total_size_mb > MAX_CACHE_SIZE_MB:
                logger.info("[CloudMusic] 缓存大小 %.2f MB 超过限制 %d MB，开始清理",
                            total_size_mb, MAX_CACHE_SIZE_MB)
                self._clean_cache()
                logger.info("[CloudMusic] 缓存清理完成")
            else:
                logger.debug("[CloudMusic] 缓存大小 %.2f MB，无需清理", total_size_mb)

        except Exception as e:
            logger.error("[CloudMusic] 检查缓存大小失败: %s", e)

    def _clean_cache(self):
        """清理 temp 下各平台缓存子目录中的所有文件。"""
        try:
            for cache_dir in self._iter_platform_cache_dirs():
                for file_path in cache_dir.rglob("*"):
                    if not file_path.is_file():
                        continue
                    try:
                        file_path.unlink()
                    except Exception as e:
                        logger.warning("[CloudMusic] 删除缓存文件失败 %s: %s", file_path, e)
            # 清空时长缓存
            self._duration_cache.clear()
        except Exception as e:
            logger.error("[CloudMusic] 清理缓存失败: %s", e)

    # ------------------------------------------------------------------
    # 通用信息发布
    # ------------------------------------------------------------------

    def _show_info(self, text: str):
        """显示信息气泡。"""
        self._ec.publish(Event(EventType.INFORMATION, {
            "text": text,
            "min": 0,
            "max": 60,
        }))

    def _show_error(self, text: str):
        """显示错误信息。"""
        self._ec.publish(Event(EventType.INFORMATION, {
            "text": f"[云音乐] {text}",
            "min": 20,
            "max": 180,
        }))

    # ------------------------------------------------------------------
    # 音频格式检测
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_audio_ext(ext: str) -> str:
        """规范化音频扩展名，未知格式回落为 .mp3。"""
        normalized = str(ext or "").strip().lower()
        if not normalized:
            return ".mp3"
        if not normalized.startswith("."):
            normalized = f".{normalized}"
        alias_map = {
            ".wave": ".wav",
            ".mpga": ".mp3",
            ".oga":  ".ogg",
            ".weba": ".webm",
        }
        normalized = alias_map.get(normalized, normalized)
        if normalized not in _AUDIO_EXT_CANDIDATES:
            return ".mp3"
        return normalized

    @staticmethod
    def _audio_ext_from_url(url: str) -> str:
        """从 URL 路径提取扩展名。"""
        if not url:
            return ""
        try:
            path = unquote(urlparse(url).path or "")
            ext = Path(path).suffix.lower()
            return ext if ext in _AUDIO_EXT_CANDIDATES else ""
        except Exception:
            return ""

    @staticmethod
    def _sniff_audio_ext(header: bytes) -> str:
        """根据文件头识别常见音频容器格式。"""
        if not header:
            return ""
        if header.startswith(b"fLaC"):
            return ".flac"
        if len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WAVE":
            return ".wav"
        if header.startswith(b"OggS"):
            if b"OpusHead" in header[:96]:
                return ".opus"
            return ".ogg"
        if len(header) >= 8 and header[4:8] == b"ftyp":
            return ".m4a"
        if header.startswith(b"ID3"):
            return ".mp3"
        # MPEG 帧同步头（MP3/AAC），默认按 mp3 兜底。
        if len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0:
            return ".mp3"
        return ""

    def _detect_audio_ext(self, url: str, content_type: str, header: bytes) -> str:
        """
        识别音频扩展名（优先级：文件头 > Content-Type > URL 后缀 > .mp3）。
        """
        sniff_ext = self._sniff_audio_ext(header)
        if sniff_ext:
            return sniff_ext

        ctype = str(content_type or "").split(";", 1)[0].strip().lower()
        mapped = _CONTENT_TYPE_EXT_MAP.get(ctype)
        if mapped:
            return mapped

        url_ext = self._audio_ext_from_url(url)
        if url_ext:
            return url_ext

        return ".mp3"

    # ------------------------------------------------------------------
    # 缓存路径与文件操作
    # ------------------------------------------------------------------

    def _cache_path(self, song_id, ext: str = ".mp3") -> Path:
        """返回指定歌曲的缓存文件路径。"""
        normalized = self._normalize_audio_ext(ext)
        return self._cache_dir_for_song(song_id) / f"{self._cache_key(song_id)}{normalized}"

    @staticmethod
    def _legacy_cache_path(song_id, ext: str = ".mp3") -> Path:
        normalized = _CacheMixin._normalize_audio_ext(ext)
        return _CACHE_DIR / f"{_CacheMixin._cache_key(song_id)}{normalized}"

    def _repair_cached_audio_ext(self, song_id, path: Path) -> Path:
        """修正历史遗留的"扩展名与实际格式不一致"缓存文件。"""
        if not path.exists() or not path.is_file():
            return path
        try:
            with open(path, "rb") as f:
                header = f.read(96)
        except OSError:
            return path

        real_ext = self._sniff_audio_ext(header)
        if not real_ext:
            return path

        suffix = path.suffix.lower()
        if suffix == real_ext:
            return path

        target = self._cache_path(song_id, real_ext)
        try:
            if target.exists():
                try:
                    if target.stat().st_mtime >= path.stat().st_mtime:
                        path.unlink(missing_ok=True)
                        return target
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
            path.replace(target)
            logger.info("[CloudMusic] 修正缓存扩展名: %s -> %s", path.name, target.name)
            return target
        except OSError as e:
            logger.debug("[CloudMusic] 修正缓存扩展名失败 %s: %s", path, e)
            return path

    def _cleanup_song_audio_cache(self, song_id, keep_path: Path | None = None):
        """清理同一歌曲的多余格式缓存，仅保留 keep_path。"""
        keep_str = str(keep_path) if keep_path else ""
        for ext in _AUDIO_EXT_CANDIDATES:
            candidates = [
                self._cache_path(song_id, ext),
                self._legacy_cache_path(song_id, ext),
            ]
            for candidate in candidates:
                if not candidate.exists():
                    continue
                if keep_str and str(candidate) == keep_str:
                    continue
                try:
                    candidate.unlink()
                except OSError as e:
                    logger.debug("[CloudMusic] 清理旧缓存失败 %s: %s", candidate, e)

    def _find_cached_audio(self, song_id) -> Path | None:
        """查找并返回歌曲缓存（兼容多格式与历史错误扩展名）。"""
        found: list[Path] = []
        for ext in _AUDIO_EXT_CANDIDATES:
            path = self._cache_path(song_id, ext)
            legacy = self._legacy_cache_path(song_id, ext)

            if not path.exists() and legacy.exists():
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    legacy.replace(path)
                except OSError:
                    path = legacy

            if not path.exists():
                continue
            repaired = self._repair_cached_audio_ext(song_id, path)
            if repaired.exists():
                found.append(repaired)

        if not found:
            return None

        # 去重并优先使用最新缓存
        unique = list(dict.fromkeys(str(p) for p in found))
        candidates = [Path(p) for p in unique]
        if len(candidates) == 1:
            return candidates[0]
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        latest = candidates[0]
        self._cleanup_song_audio_cache(song_id, keep_path=latest)
        return latest

    # ------------------------------------------------------------------
    # 元信息读写
    # ------------------------------------------------------------------

    def _meta_path(self, song_id) -> Path:
        return self._cache_dir_for_song(song_id) / f"{self._cache_key(song_id)}.meta.json"

    def _save_meta(self, song_id, meta: dict):
        try:
            with open(self._meta_path(song_id), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error("[CloudMusic] 写元信息失败: %s", e)
    @staticmethod
    def _cache_key(song_id) -> str:
        """将歌曲标识映射为稳定且文件系统安全的缓存键。"""
        if isinstance(song_id, int):
            return str(song_id)
        text = str(song_id or "").strip()
        if not text:
            return "unknown"
        if re.fullmatch(r"[A-Za-z0-9._-]+", text):
            return text
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
        return f"id_{digest}"
