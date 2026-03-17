"""API client ???????????"""

from typing import Any

import requests


class _ApiClientCommonMixin:
    @staticmethod
    def _normalize_history_items(history: list[dict] | None) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for item in history or []:
            if not isinstance(item, dict):
                continue
            role = str(item.get('role', '')).strip().lower()
            content = str(item.get('content', '')).strip()
            if role not in ('user', 'assistant') or not content:
                continue
            normalized.append({'role': role, 'content': content})
        return normalized

    @staticmethod
    def _build_openai_history_messages(history: list[dict] | None) -> list[dict[str, str]]:
        return [
            {'role': item['role'], 'content': item['content']}
            for item in _ApiClientCommonMixin._normalize_history_items(history)
        ]

    @staticmethod
    def _build_generate_history_prompt(history: list[dict] | None, assistant_name: str) -> str:
        lines: list[str] = []
        for item in _ApiClientCommonMixin._normalize_history_items(history):
            speaker = '用户' if item['role'] == 'user' else assistant_name
            lines.append(f"{speaker}：{item['content']}")
        return '\n'.join(lines)

    @staticmethod
    def _iter_stream_lines(resp: requests.Response):
        """
        低延迟逐行读取流式响应。
        使用小 chunk 规避 requests 默认缓冲导致的"伪流式"。
        """
        for raw_line in resp.iter_lines(chunk_size=1, decode_unicode=False):
            if not raw_line:
                continue
            if isinstance(raw_line, bytes):
                line = raw_line.decode("utf-8", errors="ignore")
            else:
                line = str(raw_line)
            line = line.strip()
            if line:
                yield line

    @staticmethod
    def _close_response(resp: requests.Response | None):
        if resp is None:
            return
        try:
            resp.close()
        except Exception:
            pass
        sess = getattr(resp, "_snowrol_session", None)
        if sess is not None:
            try:
                sess.close()
            except Exception:
                pass

    @staticmethod
    def _request_once(method: str, url: str, *, trust_env: bool, **kwargs) -> requests.Response:
        sess = requests.Session()
        sess.trust_env = bool(trust_env)
        if not trust_env:
            try:
                sess.proxies.clear()
            except Exception:
                pass
        try:
            resp = sess.request(method=method, url=url, **kwargs)
            setattr(resp, "_snowrol_session", sess)
            return resp
        except Exception:
            try:
                sess.close()
            except Exception:
                pass
            raise

    @classmethod
    def _request_with_proxy_fallback(cls, method: str, url: str,
                                     *, disable_env_proxy: bool, **kwargs) -> requests.Response:
        if not disable_env_proxy:
            return cls._request_once(method, url, trust_env=True, **kwargs)
        last_error: Exception | None = None
        for trust_env in (False, True):
            try:
                return cls._request_once(method, url, trust_env=trust_env, **kwargs)
            except Exception as e:
                last_error = e
        if last_error is not None:
            raise last_error
        raise RuntimeError("request failed")

    @staticmethod
    def _normalize_openai_content(content: Any) -> str:
        """
        统一提取内容文本。

        兼容：
        - str
        - list[{"type":"text","text":"..."}]
        - list[{"text":"..."}]
        - 嵌套 list/dict
        """
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, (int, float)):
            return str(content)
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                text = _ApiClientCommonMixin._normalize_openai_content(item)
                if text:
                    parts.append(text)
            return "".join(parts)
        if isinstance(content, dict):
            for key in ("text", "content", "value", "output_text"):
                if key in content:
                    text = _ApiClientCommonMixin._normalize_openai_content(content.get(key))
                    if text:
                        return text
        return ""

    @staticmethod
    def _extract_openai_chunk_text(chunk: dict) -> str:
        """从流式 chunk 中提取文本，兼容多种 OpenAI 兼容实现。"""
        if not isinstance(chunk, dict):
            return ""

        # 兼容部分服务将实际数据再包一层 data
        data = chunk.get("data")
        if isinstance(data, dict):
            nested_text = _ApiClientCommonMixin._extract_openai_chunk_text(data)
            if nested_text:
                return nested_text

        choices = chunk.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0] if isinstance(choices[0], dict) else {}
            delta = first.get("delta") if isinstance(first, dict) else {}
            if not isinstance(delta, dict):
                delta = {}
            message = first.get("message") if isinstance(first, dict) else {}
            if not isinstance(message, dict):
                message = {}

            # 标准与常见兼容：优先从 delta 提取
            for key in ("content", "text", "output_text"):
                text = _ApiClientCommonMixin._normalize_openai_content(delta.get(key))
                if text:
                    return text

            # 某些实现将本块内容放在 message 字段
            for key in ("content", "text", "output_text"):
                text = _ApiClientCommonMixin._normalize_openai_content(message.get(key))
                if text:
                    return text

        # 少数兼容实现会返回这些字段
        for key in ("output_text", "response", "text"):
            text = _ApiClientCommonMixin._normalize_openai_content(chunk.get(key))
            if text:
                return text

        # DashScope / 其他网关常见 output 包装
        output = chunk.get("output")
        if isinstance(output, dict):
            for key in ("text", "content", "output_text"):
                text = _ApiClientCommonMixin._normalize_openai_content(output.get(key))
                if text:
                    return text

            output_choices = output.get("choices")
            if isinstance(output_choices, list) and output_choices:
                first = output_choices[0] if isinstance(output_choices[0], dict) else {}
                message = first.get("message") if isinstance(first, dict) else {}
                if isinstance(message, dict):
                    for key in ("content", "text", "output_text"):
                        text = _ApiClientCommonMixin._normalize_openai_content(message.get(key))
                        if text:
                            return text

        # 顶层 message 兜底
        message = chunk.get("message")
        if isinstance(message, dict):
            for key in ("content", "text", "output_text"):
                text = _ApiClientCommonMixin._normalize_openai_content(message.get(key))
                if text:
                    return text

        return ""
