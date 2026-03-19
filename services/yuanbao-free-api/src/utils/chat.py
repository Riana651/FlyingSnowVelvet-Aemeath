"""聊天相关工具函数模块"""

import json
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from src.const import MODEL_MAPPING
from src.schemas.chat import ChatCompletionChunk, Choice, ChoiceDelta, Message


def get_model_info(model_name: str) -> Optional[Dict]:
    """获取模型信息

    Args:
        model_name: 模型名称

    Returns:
        Optional[Dict]: 模型映射信息，不存在返回 None
    """
    return MODEL_MAPPING.get(model_name.lower(), None)


def _extract_message_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (int, float)):
        return str(content)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = _extract_message_text(item)
            if text:
                parts.append(text)
        return "".join(parts)
    if isinstance(content, dict):
        item_type = str(content.get("type") or "").strip().lower()
        if item_type in ("image_url", "input_image"):
            return ""
        for key in ("text", "content", "value", "output_text", "msg"):
            if key in content:
                text = _extract_message_text(content.get(key))
                if text:
                    return text
    return ""


def parse_messages(messages: List[Message]) -> str:
    """解析消息列表为提示词

    Args:
        messages: 消息列表

    Returns:
        str: 解析后的提示词
    """
    only_user_message = True
    for m in messages:
        if m.role != "user":
            only_user_message = False
            break
    if only_user_message:
        prompt = "\n".join([f"{m.role}: {_extract_message_text(m.content)}" for m in messages])
    else:
        prompt = "\n".join([_extract_message_text(m.content) for m in messages])
    return prompt


async def process_response_stream(response: httpx.Response, model_id: str) -> AsyncGenerator[str, None]:
    """处理响应流，转换为 OpenAI 格式

    Args:
        response: HTTP 响应对象
        model_id: 模型 ID

    Yields:
        str: SSE 格式的数据块
    """

    def _create_chunk(content: str, finish_reason: Optional[str] = None) -> str:
        choice_delta = ChoiceDelta(content=content)
        choice = Choice(delta=choice_delta, finish_reason=finish_reason)
        chunk = ChatCompletionChunk(created=int(time.time()), model=model_id, choices=[choice])
        return chunk.model_dump_json(exclude_unset=True)

    def _extract_text_content(payload) -> str:
        if isinstance(payload, list):
            return "".join(_extract_text_content(item) for item in payload)
        if not isinstance(payload, dict):
            return ""

        payload_type = str(payload.get("type") or "").strip().lower()
        if payload_type == "text":
            return str(payload.get("msg") or "")

        content = payload.get("content")
        if isinstance(content, (dict, list)):
            return _extract_text_content(content)
        return ""

    def _normalize_stream_content(previous_text: str, content: str) -> tuple[str, str]:
        if not content:
            return previous_text, ""
        if not previous_text:
            return content, content
        if content == previous_text:
            return previous_text, ""
        if content.startswith(previous_text):
            return content, content[len(previous_text) :]
        if previous_text.endswith(content):
            return previous_text, ""
        if len(content) >= 4 and previous_text.startswith(content):
            return previous_text, ""

        max_overlap = min(len(previous_text), len(content))
        for overlap in range(max_overlap, 0, -1):
            if previous_text.endswith(content[:overlap]):
                delta = content[overlap:]
                return previous_text + delta, delta
        return previous_text + content, content

    start_word = "data: "
    finish_reason = "stop"
    accumulated_text = ""
    async for line in response.aiter_lines():
        if not line or not line.startswith(start_word):
            continue
        data: str = line[len(start_word) :]

        if data == "[DONE]":
            yield _create_chunk("", finish_reason)
            yield "[DONE]"
            break
        elif not data.startswith("{"):
            continue

        chunk_data: Dict = json.loads(data)
        if chunk_data.get("stopReason"):
            finish_reason = chunk_data["stopReason"]
        content = _extract_text_content(chunk_data)
        if content:
            accumulated_text, delta = _normalize_stream_content(accumulated_text, content)
            if delta:
                yield _create_chunk(delta)
