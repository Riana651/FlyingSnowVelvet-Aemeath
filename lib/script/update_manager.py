"""Github 发布检查与自动更新管理器。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests

from config.version_info import (
    RESOURCE_RELEASE_DATE,
    RESOURCE_VERSION,
    GITHUB_REPO,
)
from lib.core.logger import get_logger

_logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_STATE_PATH = _PROJECT_ROOT / "resc" / "user" / "update_state.json"
_API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "FlyingSnowVelvet-Updater/1.0",
}
_ASSET_HEADERS = {
    "Accept": "application/octet-stream",
    "User-Agent": "FlyingSnowVelvet-Updater/1.0",
}
_PROTECTED_ROOTS = ("logs", "resc/user", "resc/models")
_PROTECTED_FILES = ("py.ini",)


class UpdateError(RuntimeError):
    """更新流程异常。"""


@dataclass
class InstalledState:
    version: str
    installed_at: datetime


@dataclass
class ReleaseInfo:
    tag: str
    published_at: datetime
    asset_name: str
    download_url: str


@dataclass
class UpdateResult:
    updated: bool
    installed_state: InstalledState
    release_info: ReleaseInfo
    reason: str = ""


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    value = value.strip()
    if not value:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
    except ValueError:
        try:
            dt = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return datetime(1970, 1, 1, tzinfo=timezone.utc)
        else:
            dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt


def _isoformat(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    text = dt.isoformat()
    return text.replace("+00:00", "Z")


def _normalize_relative_path(rel_path: Path) -> str:
    if rel_path == Path("."):
        return ""
    parts = [part for part in rel_path.parts if part not in (".", "")]
    return "/".join(parts)


def _is_protected_path(rel_path: Path) -> bool:
    rel = _normalize_relative_path(rel_path)
    if not rel:
        return False
    for file_name in _PROTECTED_FILES:
        if rel == file_name:
            return True
    for root in _PROTECTED_ROOTS:
        if rel == root or rel.startswith(root + "/"):
            return True
    return False


class UpdateManager:
    """负责检测 GitHub 发布并自动更新本地资源。"""

    def __init__(
        self,
        *,
        repo: str = GITHUB_REPO,
        state_path: Path | None = None,
        info_callback: Callable[[str], None] | None = None,
    ):
        self._repo = repo
        self._state_path = Path(state_path) if state_path else _STATE_PATH
        self._info_callback = info_callback

    def check_and_update(self) -> UpdateResult:
        installed = self._load_installed_state()
        release = self._fetch_latest_release()
        if release.published_at <= installed.installed_at:
            reason = "up_to_date"
            self._info(
                f"当前已为最新版本 {installed.version}（{installed.installed_at.date()}），无需更新。"
            )
            return UpdateResult(False, installed, release, reason=reason)

        self._info(
            f"检测到新版本 {release.tag}（{release.published_at.date()}），开始下载..."
        )
        with tempfile.TemporaryDirectory(prefix="fs-update-") as tmp_dir:
            tmp_path = Path(tmp_dir) / (release.asset_name or "release.zip")
            self._download_release(release, tmp_path)
            self._info("下载完成，正在解压并覆盖文件...")
            self._extract_and_copy(tmp_path)

        self._write_installed_state(release)
        new_state = InstalledState(release.tag, release.published_at)
        self._info("更新完成，建议重启程序以载入最新资源。")
        return UpdateResult(True, new_state, release, reason="updated")

    # ------------------------------------------------------------------ #
    # 内部辅助
    # ------------------------------------------------------------------ #

    def _info(self, message: str) -> None:
        if self._info_callback:
            try:
                self._info_callback(message)
                return
            except Exception:  # pragma: no cover - 安全兜底
                _logger.debug("update info callback failed", exc_info=True)
        _logger.info("[Update] %s", message)

    def _load_installed_state(self) -> InstalledState:
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                version = str(data.get("version") or RESOURCE_VERSION)
                installed_at = _parse_datetime(data.get("installed_at"))
                return InstalledState(version, installed_at)
            except Exception as exc:
                _logger.warning("failed to parse update state: %s", exc)
        baseline = InstalledState(
            version=RESOURCE_VERSION,
            installed_at=_parse_datetime(RESOURCE_RELEASE_DATE),
        )
        return baseline

    def _write_installed_state(self, release: ReleaseInfo) -> None:
        payload = {
            "version": release.tag,
            "installed_at": _isoformat(release.published_at),
        }
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _fetch_latest_release(self) -> ReleaseInfo:
        url = f"https://api.github.com/repos/{self._repo}/releases/latest"
        try:
            resp = requests.get(url, timeout=15, headers=_API_HEADERS)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:  # pragma: no cover - 网络错误
            raise UpdateError(f"无法访问 GitHub：{exc}") from exc
        except ValueError as exc:  # pragma: no cover - JSON 解析失败
            raise UpdateError("GitHub 返回格式异常") from exc

        tag = str(data.get("tag_name") or data.get("name") or "latest").strip()
        published = _parse_datetime(data.get("published_at") or data.get("created_at"))
        assets = data.get("assets") or []
        asset_entry = next(
            (
                asset
                for asset in assets
                if str(asset.get("name") or "").lower().endswith(".zip")
            ),
            None,
        )
        download_url = ""
        asset_name = ""
        if asset_entry:
            download_url = str(asset_entry.get("browser_download_url") or "").strip()
            asset_name = str(asset_entry.get("name") or "").strip()
        if not download_url:
            download_url = str(data.get("zipball_url") or "").strip()
            asset_name = asset_name or f"{tag or 'latest'}.zip"
        if not download_url:
            raise UpdateError("GitHub 发布缺少可下载的 zip 资源")

        return ReleaseInfo(
            tag=tag or "latest",
            published_at=published,
            asset_name=asset_name or "release.zip",
            download_url=download_url,
        )

    def _download_release(self, release: ReleaseInfo, dest_path: Path) -> None:
        try:
            with requests.get(
                release.download_url,
                timeout=60,
                stream=True,
                headers=_ASSET_HEADERS,
            ) as resp:
                resp.raise_for_status()
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                with open(dest_path, "wb") as fp:
                    for chunk in resp.iter_content(chunk_size=512 * 1024):
                        if chunk:
                            fp.write(chunk)
        except requests.RequestException as exc:
            raise UpdateError(f"下载更新包失败：{exc}") from exc

    def _extract_and_copy(self, archive_path: Path) -> None:
        if not archive_path.exists():
            raise UpdateError("更新包不存在或已被清理")
        with tempfile.TemporaryDirectory(prefix="fs-update-extract-") as extract_dir:
            try:
                with zipfile.ZipFile(archive_path, "r") as zf:
                    zf.extractall(extract_dir)
            except zipfile.BadZipFile as exc:
                raise UpdateError(f"更新包损坏：{exc}") from exc
            content_root = self._resolve_content_root(Path(extract_dir))
            self._copy_tree(content_root)

    @staticmethod
    def _resolve_content_root(extracted_root: Path) -> Path:
        markers = ("install_deps.py", "README.md", "lib")
        if any((extracted_root / marker).exists() for marker in markers):
            return extracted_root
        children = [
            child for child in extracted_root.iterdir() if child.name != "__MACOSX"
        ]
        if len(children) == 1 and children[0].is_dir():
            return children[0]
        return extracted_root

    def _copy_tree(self, source_root: Path) -> None:
        for root, dirs, files in os.walk(source_root):
            rel_dir = Path(root).relative_to(source_root)
            if rel_dir != Path(".") and _is_protected_path(rel_dir):
                dirs[:] = []
                continue
            target_dir = (
                _PROJECT_ROOT if rel_dir == Path(".") else _PROJECT_ROOT / rel_dir
            )
            target_dir.mkdir(parents=True, exist_ok=True)
            for file_name in files:
                rel_file = (rel_dir / file_name) if rel_dir != Path(".") else Path(
                    file_name
                )
                if _is_protected_path(rel_file):
                    continue
                src_file = Path(root) / file_name
                dest_file = target_dir / file_name
                shutil.copy2(src_file, dest_file)
