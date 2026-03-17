"""API client ???????"""

import json
from typing import Any

import requests


class _ApiClientErrorMixin:
    @staticmethod
    def _to_error_text(value: Any) -> str:
        """将错误对象稳定转换为可展示文本。"""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float, bool)):
            return str(value)
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)

    @staticmethod
    def _extract_error(http_err: requests.HTTPError) -> str:
        """
        从 HTTPError 中提取 Ollama 返回的实际错误描述。

        优先级：response JSON ["error"] > response text > str(http_err)
        确保即使响应正文为空也能返回有意义的文本。
        """
        response = getattr(http_err, "response", None)
        if response is not None:
            try:
                body = response.json()
                if isinstance(body, dict):
                    for key in ("error", "message", "msg", "detail", "details"):
                        if key in body:
                            text = _ApiClientErrorMixin._to_error_text(body.get(key)).strip()
                            if text:
                                return text
                text = _ApiClientErrorMixin._to_error_text(body).strip()
                if text:
                    return text
            except Exception:
                pass

            try:
                text = str(response.text or "").strip()
                if text:
                    return text[:300]
            except Exception:
                pass
        return str(http_err)
