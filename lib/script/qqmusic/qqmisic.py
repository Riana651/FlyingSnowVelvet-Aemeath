"""QQ music API client.

Based on publicly used QQ music endpoints at:
`https://u.y.qq.com/cgi-bin/musicu.fcg`
"""

import json
import html
import random
import re
import time
from typing import Any
from urllib.parse import urlsplit

import requests

from lib.core.logger import get_logger

logger = get_logger(__name__)


class QQmisic:
    """QQ music API wrapper for search / metadata / playable URL."""

    _API_URL = "https://u.y.qq.com/cgi-bin/musicu.fcg"
    _LOGIN_GET_MUSICKEY_URL = "https://c.y.qq.com/base/fcgi-bin/login_get_musickey.fcg"
    _PLAYLIST_LIST_URL = "https://c.y.qq.com/rsc/fcgi-bin/fcg_user_created_diss"
    _PLAYLIST_DETAIL_URL = "https://c.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg"
    _PROFILE_HOMEPAGE_URL = "https://c.y.qq.com/rsc/fcgi-bin/fcg_get_profile_homepage.fcg"
    _LEGACY_MAX_PAGE_SIZE = 30
    _QQ_SEARCH_PAGE_SIZE = 50
    _LIKED_DIRID = 201
    _MUSICU_RETRY_TIMES = 2
    _MUSICU_RETRY_BACKOFF = 0.35
    _PREVIEW_PROBE_TIMEOUT = (4.0, 8.0)

    def __init__(self, timeout: tuple[float, float] = (8.0, 20.0)) -> None:
        self._timeout = timeout
        self._session = requests.Session()
        self._last_vkey_meta: dict[str, Any] = {}
        self._last_liked_meta: dict[str, Any] = {}
        self._session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Referer": "https://y.qq.com/",
                "Origin": "https://y.qq.com",
            }
        )

    @staticmethod
    def _hash33(text: str) -> int:
        val = 5381
        for ch in str(text or ""):
            val += (val << 5) + ord(ch)
        return val & 0x7FFFFFFF

    @staticmethod
    def _normalize_uin(raw_uin: str | None) -> str:
        text = str(raw_uin or "0").strip()
        m = re.search(r"(\d+)", text)
        return m.group(1) if m else "0"

    def _cookie_text(self, *names: str) -> str:
        cookies = self.export_cookies()
        for name in names:
            value = str(cookies.get(name) or "").strip()
            if value:
                return value
        return ""

    def _has_auth_cookie(self) -> bool:
        return bool(
            self._cookie_text(
                "p_skey",
                "skey",
                "qqmusic_key",
                "music_key",
                "qm_keyst",
                "p_lskey",
                "lskey",
                "pt4_token",
            )
        )

    def _musickey_cookie(self) -> str:
        return self._cookie_text("qqmusic_key", "music_key", "qm_keyst", "p_lskey", "lskey")

    def _effective_uin(self, raw_uin: str | None = None) -> str:
        uin = self._normalize_uin(raw_uin or self._uin_from_cookies() or "0")
        if uin == "0":
            return "0"
        # 存在 uin 但缺少关键鉴权 Cookie 时按匿名态处理，
        # 避免“伪登录”导致取流稳定性下降。
        return uin if self._has_auth_cookie() else "0"

    def _uin_candidates(self) -> list[str]:
        """
        取流时的 uin 候选：
        1) 鉴权可信 uin（_effective_uin）
        2) 原始 cookie uin（用于兼容部分 VIP 场景）
        3) 匿名 0（兜底）
        """
        out: list[str] = []
        for candidate in (self._effective_uin(), self._uin_from_cookies(), "0"):
            uin = self._normalize_uin(candidate)
            if uin not in out:
                out.append(uin)
        return out

    def _g_tk(self, use_new: bool = False) -> int:
        # 对齐 QQ Web 端:
        # g_tk_new_20200303: qqmusic_key -> p_skey -> skey -> p_lskey -> lskey
        # g_tk:              skey -> qqmusic_key
        if use_new:
            key = self._cookie_text("qqmusic_key", "p_skey", "skey", "p_lskey", "lskey")
        else:
            key = self._cookie_text("skey", "qqmusic_key")
        if not key:
            return 5381
        return self._hash33(key)

    def _default_comm(self, uin_text: str | None = None) -> dict[str, Any]:
        # comm.uin 对齐 Web：优先使用传入 uin，其次 Cookie 推导，不额外强制降级到 0。
        uin = self._normalize_uin(uin_text or self._uin_from_cookies() or "0")
        return {
            "cv": 4747474,
            "ct": 24,
            "format": "json",
            "inCharset": "utf-8",
            "outCharset": "utf-8",
            "notice": 0,
            "platform": "yqq.json",
            "needNewCode": 1,
            "uin": uin,
            "g_tk_new_20200303": self._g_tk(use_new=True),
            "g_tk": self._g_tk(use_new=False),
        }

    def _ensure_guid(self) -> str:
        guid = self._cookie_text("qqmusic_guid")
        if re.fullmatch(r"\d{6,}", guid):
            return guid
        guid = str(random.randint(1000000000, 4294967295))
        try:
            self._session.cookies.set("qqmusic_guid", guid)
        except Exception:
            pass
        return guid

    def get_last_vkey_meta(self) -> dict[str, Any]:
        return dict(self._last_vkey_meta or {})

    def get_last_liked_meta(self) -> dict[str, Any]:
        return dict(self._last_liked_meta or {})

    def is_logged_in(self) -> bool:
        return self._effective_uin() != "0"

    def get_session(self) -> requests.Session:
        return self._session

    def set_cookies(self, cookies: dict[str, str]) -> None:
        if not isinstance(cookies, dict):
            return
        self._session.cookies.clear()
        for key, value in cookies.items():
            if key and value is not None:
                try:
                    self._session.cookies.set(str(key), str(value))
                except Exception:
                    continue

    def export_cookies(self) -> dict[str, str]:
        try:
            return self._session.cookies.get_dict() or {}
        except Exception:
            return {}

    def _uin_from_cookies(self) -> str:
        cookies = self.export_cookies()
        wxopenid = str(cookies.get("wxopenid") or "").strip()
        # 对齐 Web 端 getUin：微信态优先 wxuin，否则优先 uin，再回退 p_uin。
        preferred_uin = cookies.get("wxuin") if wxopenid else cookies.get("uin")
        raw = str(
            preferred_uin
            or cookies.get("p_uin")
            or cookies.get("ptui_loginuin")
            or cookies.get("qqmusic_uin")
            or "0"
        ).strip()
        m = re.search(r"(\d+)", raw)
        return m.group(1) if m else "0"

    def _post_musicu(self, payload: dict[str, Any]) -> dict[str, Any]:
        req_payload: dict[str, Any] = dict(payload or {})
        comm_raw = req_payload.get("comm")
        if isinstance(comm_raw, dict):
            merged = self._default_comm(uin_text=str(comm_raw.get("uin") or "0"))
            merged.update(comm_raw)
            req_payload["comm"] = merged
        else:
            req_payload["comm"] = self._default_comm()

        resp = self._session.post(
            self._API_URL,
            params={"format": "json"},
            json=req_payload,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {}

    def _post_musicu_with_schedule(self, payload: dict[str, Any], *, context: str = "") -> dict[str, Any]:
        max_attempts = max(1, int(self._MUSICU_RETRY_TIMES or 1))
        retry_backoff = max(0.0, float(self._MUSICU_RETRY_BACKOFF or 0.0))
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return self._post_musicu(payload)
            except requests.HTTPError as e:
                last_error = e
                status = e.response.status_code if e.response is not None else 0
                should_retry = status in (408, 425, 429) or status >= 500
                if should_retry and attempt < max_attempts:
                    logger.warning(
                        "[QQmisic] musicu retry context=%s status=%s attempt=%d/%d",
                        context or "unknown",
                        status,
                        attempt,
                        max_attempts,
                    )
                    if retry_backoff > 0:
                        time.sleep(retry_backoff * attempt)
                    continue
                raise
            except (requests.Timeout, requests.ConnectionError) as e:
                last_error = e
                if attempt < max_attempts:
                    logger.warning(
                        "[QQmisic] musicu network retry context=%s attempt=%d/%d err=%s",
                        context or "unknown",
                        attempt,
                        max_attempts,
                        e,
                    )
                    if retry_backoff > 0:
                        time.sleep(retry_backoff * attempt)
                    continue
                raise
            except Exception as e:
                last_error = e
                if attempt < max_attempts:
                    logger.warning(
                        "[QQmisic] musicu retry context=%s attempt=%d/%d err=%s",
                        context or "unknown",
                        attempt,
                        max_attempts,
                        e,
                    )
                    if retry_backoff > 0:
                        time.sleep(retry_backoff * attempt)
                    continue
                raise
        if last_error is not None:
            raise last_error
        return {}

    def _request_json_text_payload(
        self,
        api_url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any], int]:
        resp = self._session.get(
            api_url,
            params=params,
            headers=headers,
            timeout=self._timeout,
        )
        status_code = int(resp.status_code or 0)
        resp.raise_for_status()
        data = self._parse_json_text(resp.text)
        return data if isinstance(data, dict) else {}, status_code

    def _build_req0_musicu_payload(
        self,
        req_payload: dict[str, Any],
        *,
        uin_text: str,
    ) -> dict[str, Any]:
        req_comm = self._default_comm(uin_text=uin_text)
        return {
            "comm": req_comm,
            "req_0": dict(req_payload or {}),
        }

    def _refresh_musickey(self) -> dict[str, Any]:
        """
        刷新 QQ 播放 key（musickey）。官方 Web 在取流异常时会走该接口。
        """
        uin = self._normalize_uin(self._uin_from_cookies())
        if uin == "0":
            return {"ok": False, "reason": "no_uin"}

        params = {
            "from": "1",
            "force_access": "1",
            "wxopenid": self._cookie_text("wxopenid") or uin,
            "wxrefresh_token": self._cookie_text("wxrefresh_token"),
            "musickey": self._musickey_cookie(),
            "musicuin": uin,
            "get_access_token": 1,
            "ct": 1001,
            "format": "json",
            "inCharset": "utf-8",
            "outCharset": "utf-8",
        }
        try:
            resp = self._session.get(
                self._LOGIN_GET_MUSICKEY_URL,
                params=params,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            try:
                data = resp.json()
            except Exception:
                data = self._parse_json_text(resp.text or "")
        except Exception as e:
            return {"ok": False, "reason": "request_failed", "error": str(e)}

        if not isinstance(data, dict):
            return {"ok": False, "reason": "invalid_response"}

        code = data.get("code")
        # 部分环境 key 通过 Set-Cookie 下发，response body 未必直接带 key。
        body_key = str(
            data.get("musickey")
            or data.get("qqmusic_key")
            or data.get("music_key")
            or data.get("key")
            or ""
        ).strip()
        if body_key:
            try:
                self._session.cookies.set("qqmusic_key", body_key)
            except Exception:
                pass
        cookie_key = self._musickey_cookie()
        ok = str(code) == "0"
        return {
            "ok": ok,
            "code": code,
            "body_key": bool(body_key),
            "cookie_key": bool(cookie_key),
        }

    @staticmethod
    def _parse_json_text(raw_text: str) -> dict[str, Any]:
        text = str(raw_text or "").strip()
        if not text:
            return {}
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except Exception:
            pass
        m = re.search(r"\((\{.*\})\)\s*;?\s*$", text, flags=re.S)
        if not m:
            return {}
        try:
            data = json.loads(m.group(1))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _extract_playlist_items(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
        """Extract playlist list from multiple QQ response layouts."""
        if not isinstance(payload, dict):
            return []
        data = payload.get("data")
        candidates: list[Any] = []
        if isinstance(data, dict):
            candidates.extend(
                data.get(key)
                for key in ("disslist", "list", "dirlist", "playlist", "playlists", "cdlist")
            )
            inner_list = data.get("list")
            if isinstance(inner_list, dict):
                candidates.extend(inner_list.get(key) for key in ("list", "disslist", "dirlist", "playlist"))
        candidates.extend(payload.get(key) for key in ("disslist", "list", "dirlist", "playlist", "playlists"))

        for raw in candidates:
            if isinstance(raw, list):
                out = [x for x in raw if isinstance(x, dict)]
                if out:
                    return out
            elif isinstance(raw, dict):
                for key in ("list", "disslist", "dirlist", "playlist"):
                    value = raw.get(key)
                    if isinstance(value, list):
                        out = [x for x in value if isinstance(x, dict)]
                    if out:
                        return out
        return []

    def _build_musicu_request(
        self,
        *,
        module: str,
        method: str,
        param: dict[str, Any],
        req_key: str = "req_0",
        comm: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request_comm = dict(comm) if isinstance(comm, dict) else {
            "ct": 24,
            "cv": 0,
            "uin": self._uin_from_cookies(),
        }
        return {
            "comm": request_comm,
            req_key: {
                "module": str(module or "").strip(),
                "method": str(method or "").strip(),
                "param": dict(param or {}),
            },
        }

    @staticmethod
    def _extract_musicu_req_data(payload: dict[str, Any] | None, req_key: str = "req_0") -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        req_block = payload.get(req_key)
        if not isinstance(req_block, dict):
            return {}
        req_data = req_block.get("data")
        return req_data if isinstance(req_data, dict) else {}

    @staticmethod
    def _extract_nested_value(container: Any, path: tuple[str, ...]) -> Any:
        current = container
        for key in path:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    @staticmethod
    def _first_non_empty_list(*values: Any) -> list[Any]:
        for value in values:
            if isinstance(value, list) and value:
                return value
        return []

    def _search_musicu_request(
        self,
        *,
        module: str,
        method: str,
        param: dict[str, Any],
        list_paths: tuple[tuple[str, ...], ...],
        req_key: str = "req_0",
        comm: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        data = self._post_musicu(
            self._build_musicu_request(
                module=module,
                method=method,
                param=param,
                req_key=req_key,
                comm=comm,
            )
        )
        req_data = self._extract_musicu_req_data(data, req_key=req_key)
        raw_list = self._first_non_empty_list(
            *(self._extract_nested_value(req_data, path) for path in list_paths)
        )
        return self._normalize_song_list(self._extract_song_items(raw_list))

    def _build_vkey_request_payload(
        self,
        *,
        module: str,
        method: str,
        mid: str,
        song_type: int,
        uin_text: str,
        guid: str,
        filename: str,
        has_ctx: bool,
        ext_params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        req_param: dict[str, Any] = {
            "guid": guid,
            "songmid": [mid],
            "songtype": [song_type],
            "uin": uin_text,
            "loginflag": 1,
            "platform": "20",
            "filename": [filename],
        }
        if has_ctx:
            req_param["ctx"] = 1
        if isinstance(ext_params, dict):
            req_param.update(ext_params)
        req_comm = self._default_comm()
        req_comm["uin"] = uin_text
        return self._build_musicu_request(
            module=module,
            method=method,
            param=req_param,
            comm=req_comm,
        )

    def _build_user_playlist_request_variants(
        self,
        target_uin: str,
        size_value: int,
    ) -> list[tuple[dict[str, Any], dict[str, str]]]:
        base_params = {
            "format": "json",
            "inCharset": "utf8",
            "outCharset": "utf-8",
            "notice": "0",
            "platform": "yqq.json",
            "needNewCode": "0",
            "hostuin": target_uin,
            "sin": 0,
            "size": size_value,
            "rnd": random.random(),
        }
        return [
            (
                dict(base_params),
                {
                    "Referer": f"https://y.qq.com/portal/profile.html?uin={target_uin}",
                    "Origin": "https://y.qq.com",
                },
            ),
            (
                {
                    **base_params,
                    "uin": target_uin,
                    "loginUin": target_uin,
                    "hostUin": target_uin,
                    "ct": 20,
                    "cv": 0,
                    "g_tk": self._g_tk(use_new=False),
                    "g_tk_new_20200303": self._g_tk(use_new=True),
                },
                {
                    "Referer": f"https://y.qq.com/n/ryqq/profile?uin={target_uin}",
                    "Origin": "https://y.qq.com",
                },
            ),
        ]

    def _normalize_playlist_summary(self, item: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        dirid = self._safe_int(item.get("dirid"), 0)
        tid = (
            item.get("tid")
            or item.get("dissid")
            or item.get("disstid")
            or item.get("id")
            or (dirid if dirid > 0 else None)
        )
        try:
            disstid = int(tid)
        except (TypeError, ValueError):
            return None
        name = self._clean_text(
            item.get("diss_name")
            or item.get("dissname")
            or item.get("name")
            or item.get("title")
            or ""
        )
        return {
            "disstid": disstid,
            "dirid": dirid,
            "name": name or str(disstid),
            "song_count": self._safe_int(
                item.get("song_cnt")
                or item.get("songnum")
                or item.get("song_count")
                or item.get("songCount"),
                0,
            ),
            "raw": item,
        }

    def _search_by_musicu_method(
        self,
        keyword: str,
        page_num: int,
        num_per_page: int,
        method: str,
    ) -> list[dict[str, Any]]:
        return self._search_musicu_request(
            module="music.search.SearchCgiService",
            method=method,
            param={
                "query": keyword,
                "search_type": 0,
                "page_num": page_num,
                "num_per_page": num_per_page,
            },
            list_paths=(
                ("body", "song", "list"),
                ("body", "item_song"),
                ("item_song",),
                ("song", "list"),
            ),
        )

    def _search_by_adaptor_v2(
        self,
        keyword: str,
        page_num: int,
        num_per_page: int,
    ) -> list[dict[str, Any]]:
        return self._search_musicu_request(
            module="music.adaptor.SearchAdaptor",
            method="do_search_v2",
            param={
                "query": keyword,
                "search_type": 0,
                "page_num": page_num,
                "num_per_page": num_per_page,
            },
            list_paths=(
                ("body", "item_song"),
                ("item_song",),
                ("body", "song", "list"),
                ("song", "list"),
            ),
        )

    def _search_by_searchcgi_desktop(
        self,
        keyword: str,
        page_num: int,
        num_per_page: int,
    ) -> list[dict[str, Any]]:
        """
        QQ SearchCgiService 标准调用（2025/2026 实测可返回 >10 且支持分页）。
        """
        return self._search_musicu_request(
            module="music.search.SearchCgiService",
            method="DoSearchForQQMusicDesktop",
            param={
                "grp": 1,
                "num_per_page": max(1, int(num_per_page or 1)),
                "page_num": max(1, int(page_num or 1)),
                "query": str(keyword or ""),
                "search_type": 0,
            },
            req_key="req",
            comm={
                "ct": "19",
                "cv": "1859",
                "uin": self._uin_from_cookies(),
            },
            list_paths=(("body", "song", "list"),),
        )

    def _search_by_legacy_endpoint(
        self,
        keyword: str,
        page_num: int,
        num_per_page: int,
    ) -> list[dict[str, Any]]:
        # legacy 接口稳定性较差，请求过大时易 5xx。
        request_size = max(1, min(self._LEGACY_MAX_PAGE_SIZE, int(num_per_page or 1)))
        params = {
            "ct": "24",
            "qqmusic_ver": "1298",
            "new_json": "1",
            "remoteplace": "txt.yqq.song",
            "searchid": "",
            "t": "0",
            "aggr": "1",
            "cr": "1",
            "catZhida": "1",
            "lossless": "0",
            "flag_qc": "0",
            "p": str(max(1, page_num)),
            "n": str(request_size),
            "w": keyword,
            "g_tk": "5381",
            "loginUin": self._uin_from_cookies(),
            "hostUin": self._uin_from_cookies(),
            "format": "json",
            "inCharset": "utf8",
            "outCharset": "utf-8",
            "notice": "0",
            "platform": "yqq.json",
            "needNewCode": "0",
        }
        resp = self._session.get(
            "https://c.y.qq.com/soso/fcgi-bin/client_search_cp",
            params=params,
            timeout=self._timeout,
        )
        if int(resp.status_code or 0) >= 500:
            return []
        resp.raise_for_status()
        try:
            data = resp.json()
        except Exception:
            return []
        raw_list = (((data.get("data") or {}).get("song") or {}).get("list") or [])
        return self._normalize_song_list(raw_list)

    def _search_by_smartbox(self, keyword: str) -> list[dict[str, Any]]:
        resp = self._session.get(
            "https://c.y.qq.com/splcloud/fcgi-bin/smartbox_new.fcg",
            params={
                "is_xml": "0",
                "format": "json",
                "key": keyword,
            },
            headers={
                "Referer": "https://y.qq.com/",
                "User-Agent": self._session.headers.get("User-Agent", "Mozilla/5.0"),
            },
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        items = ((((data.get("data") or {}).get("song") or {}).get("itemlist")) or [])
        songs: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            mid = str(item.get("mid") or "").strip()
            if not mid:
                continue
            title = self._clean_text(item.get("name")) or "未知歌曲"
            artist = self._clean_text(item.get("singer")) or "未知作者"
            songs.append(
                {
                    "id": self._safe_int(item.get("id"), 0),
                    "mid": mid,
                    "title": title,
                    "artist": artist,
                    "duration_ms": None,
                    "raw": item,
                }
            )
        return songs

    def _normalize_song_list(self, raw_list: list[Any]) -> list[dict[str, Any]]:
        songs: list[dict[str, Any]] = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            song = item
            for key in ("songInfo", "songinfo", "track_info"):
                nested = song.get(key)
                if isinstance(nested, dict):
                    song = nested
                    break

            song_id = self._safe_int(song.get("id") or song.get("songid"), 0)
            song_mid = str(song.get("mid") or song.get("songmid") or song.get("songMid") or "").strip()
            if not song_mid:
                continue
            file_info = song.get("file") if isinstance(song.get("file"), dict) else {}
            media_mid = str(file_info.get("media_mid") or song.get("media_mid") or song_mid).strip() or song_mid
            title = self._clean_text(song.get("name") or song.get("title") or song.get("songname")) or "未知歌曲"
            duration_sec = self._safe_int(song.get("interval") or song.get("duration"), 0)
            songs.append(
                {
                    "id": song_id,
                    "mid": song_mid,
                    "media_mid": media_mid,
                    "title": title,
                    "artist": self._extract_artist(song),
                    "duration_ms": duration_sec * 1000 if duration_sec > 0 else None,
                    "raw": song,
                }
            )
        return songs

    @staticmethod
    def _extract_song_items(raw_items: Any) -> list[dict[str, Any]]:
        if isinstance(raw_items, list):
            return [x for x in raw_items if isinstance(x, dict)]
        if not isinstance(raw_items, dict):
            return []

        # SearchAdaptor.do_search_v2: item_song 是 dict，真实歌曲在 item_song.items。
        direct_items = raw_items.get("items")
        if isinstance(direct_items, list):
            return [x for x in direct_items if isinstance(x, dict)]
        if isinstance(direct_items, dict):
            return [x for x in direct_items.values() if isinstance(x, dict)]

        # 兼容其他返回形态：尝试从各 key 中提取 song-like dict/list。
        songs: list[dict[str, Any]] = []
        for value in raw_items.values():
            if isinstance(value, list):
                songs.extend(x for x in value if isinstance(x, dict))
                continue
            if not isinstance(value, dict):
                continue
            if any(k in value for k in ("mid", "songmid", "name", "title", "id", "songid")):
                songs.append(value)
        return songs

    @staticmethod
    def _extract_artist(song: dict[str, Any]) -> str:
        singers = song.get("singer") or song.get("singers") or []
        names: list[str] = []
        for item in singers:
            if isinstance(item, dict):
                name = QQmisic._clean_text(item.get("name"))
            else:
                name = QQmisic._clean_text(item)
            if name:
                names.append(name)
        if not names:
            return "未知作者"
        return "、".join(names)

    @staticmethod
    def _clean_text(raw: Any) -> str:
        text = str(raw or "").strip()
        if not text:
            return ""
        # 某些搜索接口会返回 <em> 高亮标签，这里统一清理为纯文本。
        text = re.sub(r"<[^>]+>", "", text)
        text = html.unescape(text)
        return text.strip()

    @staticmethod
    def _merge_song_lists(*lists: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        max_count = max(1, int(limit or 1))
        for songs in lists:
            for song in songs:
                if not isinstance(song, dict):
                    continue
                mid = str(song.get("mid") or "").strip()
                if not mid or mid in seen:
                    continue
                seen.add(mid)
                merged.append(song)
                if len(merged) >= max_count:
                    return merged
        return merged

    @staticmethod
    def _append_unique_songs(
        target: list[dict[str, Any]],
        seen_mids: set[str],
        source: list[dict[str, Any]],
        limit: int,
    ) -> int:
        """Append songs by unique mid, return added count."""
        added = 0
        max_count = max(1, int(limit or 1))
        for song in source:
            if not isinstance(song, dict):
                continue
            mid = str(song.get("mid") or "").strip()
            if not mid or mid in seen_mids:
                continue
            seen_mids.add(mid)
            target.append(song)
            added += 1
            if len(target) >= max_count:
                break
        return added

    @staticmethod
    def _safe_int(raw, default: int = 0) -> int:
        try:
            return int(raw)
        except Exception:
            return default

    def search_song(self, keyword: str, page_num: int = 1, num_per_page: int = 20) -> list[dict[str, Any]]:
        """Search songs by keyword."""
        query = str(keyword or "").strip()
        if not query:
            return []
        page_num = max(1, int(page_num or 1))
        limit = max(1, int(num_per_page or 20))

        # 主路径：SearchCgiService（支持大于 10 条与分页）
        # 兜底：SearchAdaptor / legacy / smartbox。
        page_size = min(self._QQ_SEARCH_PAGE_SIZE, limit)
        max_pages = max(1, min(12, (limit + page_size - 1) // page_size + 1))
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()

        # 先保留 adaptor 首屏结果，兼顾排序体验。
        try:
            songs = self._search_by_adaptor_v2(query, page_num, min(20, page_size))
            self._append_unique_songs(merged, seen, songs, limit=limit)
        except Exception as e:
            logger.debug("[QQmisic] search adaptor_v2 failed page=%s: %s", page_num, e)

        for idx in range(max_pages):
            cur_page = page_num + idx
            try:
                songs = self._search_by_searchcgi_desktop(query, cur_page, page_size)
            except Exception as e:
                logger.debug("[QQmisic] search SearchCgiService failed page=%s: %s", cur_page, e)
                songs = []

            added = self._append_unique_songs(merged, seen, songs, limit=limit)
            if len(merged) >= limit:
                return merged[:limit]

            # 当前页拿不到新结果，说明已触底。
            if idx > 0 and (not songs or added == 0):
                break

        # Adaptor 不足时再补其他接口（同样受统一 limit 约束）。
        try:
            songs = self._search_by_musicu_method(query, page_num, limit, "DoSearchForQQMusicMobile")
            self._append_unique_songs(merged, seen, songs, limit=limit)
        except Exception as e:
            logger.debug("[QQmisic] search method=DoSearchForQQMusicMobile failed: %s", e)
        if len(merged) >= limit:
            return merged[:limit]

        try:
            songs = self._search_by_musicu_method(query, page_num, limit, "DoSearchForQQMusicDesktop")
            self._append_unique_songs(merged, seen, songs, limit=limit)
        except Exception as e:
            logger.debug("[QQmisic] search method=DoSearchForQQMusicDesktop failed: %s", e)
        if len(merged) >= limit:
            return merged[:limit]

        try:
            songs = self._search_by_legacy_endpoint(query, page_num, limit)
            self._append_unique_songs(merged, seen, songs, limit=limit)
        except Exception as e:
            logger.debug("[QQmisic] legacy search failed: %s", e)
        if len(merged) >= limit:
            return merged[:limit]

        try:
            songs = self._search_by_smartbox(query)
            self._append_unique_songs(merged, seen, songs, limit=limit)
        except Exception as e:
            logger.debug("[QQmisic] smartbox search failed: %s", e)

        return merged[:limit]

    def get_song_detail(self, song_mid: str | None = None) -> dict[str, Any] | None:
        """Get one song metadata by song mid."""
        mid = str(song_mid or "").strip()
        if not mid:
            return None
        try:
            data = self._post_musicu(
                self._build_musicu_request(
                    module="music.pf_song_detail_svr",
                    method="get_song_detail_yqq",
                    param={
                        "song_mid": mid,
                        "song_type": 0,
                    },
                )
            )
        except Exception:
            data = {}

        req_data = self._extract_musicu_req_data(data)
        track = self._extract_nested_value(req_data, ("track_info",)) or self._extract_nested_value(req_data, ("songinfo",)) or {}
        if not isinstance(track, dict) or not track:
            # Fallback: use search result first item
            songs = self.search_song(mid, page_num=1, num_per_page=1)
            return songs[0] if songs else None

        title = str(track.get("name") or track.get("title") or "未知歌曲").strip() or "未知歌曲"
        song_id = self._safe_int(track.get("id") or track.get("songid"), 0)
        interval = self._safe_int(track.get("interval") or track.get("duration"), 0)
        file_info = track.get("file") if isinstance(track.get("file"), dict) else {}
        media_mid = str(file_info.get("media_mid") or track.get("media_mid") or mid).strip() or mid
        return {
            "id": song_id,
            "mid": mid,
            "media_mid": media_mid,
            "title": title,
            "artist": self._extract_artist(track),
            "duration_ms": interval * 1000 if interval > 0 else None,
            "raw": track,
        }

    @staticmethod
    def _filename_ladder(media_mid: str) -> list[str]:
        # Order: prefer full-length resources first.
        # RS01/RS02 are commonly preview clips (e.g. ~60s), keep as last resort.
        key = str(media_mid or "").strip()
        if not key:
            return []
        return [
            f"F000{key}.flac",
            f"A000{key}.ape",
            f"O600{key}.ogg",
            f"M800{key}.mp3",
            f"M500{key}.mp3",
            f"C400{key}.m4a",
            f"RS01{key}.flac",
            f"RS02{key}.mp3",
        ]

    @staticmethod
    def _is_preview_filename(filename: str) -> bool:
        text = str(filename or "").strip().upper()
        return text.startswith("RS01") or text.startswith("RS02")

    @staticmethod
    def _resource_filename_from_url(url_text: str) -> str:
        text = str(url_text or "").strip()
        if not text:
            return ""
        try:
            path = urlsplit(text).path
        except Exception:
            path = text.split("?", 1)[0]
        return str(path.rsplit("/", 1)[-1] or "").strip()

    @classmethod
    def _is_preview_resource(cls, filename: str = "", url_text: str = "") -> bool:
        if cls._is_preview_filename(filename):
            return True
        url_filename = cls._resource_filename_from_url(url_text)
        return cls._is_preview_filename(url_filename)

    @staticmethod
    def _pick_media_mid(song: dict[str, Any] | None, fallback_mid: str) -> str:
        if not isinstance(song, dict):
            return fallback_mid
        direct = str(song.get("media_mid") or "").strip()
        if direct:
            return direct
        raw = song.get("raw")
        if isinstance(raw, dict):
            file_info = raw.get("file") if isinstance(raw.get("file"), dict) else {}
            raw_mid = str(file_info.get("media_mid") or raw.get("media_mid") or "").strip()
            if raw_mid:
                return raw_mid
        return fallback_mid

    @staticmethod
    def _split_track_mid(track_ref: str) -> tuple[str, str]:
        """
        兼容:
        - mid
        - qq:mid
        - mid:media_mid
        - qq:mid:media_mid
        """
        text = str(track_ref or "").strip()
        if text.lower().startswith("qq:"):
            text = text.split(":", 1)[1].strip()
        if not text:
            return "", ""
        parts = text.split(":")
        mid = str(parts[0] or "").strip()
        media_mid = str(parts[1] or "").strip() if len(parts) >= 2 else ""
        return mid, media_mid

    @staticmethod
    def _normalize_remote_url(url_text: str, sip_list: list[Any] | None = None) -> str:
        text = str(url_text or "").strip()
        if not text:
            return ""
        if text.startswith("//"):
            return f"https:{text}"
        if text.startswith("http://") or text.startswith("https://"):
            return text
        if isinstance(sip_list, list):
            for sip in sip_list:
                prefix = str(sip or "").strip()
                if not prefix:
                    continue
                return f"{prefix.rstrip('/')}/{text.lstrip('/')}"
        return ""

    def _probe_stream_url(self, url: str) -> bool:
        text = str(url or "").strip()
        if not text:
            return False
        resp = None
        try:
            resp = self._session.get(
                text,
                headers={
                    "Range": "bytes=0-1",
                    "Referer": "https://y.qq.com/",
                    "User-Agent": str(self._session.headers.get("User-Agent") or "Mozilla/5.0"),
                },
                stream=True,
                timeout=self._PREVIEW_PROBE_TIMEOUT,
            )
            status = int(resp.status_code or 0)
            return status in (200, 206, 301, 302, 303, 307, 308, 416)
        except Exception as e:
            logger.debug("[QQmisic] stream probe failed url=%s: %s", text, e)
            return False
        finally:
            try:
                if resp is not None:
                    resp.close()
            except Exception:
                pass

    def get_song_url(self, song_mid: str, media_mid: str | None = None) -> str | None:
        """Get a playable URL for a song mid."""
        self._last_vkey_meta = {}
        cookie_uin = self._normalize_uin(self._uin_from_cookies() or "0")
        has_login_uin = cookie_uin != "0"
        auth_snapshot = {
            "uin_cookie": cookie_uin,
            "has_qqmusic_key": bool(self._cookie_text("qqmusic_key")),
            "has_music_key": bool(self._cookie_text("music_key")),
            "has_p_skey": bool(self._cookie_text("p_skey")),
            "has_skey": bool(self._cookie_text("skey")),
            "has_pt4_token": bool(self._cookie_text("pt4_token")),
            "has_auth_cookie": self._has_auth_cookie(),
        }
        prefer_full_track = bool(has_login_uin and auth_snapshot.get("has_auth_cookie"))
        mid, parsed_media_mid = self._split_track_mid(str(song_mid or ""))
        if not mid:
            return None

        detail = self.get_song_detail(mid) or {}
        media_candidate = str(media_mid or "").strip() or parsed_media_mid
        if not media_candidate:
            media_candidate = self._pick_media_mid(detail, fallback_mid=mid)

        song_type = self._safe_int((detail.get("raw") or {}).get("type"), 0)
        if song_type < 0:
            song_type = 0

        media_pool: list[str] = []
        for candidate in (media_candidate, mid):
            text = str(candidate or "").strip()
            if text and text not in media_pool:
                media_pool.append(text)

        guid = self._ensure_guid()
        request_specs = (
            ("music.vkey.GetEVkey", "GetUrl", {"xcdn": 1}),
            ("music.vkey.GetVkey", "UrlGetVkey", {}),
            ("vkey.GetVkeyServer", "CgiGetVkey", {}),
            ("music.vkey.GetEDownUrl", "CgiGetEDownUrl", {}),
        )
        detail_raw = detail.get("raw") if isinstance(detail.get("raw"), dict) else {}
        has_ctx = bool((detail_raw or {}).get("ctx"))
        last_result = None
        last_code = None
        refresh_attempted = False
        refresh_meta: dict[str, Any] = {}
        should_refresh_musickey = False
        tried_uins_all: list[str] = []
        preview_url = ""
        preview_filename = ""
        preview_uin = ""
        preview_result = None
        preview_code = None
        preview_module = ""
        preview_method = ""
        preview_candidates: list[str] = []

        for _round in range(2):
            uin_candidates = self._uin_candidates()
            for uin_text in uin_candidates:
                if uin_text not in tried_uins_all:
                    tried_uins_all.append(uin_text)
                for media_key in media_pool:
                    for filename in self._filename_ladder(media_key):
                        for module, method, ext_params in request_specs:
                            payload = self._build_vkey_request_payload(
                                module=module,
                                method=method,
                                mid=mid,
                                song_type=song_type,
                                uin_text=uin_text,
                                guid=guid,
                                filename=filename,
                                has_ctx=has_ctx,
                                ext_params=ext_params,
                            )
                            try:
                                data = self._post_musicu_with_schedule(
                                    payload,
                                    context=f"vkey:{module}:{method}:{mid}:{filename}:{uin_text}",
                                )
                            except Exception as e:
                                logger.debug(
                                    "[QQmisic] vkey request failed module=%s method=%s mid=%s filename=%s uin=%s err=%s",
                                    module,
                                    method,
                                    mid,
                                    filename,
                                    uin_text,
                                    e,
                                )
                                continue

                            req_data = self._extract_musicu_req_data(data)
                            infos_raw = req_data.get("midurlinfo") or []
                            if isinstance(infos_raw, dict):
                                infos = [infos_raw]
                            elif isinstance(infos_raw, list):
                                infos = [x for x in infos_raw if isinstance(x, dict)]
                            else:
                                infos = []
                            if not infos:
                                infos = [{}]
                            sips = req_data.get("sip") or []
                            thirdip = req_data.get("thirdip") or []
                            last_code = req_data.get("code")
                            if last_code is None:
                                last_code = (data.get("req_0") or {}).get("code")
                            if last_code is None:
                                last_code = data.get("code")
                            for info in infos:
                                if not isinstance(info, dict):
                                    continue
                                last_result = info.get("result")
                                out_filename = str(info.get("filename") or filename).strip()

                                purl = self._normalize_remote_url(str(info.get("purl") or ""), sips)
                                if purl:
                                    if not self._is_preview_resource(out_filename or filename, purl):
                                        self._last_vkey_meta = {
                                            "ok": True,
                                            "module": module,
                                            "method": method,
                                            "code": last_code,
                                            "result": last_result,
                                            "mid": mid,
                                            "filename": out_filename or filename,
                                            "uin": uin_text,
                                            "logged_in": self.is_logged_in(),
                                            "auth_snapshot": auth_snapshot,
                                        }
                                        return purl
                                    if purl not in preview_candidates:
                                        preview_candidates.append(purl)
                                    if not preview_url:
                                        preview_url = purl
                                        preview_filename = out_filename or filename
                                        preview_uin = uin_text
                                        preview_result = last_result
                                        preview_code = last_code
                                        preview_module = module
                                        preview_method = method

                                # Web 端新响应偶尔会直接返回可播 URL 字段。
                                for key in (
                                    "xcdnurl",
                                    "wifiurl",
                                    "flowurl",
                                    "opi192kurl",
                                    "opi192koggurl",
                                    "opiflackurl",
                                    "opi128kurl",
                                    "opi96kurl",
                                    "opi48kurl",
                                ):
                                    direct_url = self._normalize_remote_url(str(info.get(key) or ""), sips)
                                    if not direct_url:
                                        continue
                                    if not self._is_preview_resource(out_filename or filename, direct_url):
                                        self._last_vkey_meta = {
                                            "ok": True,
                                            "module": module,
                                            "method": method,
                                            "code": last_code,
                                            "result": last_result,
                                            "mid": mid,
                                            "filename": out_filename or filename,
                                            "uin": uin_text,
                                            "logged_in": self.is_logged_in(),
                                            "auth_snapshot": auth_snapshot,
                                        }
                                        return direct_url
                                    if direct_url not in preview_candidates:
                                        preview_candidates.append(direct_url)
                                    if not preview_url:
                                        preview_url = direct_url
                                        preview_filename = out_filename or filename
                                        preview_uin = uin_text
                                        preview_result = last_result
                                        preview_code = last_code
                                        preview_module = module
                                        preview_method = method

                                vkey = str(info.get("vkey") or "").strip()
                                if vkey and out_filename:
                                    host_prefix = ""
                                    prefixes: list[Any] = []
                                    if isinstance(sips, list):
                                        prefixes.extend(sips)
                                    if isinstance(thirdip, list):
                                        prefixes.extend(thirdip)
                                    for prefix in prefixes:
                                        text = str(prefix or "").strip()
                                        if not text:
                                            continue
                                        host_prefix = text
                                        break
                                    if host_prefix and not host_prefix.startswith("http"):
                                        host_prefix = f"https:{host_prefix}" if host_prefix.startswith("//") else f"https://{host_prefix.lstrip('/')}"
                                    base = host_prefix.rstrip("/") if host_prefix else "https://ws6.stream.qqmusic.qq.com"
                                    candidate_url = (
                                        f"{base}/{out_filename}"
                                        f"?guid={guid}&vkey={vkey}&uin={uin_text}&fromtag=66"
                                    )
                                    if not self._is_preview_resource(out_filename, candidate_url):
                                        self._last_vkey_meta = {
                                            "ok": True,
                                            "module": module,
                                            "method": method,
                                            "code": last_code,
                                            "result": last_result,
                                            "mid": mid,
                                            "filename": out_filename,
                                            "uin": uin_text,
                                            "logged_in": self.is_logged_in(),
                                            "auth_snapshot": auth_snapshot,
                                        }
                                        return candidate_url
                                    if candidate_url not in preview_candidates:
                                        preview_candidates.append(candidate_url)
                                    if not preview_url:
                                        preview_url = candidate_url
                                        preview_filename = out_filename
                                        preview_uin = uin_text
                                        preview_result = last_result
                                        preview_code = last_code
                                        preview_module = module
                                        preview_method = method

                                # 已登录命中常见权限码时，先刷新 musickey 再重试。
                                if uin_text != "0":
                                    code_text = str(last_code or "").strip()
                                    result_text = str(last_result or "").strip()
                                    if (
                                        result_text in {"104003", "20001", "100001", "1000"}
                                        or code_text in {"1000", "20001"}
                                    ):
                                        should_refresh_musickey = True

            if has_login_uin and preview_candidates and not refresh_attempted:
                should_refresh_musickey = True

            if should_refresh_musickey and not refresh_attempted:
                refresh_attempted = True
                refresh_meta = self._refresh_musickey()
                logger.info(
                    "[QQmisic] musickey refresh attempted mid=%s ok=%s code=%s cookie_key=%s",
                    mid,
                    bool(refresh_meta.get("ok")),
                    refresh_meta.get("code"),
                    refresh_meta.get("cookie_key"),
                )
                if refresh_meta.get("ok"):
                    should_refresh_musickey = False
                    preview_url = ""
                    preview_filename = ""
                    preview_uin = ""
                    preview_result = None
                    preview_code = None
                    preview_module = ""
                    preview_method = ""
                    preview_candidates = []
                    continue
            break
        if preview_candidates:
            if prefer_full_track:
                self._last_vkey_meta = {
                    "ok": False,
                    "preview_only": True,
                    "preview_blocked": True,
                    "module": preview_module or "unknown",
                    "method": preview_method or "unknown",
                    "code": preview_code,
                    "result": preview_result,
                    "mid": mid,
                    "filename": preview_filename,
                    "uin": preview_uin or cookie_uin,
                    "tried_uins": tried_uins_all or self._uin_candidates(),
                    "logged_in": self.is_logged_in(),
                    "musickey_refresh": refresh_meta,
                    "preview_candidates": len(preview_candidates),
                    "auth_snapshot": auth_snapshot,
                }
                logger.info(
                    "[QQmisic] get_song_url blocked preview-only result mid=%s code=%s result=%s filename=%s",
                    mid,
                    preview_code,
                    preview_result,
                    preview_filename,
                )
                return None

            for candidate in preview_candidates:
                if not self._probe_stream_url(candidate):
                    continue
                self._last_vkey_meta = {
                    "ok": True,
                    "preview_only": True,
                    "module": preview_module or "unknown",
                    "method": preview_method or "unknown",
                    "code": preview_code,
                    "result": preview_result,
                    "mid": mid,
                    "filename": preview_filename,
                    "uin": preview_uin,
                    "logged_in": self.is_logged_in(),
                    "musickey_refresh": refresh_meta,
                    "preview_candidates": len(preview_candidates),
                    "preview_probe_ok": True,
                    "auth_snapshot": auth_snapshot,
                }
                logger.info(
                    "[QQmisic] get_song_url fallback preview mid=%s code=%s result=%s filename=%s",
                    mid,
                    preview_code,
                    preview_result,
                    preview_filename,
                )
                return candidate

            self._last_vkey_meta = {
                "ok": False,
                "preview_only": True,
                "preview_unavailable": True,
                "module": preview_module or "unknown",
                "method": preview_method or "unknown",
                "code": preview_code,
                "result": preview_result,
                "mid": mid,
                "filename": preview_filename,
                "uin": preview_uin,
                "tried_uins": tried_uins_all or self._uin_candidates(),
                "logged_in": self.is_logged_in(),
                "musickey_refresh": refresh_meta,
                "preview_candidates": len(preview_candidates),
                "preview_probe_ok": False,
                "auth_snapshot": auth_snapshot,
            }
            logger.info(
                "[QQmisic] get_song_url preview unavailable mid=%s code=%s result=%s candidates=%s",
                mid,
                preview_code,
                preview_result,
                len(preview_candidates),
            )
            return None
        self._last_vkey_meta = {
            "ok": False,
            "code": last_code,
            "result": last_result,
            "mid": mid,
            "tried_uins": tried_uins_all or self._uin_candidates(),
            "logged_in": self.is_logged_in(),
            "musickey_refresh": refresh_meta,
            "auth_snapshot": auth_snapshot,
        }
        logger.info(
            "[QQmisic] get_song_url miss mid=%s logged_in=%s code=%s result=%s",
            mid,
            self.is_logged_in(),
            last_code,
            last_result,
        )
        return None

    def get_user_playlists(self, uin: str | int | None = None, size: int = 128) -> list[dict[str, Any]]:
        """Get user-created playlists by uin."""
        target_uin = str(uin or self._uin_from_cookies()).strip()
        if not target_uin or target_uin == "0":
            return []
        size_value = max(1, min(512, int(size or 128)))
        request_variants = self._build_user_playlist_request_variants(target_uin, size_value)
        playlists: list[dict[str, Any]] = []
        for params, headers in request_variants:
            try:
                data, _ = self._request_json_text_payload(
                    self._PLAYLIST_LIST_URL,
                    params=params,
                    headers=headers,
                )
                playlists = self._extract_playlist_items(data)
            except Exception:
                playlists = []
            if playlists:
                break
        out: list[dict[str, Any]] = []
        for item in playlists:
            normalized = self._normalize_playlist_summary(item)
            if normalized:
                out.append(normalized)
        return out

    def _resolve_myfav_dissid(self, uin: str | int | None = None) -> tuple[int, dict[str, Any]]:
        """
        ?? QQ ?? profile/like/song ???
        ?? fcg_get_profile_homepage.fcg ? data.mymusic[type=1].id ?? myFavDissId?
        """
        target_uin = self._normalize_uin(str(uin or self._uin_from_cookies() or "0"))
        if target_uin == "0":
            return 0, {"ok": False, "reason": "no_uin"}

        login_uin = self._normalize_uin(self._uin_from_cookies() or target_uin)
        base_params = {
            "format": "json",
            "inCharset": "utf8",
            "outCharset": "utf-8",
            "notice": "0",
            "platform": "yqq.json",
            "needNewCode": "0",
            "cid": 205360838,
            "ct": 24,
            "userid": target_uin,
            "reqfrom": 1,
            "reqtype": 0,
            "hostUin": 0,
            "loginUin": login_uin if login_uin != "0" else target_uin,
        }
        request_variants: list[tuple[dict[str, Any], dict[str, str], str]] = [
            (
                dict(base_params),
                {
                    "Referer": f"https://y.qq.com/n/ryqq/profile/{target_uin}",
                    "Origin": "https://y.qq.com",
                },
                "userid_target",
            ),
            (
                {**base_params, "userid": 0},
                {
                    "Referer": "https://y.qq.com/n/ryqq/profile",
                    "Origin": "https://y.qq.com",
                },
                "userid_0",
            ),
        ]
        tried: list[dict[str, Any]] = []

        for params, headers, variant in request_variants:
            try:
                data, status_code = self._request_json_text_payload(
                    self._PROFILE_HOMEPAGE_URL,
                    params=params,
                    headers=headers,
                )
            except Exception as e:
                tried.append({"variant": variant, "error": str(e)})
                continue

            payload_data = data.get("data") if isinstance(data.get("data"), dict) else {}
            code = self._safe_int(data.get("code"), -1)
            mymusic = payload_data.get("mymusic")
            found = 0
            if isinstance(mymusic, list):
                for item in mymusic:
                    if not isinstance(item, dict):
                        continue
                    if self._safe_int(item.get("type"), 0) != 1:
                        continue
                    found = self._safe_int(item.get("id") or item.get("dissid") or item.get("tid"), 0)
                    if found > 0:
                        break
            tried.append(
                {
                    "variant": variant,
                    "status": status_code,
                    "code": code,
                    "mymusic_count": len(mymusic) if isinstance(mymusic, list) else 0,
                    "found": found,
                }
            )
            if found > 0:
                return found, {
                    "ok": True,
                    "reason": "profile_homepage_mymusic_type_1",
                    "myfav_dissid": found,
                    "uin": target_uin,
                    "tried": tried,
                }

        return 0, {
            "ok": False,
            "reason": "profile_homepage_mymusic_missing",
            "uin": target_uin,
            "tried": tried,
        }

    @staticmethod
    def _liked_playlist_score(item: dict[str, Any]) -> int:
        if not isinstance(item, dict):
            return -1
        score = 0
        matched_by: set[str] = set()
        try:
            dirid = int(item.get("dirid") or 0)
        except Exception:
            dirid = 0
        if dirid == QQmisic._LIKED_DIRID:
            score += 500
            matched_by.add("dirid_201")
        name = str(item.get("name") or "").strip().lower()
        if name:
            if name in {"我喜欢的音乐", "我喜欢", "喜欢的音乐", "liked songs", "my liked songs"}:
                score += 220
                matched_by.add("name_exact")
            elif "我喜欢" in name or "liked songs" in name:
                score += 170
                matched_by.add("name_contains")
        raw = item.get("raw")
        if isinstance(raw, dict):
            # 兼容不同接口字段。
            if str(raw.get("is_liked") or raw.get("isLike") or "").strip() in {"1", "true", "True"}:
                score += 320
                matched_by.add("is_liked")
            try:
                if int(raw.get("specialType") or raw.get("special_type") or 0) == 5:
                    score += 300
                    matched_by.add("special_type")
            except Exception:
                pass
            try:
                if int(raw.get("dir_show") or raw.get("dirShow") or -1) == 0:
                    score += 60
                    matched_by.add("dir_show_0")
            except Exception:
                pass
        try:
            song_count = int(item.get("song_count") or 0)
        except Exception:
            song_count = 0
        if song_count > 0:
            score += min(30, song_count // 3 + 5)
        if matched_by:
            item["_liked_match"] = ",".join(sorted(matched_by))
        return score

    @classmethod
    def _preferred_playlists(cls, playlists: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not isinstance(playlists, list):
            return []
        return sorted(
            [x for x in playlists if isinstance(x, dict)],
            key=lambda x: (
                cls._liked_playlist_score(x),
                cls._safe_int(x.get("song_count"), 0),
            ),
            reverse=True,
        )

    @classmethod
    def _is_strong_liked_playlist(cls, item: dict[str, Any]) -> bool:
        """高置信度“我喜欢”歌单判定，避免误选任意收藏/自建歌单。"""
        if not isinstance(item, dict):
            return False
        score = cls._liked_playlist_score(item)
        # 200+ 代表命中官方标记或明确“我喜欢”名称。
        return score >= 200

    @staticmethod
    def _song_payload_from_item(item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        song = item
        for key in ("songInfo", "songinfo", "track_info"):
            nested = song.get(key)
            if isinstance(nested, dict):
                song = nested
                break

        mid = str(song.get("songmid") or song.get("songMid") or song.get("mid") or "").strip()
        if not mid:
            return None

        # 避免把“歌单条目/归属信息”误判为歌曲。
        playlist_like = any(
            key in song for key in ("dissid", "dirid", "tid", "dissname", "diss_name", "encrypt_uin")
        )
        song_like = any(
            key in song for key in ("songid", "songmid", "songMid", "singer", "interval", "file", "album", "mv", "pay")
        )
        if playlist_like and not song_like:
            return None
        return song

    def _filter_playlist_song_items(self, raw_items: Any) -> list[dict[str, Any]]:
        items = self._extract_song_items(raw_items)
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            song = self._song_payload_from_item(item)
            if not isinstance(song, dict):
                continue
            mid = str(song.get("songmid") or song.get("songMid") or song.get("mid") or "").strip()
            if not mid or mid in seen:
                continue
            seen.add(mid)
            out.append(song)
        return out

    def _extract_playlist_tracks(self, payload: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        candidates: list[Any] = []

        def _collect(container: Any) -> None:
            if not isinstance(container, dict):
                return
            candidates.extend(container.get(key) for key in ("songlist", "song_list", "songList", "songs"))
            cdlist = container.get("cdlist")
            if isinstance(cdlist, list):
                for cd in cdlist:
                    if isinstance(cd, dict):
                        candidates.extend(cd.get(key) for key in ("songlist", "song_list", "songList", "songs"))

            # 部分接口会把歌曲放在 list；但也有 list=歌单归属列表，需严格过滤。
            maybe_list = container.get("list")
            if isinstance(maybe_list, list):
                candidates.append(maybe_list)
            elif isinstance(maybe_list, dict):
                candidates.extend(maybe_list.get(key) for key in ("list", "songlist", "song_list", "songList"))

        _collect(payload)
        data = payload.get("data")
        _collect(data)
        for key in ("req", "req_0", "req1", "cgi"):
            req_block = payload.get(key)
            if isinstance(req_block, dict):
                _collect(req_block)
                _collect(req_block.get("data"))

        for raw in candidates:
            items = self._filter_playlist_song_items(raw)
            if items:
                return items
        return []

    def _build_playlist_legacy_params(
        self,
        *,
        tid: int | None,
        did: int | None,
        uin_text: str,
        ctx_value: int,
        song_num: int,
    ) -> dict[str, Any]:
        legacy_params = {
            "type": 1,
            "json": 1,
            "utf8": 1,
            "onlysong": 0,
            "new_format": 1,
            "song_begin": 0,
            "song_num": song_num,
            "format": "json",
            "inCharset": "utf8",
            "outCharset": "utf-8",
            "notice": "0",
            "platform": "yqq.json",
            "needNewCode": "0",
        }
        if tid is not None:
            legacy_params["disstid"] = tid
        if did is not None:
            legacy_params["dirid"] = did
        if uin_text != "0":
            legacy_params["hostUin"] = uin_text
            legacy_params["loginUin"] = uin_text
            legacy_params["uin"] = uin_text
        if ctx_value in {0, 1}:
            legacy_params["ctx"] = ctx_value
        return legacy_params

    @staticmethod
    def _build_playlist_headers(tid: int | None) -> dict[str, str]:
        return {
            "Referer": (
                f"https://y.qq.com/n/ryqq/playlist/{tid}"
                if tid is not None
                else "https://y.qq.com/n/ryqq/profile"
            ),
            "Origin": "https://y.qq.com",
        }

    @staticmethod
    def _playlist_attempt_entry(
        source: str,
        *,
        tid: int | None,
        did: int | None,
        count: int | None = None,
        status: int | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "source": source,
            "disstid": tid,
            "dirid": did,
        }
        if count is not None:
            entry["count"] = count
        if status is not None:
            entry["status"] = status
        if error:
            entry["error"] = error
        return entry

    def _build_playlist_musicu_variants(
        self,
        *,
        tid: int | None,
        did: int | None,
        uin_text: str,
        ctx_value: int,
        song_num: int,
    ) -> list[tuple[str, dict[str, Any]]]:
        uniform_param = {
            "disstid": int(tid or 0),
            "dirid": int(did or 0),
            "song_begin": 0,
            "song_num": song_num,
            "onlysong": 0,
            "onlysonglist": 0,
            "userinfo": 1,
            "tag": 1,
            "orderlist": 1,
            "enc_host_uin": "" if uin_text == "0" else str(uin_text),
        }
        variants: list[tuple[str, dict[str, Any]]] = [
            (
                "uniform_get_Dissinfo",
                {
                    "module": "music.srfDissInfo.aiDissInfo",
                    "method": "uniform_get_Dissinfo",
                    "param": dict(uniform_param),
                },
            ),
            (
                "CgiGetDiss",
                {
                    "module": "music.srfDissInfo.SrfDissInfo",
                    "method": "CgiGetDiss",
                    "param": {
                        "disstid": int(tid or 0),
                        "dirid": int(did or 0),
                        "song_begin": 0,
                        "song_num": song_num,
                        "onlysong": 0,
                    },
                },
            ),
        ]
        if tid is None and did is not None:
            dirid_param = dict(uniform_param)
            dirid_param["disstid"] = int(did)
            dirid_param["dirid"] = int(did)
            variants.insert(
                1,
                (
                    "uniform_get_Dissinfo_dirid_as_disstid",
                    {
                        "module": "music.srfDissInfo.aiDissInfo",
                        "method": "uniform_get_Dissinfo",
                        "param": dirid_param,
                    },
                ),
            )
        if ctx_value in {0, 1}:
            for _label, payload in variants:
                param = payload.get("param")
                if isinstance(param, dict):
                    param["ctx"] = ctx_value
        return variants

    def _request_playlist_tracks(
        self,
        *,
        disstid: int | None,
        dirid: int | None,
        uin: str | None,
        ctx: int | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        song_num = max(1, min(5000, int(limit or 1000)))
        tid_value = self._safe_int(disstid, 0)
        did_value = self._safe_int(dirid, 0)
        tid = tid_value if tid_value > 0 else None
        did = did_value if did_value > 0 else None
        ctx_value = self._safe_int(ctx, -1)
        uin_text = self._normalize_uin(uin or self._uin_from_cookies() or "0")
        tried: list[dict[str, Any]] = []
        legacy_params = self._build_playlist_legacy_params(
            tid=tid,
            did=did,
            uin_text=uin_text,
            ctx_value=ctx_value,
            song_num=song_num,
        )
        headers = self._build_playlist_headers(tid)

        if tid is not None or did is not None:
            try:
                data, status_code = self._request_json_text_payload(
                    self._PLAYLIST_DETAIL_URL,
                    params=dict(legacy_params),
                    headers=headers,
                )
                songs = self._extract_playlist_tracks(data)
                normalized = self._normalize_song_list(songs)[:song_num]
                tried.append(
                    self._playlist_attempt_entry(
                        "legacy_detail",
                        tid=tid,
                        did=did,
                        status=status_code,
                        count=len(normalized),
                    )
                )
                if normalized:
                    return normalized, {"ok": True, "source": "legacy_detail", "tried": tried}
            except Exception as e:
                tried.append(self._playlist_attempt_entry("legacy_detail", tid=tid, did=did, error=str(e)))

        musicu_variants = self._build_playlist_musicu_variants(
            tid=tid,
            did=did,
            uin_text=uin_text,
            ctx_value=ctx_value,
            song_num=song_num,
        )

        for label, req_payload in musicu_variants:
            try:
                data = self._post_musicu(self._build_req0_musicu_payload(req_payload, uin_text=uin_text))
                songs = self._extract_playlist_tracks(data)
                normalized = self._normalize_song_list(songs)[:song_num]
                tried.append(self._playlist_attempt_entry(f"musicu:{label}", tid=tid, did=did, count=len(normalized)))
                if normalized:
                    return normalized, {"ok": True, "source": f"musicu:{label}", "tried": tried}
            except Exception as e:
                tried.append(self._playlist_attempt_entry(f"musicu:{label}", tid=tid, did=did, error=str(e)))

        return [], {
            "ok": False,
            "reason": "playlist_detail_empty",
            "disstid": tid,
            "dirid": did,
            "uin": uin_text,
            "tried": tried,
        }

    def get_playlist_tracks(
        self,
        disstid: int | str | None = None,
        limit: int = 1000,
        *,
        dirid: int | str | None = None,
        uin: str | int | None = None,
        ctx: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get songs of one QQ playlist (supports disstid or dirid)."""
        tid: int | None = None
        did: int | None = None
        try:
            if disstid is not None:
                t = int(disstid)
                if t > 0:
                    tid = t
        except (TypeError, ValueError):
            tid = None
        try:
            if dirid is not None:
                d = int(dirid)
                if d > 0:
                    did = d
        except (TypeError, ValueError):
            did = None
        if tid is None and did is None:
            return []

        tracks, _meta = self._request_playlist_tracks(
            disstid=tid,
            dirid=did,
            uin=str(uin or self._uin_from_cookies() or "0"),
            ctx=ctx,
            limit=limit,
        )
        return tracks

    def _get_liked_tracks_direct(
        self,
        *,
        uin: str | None,
        ctx: int | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        tracks, detail_meta = self._request_playlist_tracks(
            disstid=None,
            dirid=self._LIKED_DIRID,
            uin=str(uin or self._uin_from_cookies() or "0"),
            ctx=ctx,
            limit=limit,
        )
        if tracks:
            return tracks, {
                "ok": True,
                "reason": "direct_dirid_201",
                "source": detail_meta.get("source"),
                "track_count": len(tracks),
                "detail": detail_meta,
            }
        return [], {
            "ok": False,
            "reason": "direct_dirid_201_empty",
            "detail": detail_meta,
        }

    def _set_liked_meta_failure(
        self,
        reason: str,
        *,
        uin: str | None = None,
        myfav_meta: dict[str, Any] | None = None,
        direct_meta: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        meta: dict[str, Any] = {"ok": False, "reason": reason}
        if uin is not None:
            meta["uin"] = uin
        if myfav_meta is not None:
            meta["myfav_meta"] = myfav_meta
        if direct_meta is not None:
            meta["direct_probe"] = direct_meta
        if isinstance(extra, dict):
            meta.update(extra)
        self._last_liked_meta = meta

    def _set_liked_meta_success(
        self,
        reason: str,
        *,
        tracks: list[dict[str, Any]],
        playlist_id: int | None = None,
        playlist_name: str | None = None,
        matched_by: str | None = None,
        myfav_meta: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        meta: dict[str, Any] = {
            "ok": True,
            "reason": reason,
            "track_count": len(tracks),
        }
        if playlist_id is not None:
            meta["playlist_id"] = playlist_id
        if playlist_name:
            meta["playlist_name"] = str(playlist_name).strip()
        if matched_by:
            meta["matched_by"] = str(matched_by).strip()
        if myfav_meta is not None:
            meta["myfav_meta"] = myfav_meta
        self._last_liked_meta = meta
        return tracks

    def _probe_direct_liked_tracks(
        self,
        *,
        uin: str | None,
        ctx: int | None,
        max_items: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        direct_tracks, direct_meta = self._get_liked_tracks_direct(
            uin=uin,
            ctx=ctx,
            limit=max_items * 4,
        )
        if direct_tracks:
            self._last_liked_meta = direct_meta
            return direct_tracks[:max_items], direct_meta
        return [], direct_meta

    def _probe_direct_liked_or_fail(
        self,
        reason: str,
        *,
        uin: str | None,
        ctx: int | None,
        max_items: int,
        myfav_meta: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        direct_tracks, direct_meta = self._probe_direct_liked_tracks(
            uin=uin,
            ctx=ctx,
            max_items=max_items,
        )
        if direct_tracks:
            return direct_tracks
        self._set_liked_meta_failure(
            reason,
            uin=uin,
            myfav_meta=myfav_meta,
            direct_meta=direct_meta,
            extra=extra,
        )
        return []

    def _ordered_liked_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        strong_candidates = [x for x in candidates if self._is_strong_liked_playlist(x)]
        liked_by_dirid = [x for x in candidates if self._safe_int(x.get("dirid"), 0) == self._LIKED_DIRID]
        ordered_candidates: list[dict[str, Any]] = []
        for bucket in (liked_by_dirid, strong_candidates):
            for item in bucket:
                if item not in ordered_candidates:
                    ordered_candidates.append(item)
        return ordered_candidates

    def get_liked_tracks(self, limit: int = 32) -> list[dict[str, Any]]:
        """Get liked songs from QQ user playlists."""
        self._last_liked_meta = {}
        max_items = max(1, int(limit or 32))
        uin = self._effective_uin()
        if not uin or uin == "0":
            uin = self._uin_from_cookies()
        if not uin or uin == "0":
            self._last_liked_meta = {"ok": False, "reason": "no_uin"}
            return []
        cookie_uin = self._normalize_uin(self._uin_from_cookies() or "0")
        is_state_host = cookie_uin != "0" and cookie_uin == self._normalize_uin(uin)
        ctx = 1 if is_state_host else None

        myfav_dissid, myfav_meta = self._resolve_myfav_dissid(uin=uin)
        if myfav_dissid > 0:
            try:
                tracks = self.get_playlist_tracks(
                    disstid=myfav_dissid,
                    uin=uin,
                    ctx=ctx,
                    limit=max_items * 4,
                )
            except Exception as e:
                logger.debug("[QQmisic] get myFavDissId tracks failed dissid=%s: %s", myfav_dissid, e)
                tracks = []
            if tracks:
                return self._set_liked_meta_success(
                    "profile_myfav_dissid",
                    tracks=tracks[:max_items],
                    playlist_id=myfav_dissid,
                    playlist_name="???",
                    matched_by="profile_homepage_mymusic_type_1",
                    myfav_meta=myfav_meta,
                )

        try:
            playlists = self.get_user_playlists(uin=uin, size=256)
        except Exception as e:
            logger.warning("[QQmisic] get_user_playlists failed: %s", e)
            return self._probe_direct_liked_or_fail(
                "playlist_request_failed",
                uin=uin,
                ctx=ctx,
                max_items=max_items,
                myfav_meta=myfav_meta,
                extra={"error": str(e)},
            )
        if not playlists:
            return self._probe_direct_liked_or_fail(
                "playlist_empty",
                uin=uin,
                ctx=ctx,
                max_items=max_items,
                myfav_meta=myfav_meta,
            )

        candidates = self._preferred_playlists(playlists)
        if not candidates:
            self._set_liked_meta_failure(
                "playlist_no_candidate",
                uin=uin,
                myfav_meta=myfav_meta,
                extra={"playlist_total": len(playlists)},
            )
            return []

        ordered_candidates = self._ordered_liked_candidates(candidates)
        if not ordered_candidates:
            self._set_liked_meta_failure(
                "liked_playlist_not_found",
                uin=uin,
                myfav_meta=myfav_meta,
                extra={"playlist_total": len(candidates)},
            )
            return []

        tried: list[dict[str, int]] = []
        for item in ordered_candidates[:12]:
            playlist_id = item.get("disstid")
            dirid_val = self._safe_int(item.get("dirid"), 0)
            try:
                playlist_id_int = int(playlist_id)
            except (TypeError, ValueError):
                continue
            tried.append({"disstid": playlist_id_int, "dirid": dirid_val})
            try:
                tracks = self.get_playlist_tracks(
                    disstid=playlist_id_int,
                    dirid=dirid_val or None,
                    uin=uin,
                    ctx=ctx,
                    limit=max_items * 4,
                )
            except Exception as e:
                logger.debug("[QQmisic] get_playlist_tracks failed disstid=%s: %s", playlist_id_int, e)
                continue
            if tracks:
                return self._set_liked_meta_success(
                    "candidate_playlist",
                    tracks=tracks[:max_items],
                    playlist_id=playlist_id_int,
                    playlist_name=str(item.get("name") or "").strip(),
                    matched_by=str(item.get("_liked_match") or "").strip(),
                    myfav_meta=myfav_meta,
                )

        return self._probe_direct_liked_or_fail(
            "liked_playlist_tracks_empty",
            uin=uin,
            ctx=ctx,
            max_items=max_items,
            myfav_meta=myfav_meta,
            extra={"playlist_total": len(playlists), "tried": tried},
        )

QQMusic = QQmisic

_instance: QQmisic | None = None


def get_qqmusic_client() -> QQmisic:
    global _instance
    if _instance is None:
        _instance = QQmisic()
    return _instance
