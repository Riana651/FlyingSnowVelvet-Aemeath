"""网易云音乐管理器 - 登录系统 Mixin"""

import json
import math
import re
import threading
import time
from urllib.parse import quote_plus

import requests

from lib.core.event.center import EventType, Event
from lib.core.logger import get_logger
from config.config import TIMEOUTS, CLOUD_MUSIC

from ._provider_clients import get_kugou_provider_client, get_qqmusic_provider_client
from ._constants import (
    _KUGOU_LOGIN_CACHE_FILE,
    _LOGIN_CACHE_FILE,
    _QQ_LOGIN_CACHE_FILE,
    _QR_LOGIN_TIMEOUT,
    _QR_POLL_INTERVAL,
    _QR_REFRESH_INTERVAL,
)

logger = get_logger(__name__)


class _LoginMixin:
    """网易云账号登录系统：缓存恢复、匿名登录、二维码登录与退出。"""
    _QQ_LOGIN_APPID = "716027609"
    _QQ_LOGIN_DAID = "383"
    _QQ_LOGIN_PT_3RD_AID = "100497308"
    _QQ_LOGIN_S_URL = "https://graph.qq.com/oauth2.0/login_jump"
    _QQ_LOGIN_UI_STYLE = "40"
    _QQ_LOGIN_DEVICE = "2"
    _QQ_XLOGIN_URL = "https://xui.ptlogin2.qq.com/cgi-bin/xlogin"
    _QQ_QRSHOW_URL = "https://xui.ptlogin2.qq.com/ssl/ptqrshow"
    _QQ_PTQRLOGIN_URL = "https://ssl.ptlogin2.qq.com/ptqrlogin"
    _QQ_LOGIN_TIMEOUT = (8, 20)

    # ------------------------------------------------------------------
    # 静态辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _is_account_logged_in(status: dict) -> bool:
        """判断当前登录态是否为非匿名账号。"""
        if not isinstance(status, dict):
            return False
        account = status.get('account') or {}
        if not isinstance(account, dict) or not account:
            return False
        return not bool(account.get('anonimousUser', False))

    @staticmethod
    def _profile_from_status(status: dict) -> dict:
        """从登录状态中提取可展示的账号信息。"""
        if not isinstance(status, dict):
            return {}
        profile = status.get('profile')
        if isinstance(profile, dict) and profile:
            return profile
        account = status.get('account') or {}
        if isinstance(account, dict):
            name = str(account.get('userName') or '').strip()
            if name:
                return {'nickname': name}
        return {}

    @staticmethod
    def _is_cookie_conflict_error(error: Exception) -> bool:
        """判断是否为 pyncm requests-cookie 冲突错误（同名 __csrf）。"""
        text = str(error)
        if not text:
            return False
        lower = text.lower()
        return "__csrf" in lower and "multiple cookies" in lower

    @staticmethod
    def _current_provider() -> str:
        return str(CLOUD_MUSIC.get('provider', 'netease') or 'netease').strip().lower()

    @staticmethod
    def _is_qq_provider() -> bool:
        return _LoginMixin._current_provider() == 'qq'

    @staticmethod
    def _is_kugou_provider() -> bool:
        return _LoginMixin._current_provider() == 'kugou'

    @staticmethod
    def _qq_ptqrtoken(qrsig: str) -> int:
        e = 0
        for ch in str(qrsig or ''):
            e += (e << 5) + ord(ch)
        return e & 2147483647

    @staticmethod
    def _parse_qq_login_cb(raw_text: str) -> tuple[str, str, str, str]:
        """
        解析 ptqrlogin 返回：ptuiCB('code','sub','url','flag','msg','nickname')
        返回 (code, redirect_url, message, nickname)
        """
        text = str(raw_text or '').strip()
        m = re.search(r"ptuiCB\((.*)\)", text)
        if not m:
            return "", "", text, ""
        inner = m.group(1)
        parts = re.findall(r"'([^']*)'", inner)
        if len(parts) >= 5:
            code = parts[0]
            redirect = parts[2]
            msg = parts[4]
            nickname = parts[5] if len(parts) >= 6 else ""
            return code, redirect, msg, nickname
        return "", "", text, ""

    @classmethod
    def _qq_xlogin_params(cls) -> dict[str, str]:
        # 同步 QQ 官方 login_10.js 当前参数，避免旧参数导致 ptqrlogin 403。
        return {
            "appid": cls._QQ_LOGIN_APPID,
            "daid": cls._QQ_LOGIN_DAID,
            "style": "33",
            "login_text": "登录",
            "hide_title_bar": "1",
            "hide_border": "1",
            "target": "self",
            "s_url": cls._QQ_LOGIN_S_URL,
            "pt_3rd_aid": cls._QQ_LOGIN_PT_3RD_AID,
            "theme": "2",
            "verify_theme": "",
        }

    @classmethod
    def _qq_qrshow_params(cls) -> dict[str, str]:
        return {
            "s": "8",
            "e": "0",
            "appid": cls._QQ_LOGIN_APPID,
            "type": "1",
            "t": str(time.time()),
            "u1": cls._QQ_LOGIN_S_URL,
            "daid": cls._QQ_LOGIN_DAID,
            "pt_3rd_aid": cls._QQ_LOGIN_PT_3RD_AID,
        }

    @classmethod
    def _qq_ptqrlogin_params(cls, ptqrtoken: str) -> dict[str, str]:
        return {
            "u1": cls._QQ_LOGIN_S_URL,
            "from_ui": "1",
            "type": "1",
            "ptlang": "2052",
            "ptqrtoken": str(ptqrtoken or ""),
            "daid": cls._QQ_LOGIN_DAID,
            "aid": cls._QQ_LOGIN_APPID,
            "pt_3rd_aid": cls._QQ_LOGIN_PT_3RD_AID,
            "device": cls._QQ_LOGIN_DEVICE,
            "ptopt": "1",
            "pt_uistyle": cls._QQ_LOGIN_UI_STYLE,
        }

    def _qq_sync_login_session(self, session, headers: dict[str, str], redirect_url: str) -> None:
        # 登录成功后补齐跳转链路，促使 y.qq.com 侧 Cookie 写入完整。
        urls = [
            redirect_url,
            self._QQ_LOGIN_S_URL,
            "https://y.qq.com/m/login/redirect.html?is_qq_connect=1&login_type=1&surl=https%3A%2F%2Fy.qq.com%2Fn%2Fryqq%2Findex.html",
            "https://y.qq.com/",
            "https://y.qq.com/n/ryqq/index.html",
        ]
        for url in urls:
            if not url:
                continue
            try:
                session.get(str(url), headers=headers, timeout=self._QQ_LOGIN_TIMEOUT, allow_redirects=True)
            except Exception:
                continue

    @staticmethod
    def _qq_nickname_hint(session, fallback: str = "QQ账号") -> str:
        try:
            cookies = session.cookies.get_dict() or {}
        except Exception:
            return fallback
        nickname = str(cookies.get("nick") or "").strip()
        if nickname:
            return nickname
        uin = str(cookies.get("uin") or cookies.get("p_uin") or "").strip()
        m = re.search(r"(\d{4,})", uin)
        if not m:
            return fallback
        num = m.group(1)
        return f"QQ账号({num[-4:]})"

    @staticmethod
    def _login_success_message(platform_name: str, nickname: str | None) -> str:
        clean_platform = str(platform_name or "").strip() or "平台"
        clean_nickname = str(nickname or "").strip() or "未知用户"
        return f"{clean_platform}登录成功:{clean_nickname}"

    @staticmethod
    def _qq_is_png_bytes(data: bytes) -> bool:
        return isinstance(data, (bytes, bytearray)) and bytes(data).startswith(b"\x89PNG\r\n\x1a\n")

    def _qq_qr_png_from_response(self, response) -> bytes | None:
        data = bytes(getattr(response, "content", b"") or b"")
        if self._qq_is_png_bytes(data):
            return data

        text = str(getattr(response, "text", "") or "").strip()
        if not text:
            return data or None

        payload_obj = None
        m = re.search(r"ptui_qrcode_CB\((\{.*\})\)\s*;?\s*$", text)
        raw_json = m.group(1) if m else (text if text.startswith("{") and text.endswith("}") else "")
        if raw_json:
            try:
                payload_obj = json.loads(raw_json)
            except Exception:
                payload_obj = None

        if isinstance(payload_obj, dict):
            qr_url = str(payload_obj.get("qrcode") or payload_obj.get("url") or "").strip()
            if qr_url:
                qr_png = self._create_qr_png(qr_url)
                if qr_png:
                    return qr_png

        return data or None

    @staticmethod
    def _qq_has_login_cookies(session) -> bool:
        """通过 QQ 常见登录 Cookie 判断当前会话是否已完成登录。"""
        if session is None:
            return False
        try:
            cookies = session.cookies.get_dict() or {}
        except Exception:
            return False

        uin = str(cookies.get('uin') or cookies.get('wxuin') or cookies.get('p_uin') or '').strip()
        if not uin:
            return False

        return bool(
            str(cookies.get('p_skey') or '').strip()
            or str(cookies.get('skey') or '').strip()
            or str(cookies.get('p_uin') or '').strip()
            or str(cookies.get('pt4_token') or '').strip()
            or str(cookies.get('qm_keyst') or '').strip()
            or str(cookies.get('qqmusic_key') or '').strip()
            or str(cookies.get('music_key') or '').strip()
        )

    @staticmethod
    def _qq_has_uin_cookie(session) -> bool:
        if session is None:
            return False
        try:
            cookies = session.cookies.get_dict() or {}
        except Exception:
            return False
        return bool(str(cookies.get('uin') or cookies.get('wxuin') or cookies.get('p_uin') or '').strip())

    # ------------------------------------------------------------------
    # Cookie 管理
    # ------------------------------------------------------------------

    def _clear_runtime_login_cookies(self):
        """清空当前进程内 pyncm 会话 Cookie，解决同名 Cookie 冲突。"""
        try:
            from pyncm.apis.login import GetCurrentSession
        except Exception:
            return

        try:
            session = GetCurrentSession()
        except Exception as e:
            logger.debug('[CloudMusic] 获取当前会话失败，无法清理 Cookie: %s', e)
            return

        jar = getattr(session, 'cookies', None)
        if jar is None:
            return

        try:
            jar.clear()
            return
        except Exception:
            pass

        # 兼容少数 CookieJar 实现 clear() 失败的场景。
        try:
            for cookie in list(jar):
                try:
                    jar.clear(domain=cookie.domain, path=cookie.path, name=cookie.name)
                except Exception:
                    continue
        except Exception as e:
            logger.debug('[CloudMusic] Cookie 逐项清理失败: %s', e)

    def _call_with_cookie_recover(self, func, *args, **kwargs):
        """
        调用 pyncm 接口；若遇到 __csrf 多 Cookie 冲突则清理后重试一次。
        """
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if not self._is_cookie_conflict_error(e):
                raise
            logger.warning('[CloudMusic] 检测到 __csrf Cookie 冲突，清理后重试: %s', e)
            self._clear_runtime_login_cookies()
            return func(*args, **kwargs)

    def _login_call_timeout(self) -> float:
        try:
            v = float(TIMEOUTS.get('login_call', 12))
        except (TypeError, ValueError):
            v = 12.0
        return max(2.0, min(60.0, v))

    def _safe_login_call(self, func, *args, **kwargs):
        done = threading.Event()
        out = {}
        err = {}
        timeout_s = self._login_call_timeout()

        def _run():
            try:
                out['v'] = self._call_with_cookie_recover(func, *args, **kwargs)
            except Exception as e:
                err['e'] = e
            finally:
                done.set()

        threading.Thread(target=_run, daemon=True, name='cm-login-call').start()
        if not done.wait(timeout=timeout_s):
            name = getattr(func, '__name__', 'login_call')
            raise TimeoutError(f'{name} 超时 ({timeout_s:.1f}s)')
        if 'e' in err:
            raise err['e']
        return out.get('v')

    # ------------------------------------------------------------------
    # 登录缓存
    # ------------------------------------------------------------------

    def _clear_login_cache(self):
        try:
            _LOGIN_CACHE_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    def _save_login_cache(self) -> bool:
        """保存登录 cookies 到项目根目录，便于用户手动删除。"""
        if not self.provider_logged_in('netease'):
            return False
        try:
            from pyncm.apis.login import GetCurrentSession
            cookies = GetCurrentSession().cookies.get_dict() or {}
            if not cookies:
                return False
            payload = {
                'version': 1,
                'saved_at': int(time.time()),
                'cookies': cookies,
            }
            with open(_LOGIN_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            logger.info('[CloudMusic] 登录缓存已写入: %s', _LOGIN_CACHE_FILE)
            return True
        except Exception as e:
            logger.warning('[CloudMusic] 保存登录缓存失败: %s', e)
            return False

    def _restore_login_from_cache(self) -> bool:
        """从项目根目录缓存恢复登录。"""
        if not _LOGIN_CACHE_FILE.exists():
            return False
        try:
            with open(_LOGIN_CACHE_FILE, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            cookies = payload.get('cookies') if isinstance(payload, dict) else None
            if not isinstance(cookies, dict) or not cookies:
                self._clear_login_cache()
                return False

            from pyncm.apis.login import LoginViaCookie, GetCurrentLoginStatus
            self._clear_runtime_login_cookies()
            self._safe_login_call(LoginViaCookie, **cookies)
            status = self._safe_login_call(GetCurrentLoginStatus)
            if self._is_account_logged_in(status):
                self._set_login_state(True, self._profile_from_status(status), provider='netease')
                logger.info('[CloudMusic] 已从缓存恢复账号登录')
                return True

            logger.info('[CloudMusic] 登录缓存已失效，回退匿名登录')
            self._clear_login_cache()
            return False
        except Exception as e:
            logger.warning('[CloudMusic] 恢复登录缓存失败: %s', e)
            self._clear_login_cache()
            return False

    def _clear_qq_login_cache(self):
        try:
            _QQ_LOGIN_CACHE_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    def _save_qq_login_cache(self) -> bool:
        try:
            cookies = get_qqmusic_provider_client().export_cookies()
            if not cookies:
                return False
            payload = {
                'version': 1,
                'saved_at': int(time.time()),
                'cookies': cookies,
            }
            with open(_QQ_LOGIN_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            logger.info('[CloudMusic] QQ 登录缓存已写入: %s', _QQ_LOGIN_CACHE_FILE)
            return True
        except Exception as e:
            logger.warning('[CloudMusic] 保存 QQ 登录缓存失败: %s', e)
            return False

    def _restore_qq_login_from_cache(self) -> bool:
        if not _QQ_LOGIN_CACHE_FILE.exists():
            return False
        try:
            with open(_QQ_LOGIN_CACHE_FILE, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            cookies = payload.get('cookies') if isinstance(payload, dict) else None
            if not isinstance(cookies, dict) or not cookies:
                self._clear_qq_login_cache()
                return False
            client = get_qqmusic_provider_client()
            client.set_cookies({str(k): str(v) for k, v in cookies.items() if v is not None})
            if not client.is_logged_in():
                logger.warning('[CloudMusic] QQ 缓存登录态无有效鉴权 Cookie，清理缓存并回退未登录')
                self._clear_qq_login_cache()
                self._set_login_state(False, {}, provider='qq')
                return False
            self._set_login_state(True, {'nickname': 'QQ账号'}, provider='qq')
            logger.info('[CloudMusic] 已从缓存恢复 QQ 登录态')
            return True
        except Exception as e:
            logger.warning('[CloudMusic] 恢复 QQ 登录缓存失败: %s', e)
            self._clear_qq_login_cache()
            return False

    def _clear_kugou_login_cache(self):
        try:
            _KUGOU_LOGIN_CACHE_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    def _save_kugou_login_cache(self) -> bool:
        try:
            cookies = get_kugou_provider_client().export_cookies()
            if not cookies:
                return False
            payload = {
                'version': 1,
                'saved_at': int(time.time()),
                'cookies': cookies,
            }
            with open(_KUGOU_LOGIN_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            logger.info('[CloudMusic] 酷狗登录缓存已写入: %s', _KUGOU_LOGIN_CACHE_FILE)
            return True
        except Exception as e:
            logger.warning('[CloudMusic] 保存酷狗登录缓存失败: %s', e)
            return False

    def _restore_kugou_login_from_cache(self) -> bool:
        if not _KUGOU_LOGIN_CACHE_FILE.exists():
            return False
        try:
            with open(_KUGOU_LOGIN_CACHE_FILE, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            cookies = payload.get('cookies') if isinstance(payload, dict) else None
            if not isinstance(cookies, dict) or not cookies:
                self._clear_kugou_login_cache()
                return False

            client = get_kugou_provider_client()
            client.set_cookies({str(k): str(v) for k, v in cookies.items() if v is not None})
            if client.is_logged_in():
                uid = str(cookies.get('userid') or '').strip()
                nickname = f"酷狗用户({uid[-4:]})" if uid else "酷狗用户"
                self._set_login_state(True, {'nickname': nickname}, provider='kugou')
                logger.info('[CloudMusic] 已从缓存恢复酷狗登录态')
                return True

            logger.info('[CloudMusic] 酷狗登录缓存已失效')
            self._clear_kugou_login_cache()
            return False
        except Exception as e:
            logger.warning('[CloudMusic] 恢复酷狗登录缓存失败: %s', e)
            self._clear_kugou_login_cache()
            return False

    # ------------------------------------------------------------------
    # 登录方式
    # ------------------------------------------------------------------

    def _anonymous_login(self):
        """执行匿名登录（用于播放功能兜底）。"""
        from pyncm.apis.login import LoginViaAnonymousAccount, GetCurrentLoginStatus
        t0 = time.monotonic()
        self._clear_runtime_login_cookies()
        t1 = time.monotonic()
        self._safe_login_call(LoginViaAnonymousAccount)
        t2 = time.monotonic()
        status = self._safe_login_call(GetCurrentLoginStatus)
        t3 = time.monotonic()
        self._set_login_state(
            self._is_account_logged_in(status),
            self._profile_from_status(status),
            provider='netease',
        )
        logger.info("[CloudMusic] 匿名登录完成")
        logger.debug(
            "[CloudMusic] 匿名登录耗时: clear=%.3fs login=%.3fs status=%.3fs total=%.3fs",
            t1 - t0,
            t2 - t1,
            t3 - t2,
            t3 - t0,
        )

    # ------------------------------------------------------------------
    # 二维码生成
    # ------------------------------------------------------------------

    def _create_qr_png(self, qr_url: str) -> bytes | None:
        """将二维码 URL 渲染成 PNG 二进制。"""
        try:
            import io
            import qrcode

            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=10,
                border=2,
            )
            qr.add_data(qr_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color='black', back_color='white')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        except Exception as e:
            logger.debug('[CloudMusic] 本地二维码生成失败，尝试在线兜底: %s', e)

        try:
            online = f'https://api.qrserver.com/v1/create-qr-code/?size=320x320&data={quote_plus(qr_url)}'
            resp = requests.get(online, timeout=(8, 12))
            resp.raise_for_status()
            if resp.content:
                return resp.content
        except Exception as e:
            logger.warning('[CloudMusic] 在线二维码生成失败: %s', e)
        return None

    # ------------------------------------------------------------------
    # 二维码登录事件发布
    # ------------------------------------------------------------------

    def _publish_qr_show(self, qr_png: bytes, status: str, title: str = '音乐扫码登录'):
        self._ec.publish(Event(EventType.MUSIC_LOGIN_QR_SHOW, {
            'qr_png': qr_png,
            'status': status,
            'title': title,
        }))

    def _publish_qr_status(self, status: str, refresh_left: int | None = None):
        data = {'status': status}
        if refresh_left is not None:
            data['refresh_left'] = max(0, int(refresh_left))
        self._ec.publish(Event(EventType.MUSIC_LOGIN_QR_STATUS, data))

    def _publish_qr_hide(self):
        self._ec.publish(Event(EventType.MUSIC_LOGIN_QR_HIDE, {}))

    def _request_qr_payload(self, LoginQrcodeUnikey, GetLoginQRCodeUrl) -> tuple[str, bytes]:
        """申请新的二维码登录 key 并返回可展示 PNG。"""
        unikey_resp = LoginQrcodeUnikey()
        unikey = (
            (unikey_resp or {}).get('unikey')
            or (unikey_resp or {}).get('data', {}).get('unikey')
        )
        if not unikey:
            raise RuntimeError(f'获取二维码 key 失败: {unikey_resp}')

        qr_url = GetLoginQRCodeUrl(str(unikey))
        qr_png = self._create_qr_png(qr_url)
        if not qr_png:
            raise RuntimeError('二维码生成失败')

        return str(unikey), qr_png

    # ------------------------------------------------------------------
    # 登录事件处理
    # ------------------------------------------------------------------

    def _on_login_request(self, event: Event):
        """处理登录按钮点击：发起二维码登录流程。"""
        if self._is_qq_provider():
            self._on_qq_login_request()
            return
        if self._is_kugou_provider():
            self._on_kugou_login_request()
            return

        already_logged_in = self.provider_logged_in('netease')
        if already_logged_in:
            self._show_info('网易云账号已登录')
            return

        if self._qr_login_thread is not None and self._qr_login_thread.is_alive():
            self._show_info('二维码登录进行中，请完成手机确认')
            return

        self._qr_login_cancel.clear()
        self._qr_login_thread = threading.Thread(
            target=self._qr_login_worker,
            daemon=True,
            name='cm-qr-login',
        )
        self._qr_login_thread.start()

    def _on_login_cancel_request(self, event: Event):
        """处理退出扫码请求：仅取消当前扫码流程，不执行账号登出。"""
        self._qr_login_cancel.set()
        self._publish_qr_hide()
        if self._qr_login_thread is not None and self._qr_login_thread.is_alive():
            self._show_info('已退出扫码登录')

    def _on_logout_request(self, event: Event):
        """处理退出登录请求：退出网易云账号并清除本地登录缓存。"""
        if self._is_qq_provider():
            self._on_qq_logout_request()
            return
        if self._is_kugou_provider():
            self._on_kugou_logout_request()
            return

        # 终止可能存在的二维码登录流程，并关闭二维码弹窗。
        self._qr_login_cancel.set()
        self._publish_qr_hide()
        threading.Thread(
            target=self._logout_worker,
            daemon=True,
            name='cm-logout',
        ).start()

    def _logout_worker(self):
        t0 = time.monotonic()

        try:
            from pyncm.apis.login import LoginLogout
            self._safe_login_call(LoginLogout)
        except ImportError:
            logger.warning('[CloudMusic] pyncm 未安装，跳过远端退出登录')
        except Exception as e:
            logger.warning('[CloudMusic] 远端退出登录失败: %s', e)

        self._clear_login_cache()

        # 退出账号后回退匿名态，保持音乐功能可用，同时 UI 应显示未登录。
        try:
            self._anonymous_login()
        except ImportError:
            self._set_login_state(False, {}, provider='netease')
        except Exception as e:
            logger.warning('[CloudMusic] 回退匿名登录失败: %s', e)
            self._set_login_state(False, {}, provider='netease')

        self._show_info('已退出网易云登录并清除缓存')
        logger.debug('[CloudMusic] 退出登录流程耗时: %.3fs', time.monotonic() - t0)

    def _on_qq_logout_request(self):
        self._qr_login_cancel.set()
        self._publish_qr_hide()
        threading.Thread(
            target=self._qq_logout_worker,
            daemon=True,
            name='cm-qq-logout',
        ).start()

    def _qq_logout_worker(self):
        try:
            get_qqmusic_provider_client().set_cookies({})
        except Exception:
            pass
        self._clear_qq_login_cache()
        self._set_login_state(False, {}, provider='qq')
        self._show_info('已退出QQ登录并清除缓存')

    def _on_kugou_logout_request(self):
        self._qr_login_cancel.set()
        self._publish_qr_hide()
        threading.Thread(
            target=self._kugou_logout_worker,
            daemon=True,
            name='cm-kugou-logout',
        ).start()

    def _kugou_logout_worker(self):
        try:
            get_kugou_provider_client().set_cookies({})
        except Exception:
            pass
        self._clear_kugou_login_cache()
        self._set_login_state(False, {}, provider='kugou')
        self._show_info('已退出酷狗登录并清除缓存')

    # ------------------------------------------------------------------
    # 二维码登录后台线程
    # ------------------------------------------------------------------

    def _on_kugou_login_request(self):
        already_logged_in = self.provider_logged_in('kugou')
        if already_logged_in:
            self._show_info('酷狗账号已登录')
            return

        if self._qr_login_thread is not None and self._qr_login_thread.is_alive():
            self._show_info('酷狗扫码登录进行中，请完成手机确认')
            return

        self._qr_login_cancel.clear()
        self._qr_login_thread = threading.Thread(
            target=self._kugou_login_worker,
            daemon=True,
            name='cm-kugou-qr-login',
        )
        self._qr_login_thread.start()

    def _on_qq_login_request(self):
        already_logged_in = self.provider_logged_in('qq')
        if already_logged_in:
            self._show_info('QQ账号已登录')
            return

        if self._qr_login_thread is not None and self._qr_login_thread.is_alive():
            self._show_info('QQ扫码登录进行中，请完成手机确认')
            return

        self._qr_login_cancel.clear()
        self._qr_login_thread = threading.Thread(
            target=self._qq_login_worker,
            daemon=True,
            name='cm-qq-qr-login',
        )
        self._qr_login_thread.start()

    def _qq_login_worker(self):
        """后台执行 QQ 二维码登录轮询。"""
        should_hide_qr = False
        try:
            client = get_qqmusic_provider_client()
            session = client.get_session()
            headers = {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/122.0.0.0 Safari/537.36'
                ),
            }
            xlogin = session.get(
                self._QQ_XLOGIN_URL,
                params=self._qq_xlogin_params(),
                headers=headers,
                timeout=self._QQ_LOGIN_TIMEOUT,
            )
            xlogin.raise_for_status()
            headers["Referer"] = str(xlogin.url or self._QQ_XLOGIN_URL)

            def _request_qq_qr_payload(status_text: str, show_text: str) -> str:
                self._publish_qr_status(status_text)
                qr_resp = session.get(
                    self._QQ_QRSHOW_URL,
                    params=self._qq_qrshow_params(),
                    headers=headers,
                    timeout=self._QQ_LOGIN_TIMEOUT,
                )
                if qr_resp.status_code != 200:
                    raise RuntimeError(f'QQ二维码获取失败: {qr_resp.status_code}')
                qrsig = session.cookies.get('qrsig') or ''
                if not qrsig:
                    raise RuntimeError('QQ二维码获取失败: 缺少 qrsig')
                ptqrtoken = str(self._qq_ptqrtoken(qrsig))
                qr_png = self._qq_qr_png_from_response(qr_resp)
                if not qr_png:
                    raise RuntimeError('QQ二维码渲染失败')
                self._publish_qr_show(qr_png, show_text, title='QQ扫码登录')
                return ptqrtoken

            ptqrtoken = _request_qq_qr_payload('正在生成QQ二维码...', '请使用QQ扫码登录')

            begin_ts = time.time()
            last_refresh_ts = begin_ts
            last_refresh_left: int | None = None
            while not self._qr_login_cancel.is_set():
                now_ts = time.time()
                if now_ts - begin_ts > _QR_LOGIN_TIMEOUT:
                    self._publish_qr_status('QQ二维码超时，请重新点击登录')
                    self._show_info('QQ二维码已超时，请重新点击登录音乐')
                    return

                poll_resp = session.get(
                    self._QQ_PTQRLOGIN_URL,
                    params=self._qq_ptqrlogin_params(ptqrtoken),
                    headers=headers,
                    timeout=self._QQ_LOGIN_TIMEOUT,
                )
                code, redirect_url, message, nickname = self._parse_qq_login_cb(poll_resp.text)
                if code == '66':
                    left = int(math.ceil(max(0.0, _QR_REFRESH_INTERVAL - (now_ts - last_refresh_ts))))
                    if left != last_refresh_left:
                        self._publish_qr_status('等待扫码...', refresh_left=left)
                        last_refresh_left = left
                    if (now_ts - last_refresh_ts) >= _QR_REFRESH_INTERVAL:
                        ptqrtoken = _request_qq_qr_payload('正在刷新QQ二维码...', 'QQ二维码已自动刷新，请扫码登录')
                        last_refresh_ts = time.time()
                        last_refresh_left = None
                        continue
                elif code == '67':
                    self._publish_qr_status('已扫码，请在手机端确认登录')
                    last_refresh_left = None
                elif code == '65':
                    ptqrtoken = _request_qq_qr_payload('二维码已过期，正在自动刷新...', 'QQ二维码已自动刷新，请重新扫码')
                    last_refresh_ts = time.time()
                    last_refresh_left = None
                    continue
                elif code == '0':
                    self._publish_qr_status('登录成功，正在同步...')
                    self._qq_sync_login_session(session, headers, redirect_url)
                    cookie_ok = self._qq_has_login_cookies(session)
                    if not cookie_ok:
                        # 某些环境只写入 uin + qqmusic_key 相关 Cookie，先做一次宽松确认，避免误判失败。
                        if not self._qq_has_uin_cookie(session):
                            self._publish_qr_status('QQ登录同步失败，请重试')
                            self._show_error('QQ登录状态异常，请重试')
                            return
                        logger.warning('[CloudMusic] QQ 登录同步后仅检测到 uin，按成功继续')
                    nickname = str(nickname or "").strip() or self._qq_nickname_hint(session)
                    self._set_login_state(True, {'nickname': nickname}, provider='qq')
                    self._save_qq_login_cache()
                    self._show_info(self._login_success_message("QQ平台", nickname))
                    should_hide_qr = True
                    return
                elif code:
                    self._publish_qr_status(message or 'QQ登录处理中...')
                    last_refresh_left = None
                elif int(poll_resp.status_code or 0) >= 400:
                    if self._qq_has_login_cookies(session):
                        nickname = self._qq_nickname_hint(session)
                        self._set_login_state(True, {'nickname': nickname}, provider='qq')
                        self._save_qq_login_cache()
                        self._publish_qr_status('已检测到QQ登录成功，正在同步...')
                        self._show_info(self._login_success_message("QQ平台", nickname))
                        should_hide_qr = True
                        return
                    self._publish_qr_status(f'QQ登录接口返回 {poll_resp.status_code}，正在重试...')
                    last_refresh_left = None
                    time.sleep(max(_QR_POLL_INTERVAL, 2.0))
                    continue
                else:
                    self._publish_qr_status(message or 'QQ登录处理中...')
                    last_refresh_left = None

                time.sleep(_QR_POLL_INTERVAL)
        except Exception as e:
            logger.error('[CloudMusic] QQ二维码登录失败: %s', e)
            self._publish_qr_status('QQ二维码登录失败，请稍后重试')
            self._show_error('QQ二维码登录失败，请稍后重试')
        finally:
            if should_hide_qr or self._qr_login_cancel.is_set():
                self._publish_qr_hide()

    def _kugou_login_worker(self):
        """后台执行酷狗二维码登录轮询。"""
        should_hide_qr = False
        try:
            client = get_kugou_provider_client()

            def _request_kugou_qr_payload(status_text: str, show_text: str) -> str:
                self._publish_qr_status(status_text)
                qr_payload = client.create_login_qr()
                qr_key = str(qr_payload.get('key') or '').strip()
                qr_png = qr_payload.get('qr_png')
                qr_url = str(qr_payload.get('qr_url') or '').strip()
                if not qr_key:
                    raise RuntimeError('酷狗二维码 key 获取失败')
                if not qr_png and qr_url:
                    qr_png = self._create_qr_png(qr_url)
                if not qr_png:
                    raise RuntimeError('酷狗二维码渲染失败')
                self._publish_qr_show(qr_png, show_text, title='酷狗扫码登录')
                return qr_key

            qr_key = _request_kugou_qr_payload('正在生成酷狗二维码...', '请使用酷狗音乐扫码登录')

            begin_ts = time.time()
            last_refresh_ts = begin_ts
            last_refresh_left: int | None = None
            while not self._qr_login_cancel.is_set():
                now_ts = time.time()
                if now_ts - begin_ts > _QR_LOGIN_TIMEOUT:
                    self._publish_qr_status('酷狗二维码超时，请重新点击登录')
                    self._show_info('酷狗二维码已超时，请重新点击登录音乐')
                    return

                result = client.poll_login_qr(qr_key)
                status = int(result.get('status', -1))
                if status == 1:
                    left = int(math.ceil(max(0.0, _QR_REFRESH_INTERVAL - (now_ts - last_refresh_ts))))
                    if left != last_refresh_left:
                        self._publish_qr_status('等待扫码...', refresh_left=left)
                        last_refresh_left = left
                    if (now_ts - last_refresh_ts) >= _QR_REFRESH_INTERVAL:
                        qr_key = _request_kugou_qr_payload('正在刷新酷狗二维码...', '酷狗二维码已自动刷新，请扫码登录')
                        last_refresh_ts = time.time()
                        last_refresh_left = None
                        continue
                elif status == 2:
                    self._publish_qr_status('已扫码，请在手机端确认登录')
                    last_refresh_left = None
                elif status == 0:
                    qr_key = _request_kugou_qr_payload('二维码已过期，正在自动刷新...', '酷狗二维码已自动刷新，请重新扫码')
                    last_refresh_ts = time.time()
                    last_refresh_left = None
                    continue
                elif status == 4:
                    token = str(result.get('token') or '').strip()
                    userid = str(result.get('userid') or '').strip()
                    if not client.set_login_token(token, userid):
                        self._publish_qr_status('酷狗登录状态异常，请重试')
                        self._show_error('酷狗登录状态异常，请重试')
                        return
                    nickname = str(result.get('nickname') or '').strip()
                    if not nickname:
                        nickname = f"酷狗用户({userid[-4:]})" if userid else "酷狗用户"
                    self._set_login_state(True, {'nickname': nickname}, provider='kugou')
                    self._save_kugou_login_cache()
                    self._show_info(self._login_success_message("酷狗平台", nickname))
                    should_hide_qr = True
                    return
                else:
                    msg = str(result.get('message') or '').strip()
                    self._publish_qr_status(msg or f'酷狗登录状态: {status}')
                    last_refresh_left = None

                time.sleep(_QR_POLL_INTERVAL)
        except Exception as e:
            logger.error('[CloudMusic] 酷狗二维码登录失败: %s', e)
            self._publish_qr_status('酷狗二维码登录失败，请稍后重试')
            self._show_error('酷狗二维码登录失败，请稍后重试')
        finally:
            if should_hide_qr or self._qr_login_cancel.is_set():
                self._publish_qr_hide()

    def _qr_login_worker(self):
        """后台执行二维码登录轮询。"""
        try:
            from pyncm.apis.login import (
                LoginQrcodeUnikey,
                GetLoginQRCodeUrl,
                LoginQrcodeCheck,
                GetCurrentLoginStatus,
            )

            self._publish_qr_status('正在生成二维码...')
            unikey, qr_png = self._request_qr_payload(LoginQrcodeUnikey, GetLoginQRCodeUrl)
            self._publish_qr_show(qr_png, '请使用网易云音乐扫码登录', title='网易云扫码登录')

            begin_ts        = time.time()
            last_refresh_ts = begin_ts
            last_code       = None
            last_refresh_left: int | None = None
            while not self._qr_login_cancel.is_set():
                now_ts = time.time()
                if now_ts - begin_ts > _QR_LOGIN_TIMEOUT:
                    self._publish_qr_status('二维码超时，请重新点击登录')
                    self._show_info('二维码已超时，请重新点击登录音乐')
                    return

                check = LoginQrcodeCheck(str(unikey))
                code  = int((check or {}).get('code', -1))
                if code != last_code:
                    if code == 802:
                        self._publish_qr_status('已扫码，请在手机端确认登录')
                    elif code == 803:
                        self._publish_qr_status('登录成功，正在同步...')
                    elif code == 800:
                        self._publish_qr_status('二维码已过期，请重新点击登录')
                    else:
                        self._publish_qr_status(f'登录状态: {code}')
                    last_code = code
                    if code != 801:
                        last_refresh_left = None

                if code == 803:
                    status = self._safe_login_call(GetCurrentLoginStatus)
                    if self._is_account_logged_in(status):
                        profile  = self._profile_from_status(status)
                        self._set_login_state(True, profile, provider='netease')
                        self._save_login_cache()
                        nickname = self._extract_nickname(profile) or '网易云账号'
                        self._show_info(self._login_success_message("网易云平台", nickname))
                        return
                    self._show_error('登录状态异常，请重试')
                    return

                if code == 800:
                    self._publish_qr_status('二维码已过期，正在自动刷新...')
                    unikey, qr_png = self._request_qr_payload(LoginQrcodeUnikey, GetLoginQRCodeUrl)
                    self._publish_qr_show(qr_png, '二维码已自动刷新，请重新扫码', title='网易云扫码登录')
                    last_code         = None
                    last_refresh_left = None
                    last_refresh_ts   = time.time()
                    continue

                # 自动刷新二维码：按 _QR_REFRESH_INTERVAL（默认 30 秒）刷新一次（等待扫码阶段）
                if code == 801 and (now_ts - last_refresh_ts) >= _QR_REFRESH_INTERVAL:
                    unikey, qr_png = self._request_qr_payload(LoginQrcodeUnikey, GetLoginQRCodeUrl)
                    self._publish_qr_show(qr_png, '二维码已自动刷新，请扫码登录', title='网易云扫码登录')
                    last_code         = None
                    last_refresh_left = None
                    last_refresh_ts   = time.time()
                    continue

                # 等待扫码阶段显示刷新倒计时（每秒更新）
                if code == 801:
                    left = int(math.ceil(max(0.0, _QR_REFRESH_INTERVAL - (now_ts - last_refresh_ts))))
                    if left != last_refresh_left:
                        self._publish_qr_status('等待扫码...', refresh_left=left)
                        last_refresh_left = left

                time.sleep(_QR_POLL_INTERVAL)

        except ImportError:
            self._show_error('缺少 pyncm 依赖，无法二维码登录')
        except Exception as e:
            logger.error('[CloudMusic] 二维码登录失败: %s', e)
            self._show_error('二维码登录失败，请稍后重试')
        finally:
            self._publish_qr_hide()

    # ------------------------------------------------------------------
    # 启动登录
    # ------------------------------------------------------------------

    def _login(self):
        """启动时登录：初始化恢复全平台登录态。"""
        t0 = time.monotonic()
        netease_ready = False
        qq_ready = False
        kugou_ready = False
        try:
            # Kugou: 启动时恢复缓存登录，不依赖当前模式。
            try:
                kugou_ready = self._restore_kugou_login_from_cache()
            except Exception as e:
                logger.warning("[CloudMusic] 酷狗启动恢复登录失败: %s", e)
            if not kugou_ready:
                self._set_login_state(False, {}, provider='kugou')

            # QQ: 启动时恢复缓存登录，不依赖当前模式。
            try:
                qq_ready = self._restore_qq_login_from_cache()
            except Exception as e:
                logger.warning("[CloudMusic] QQ 启动恢复登录失败: %s", e)
            if not qq_ready:
                self._set_login_state(False, {}, provider='qq')

            # NetEase: 启动时恢复账号登录，失败回退匿名登录（保证搜索可用）。
            try:
                restored = self._restore_login_from_cache()
                if restored:
                    netease_ready = True
                else:
                    self._anonymous_login()
                    netease_ready = self.provider_logged_in('netease')
            except ImportError:
                logger.warning("[CloudMusic] pyncm 未安装")
                self._set_login_state(False, {}, provider='netease')
            except Exception as e:
                logger.error("[CloudMusic] 网易云启动登录失败: %s", e)
                self._set_login_state(False, {}, provider='netease')
        finally:
            self._login_ready.set()
            self._publish_login_status()
            current_provider = self._current_provider()
            current_logged_in = self.provider_logged_in(current_provider)
            logger.debug(
                "[CloudMusic] 启动登录流程结束: current=%s logged_in=%s netease=%s qq=%s kugou=%s dt=%.3fs",
                current_provider,
                current_logged_in,
                netease_ready,
                qq_ready,
                kugou_ready,
                time.monotonic() - t0,
            )
