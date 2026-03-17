"""???????????????"""

import base64
import binascii
import json
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from lib.core.logger import get_logger

logger = get_logger(__name__)

_MAX_WIDTH_720P = 1280
_MAX_HEIGHT_720P = 720
_JPEG_QUALITY = 85

try:
    _RESAMPLE_LANCZOS = Image.Resampling.LANCZOS
except AttributeError:
    _RESAMPLE_LANCZOS = Image.LANCZOS


def _fit_size_to_720p(width: int, height: int) -> tuple[int, int]:
    """按图片方向缩放到 720p 边界框内，保持纵横比。"""
    if width <= 0 or height <= 0:
        return width, height

    if width >= height:
        max_width, max_height = _MAX_WIDTH_720P, _MAX_HEIGHT_720P
    else:
        max_width, max_height = _MAX_HEIGHT_720P, _MAX_WIDTH_720P

    if width <= max_width and height <= max_height:
        return width, height

    ratio = min(max_width / float(width), max_height / float(height))
    new_width = max(1, int(width * ratio))
    new_height = max(1, int(height * ratio))
    return new_width, new_height

def _to_rgb_without_alpha(image: Image.Image) -> Image.Image:
    """统一转为 RGB；透明像素以白底合成，避免 JPEG 丢失 alpha 造成黑底。"""
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    if image.mode != "RGB":
        return image.convert("RGB")
    return image

def _compress_image_bytes_720p(image_data: bytes) -> bytes | None:
    """
    将图片压缩到 720p 边界并转为 JPEG。

    返回:
        压缩后的 JPEG 字节；若输入非可识别图片则返回 None。
    """
    if not image_data:
        return None

    source_size = len(image_data)
    try:
        with Image.open(BytesIO(image_data)) as image:
            image.load()
            src_w, src_h = image.size
            dst_w, dst_h = _fit_size_to_720p(src_w, src_h)

            if (dst_w, dst_h) != (src_w, src_h):
                image = image.resize((dst_w, dst_h), _RESAMPLE_LANCZOS)
            rgb_image = _to_rgb_without_alpha(image)

            output = BytesIO()
            rgb_image.save(
                output,
                format="JPEG",
                quality=_JPEG_QUALITY,
                optimize=True,
                progressive=True,
            )
            result = output.getvalue()
            logger.debug(
                "[Vision] 图片压缩完成: %dx%d -> %dx%d, %d -> %d bytes",
                src_w,
                src_h,
                rgb_image.width,
                rgb_image.height,
                source_size,
                len(result),
            )
            return result
    except (UnidentifiedImageError, OSError):
        return None
    except Exception as e:
        logger.warning("[Vision] 图片压缩失败，回退原始数据: %s", e)
        return None

def _decode_base64_payload(text: str) -> bytes | None:
    """尽量宽松地解码 base64 文本，失败返回 None。"""
    if not text:
        return None

    cleaned = "".join(text.split())
    if not cleaned:
        return None

    padding = (-len(cleaned)) % 4
    if padding:
        cleaned += "=" * padding

    try:
        return base64.b64decode(cleaned, validate=False)
    except (binascii.Error, ValueError):
        try:
            return base64.urlsafe_b64decode(cleaned)
        except (binascii.Error, ValueError):
            return None

def _compress_base64_payload(text: str) -> str | None:
    """将 base64 文本对应图片压缩到 720p，成功返回新的 base64。"""
    raw = _decode_base64_payload(text)
    if raw is None:
        return None

    compressed = _compress_image_bytes_720p(raw)
    if compressed is None:
        return None

    return base64.b64encode(compressed).decode("utf-8")

def _extract_data_url_payload(text: str) -> str:
    """提取 data URL 中的 base64 载荷，非 data URL 原样返回。"""
    if text.startswith("data:") and "," in text:
        return text.split(",", 1)[1].strip()
    return text

def _encoded_image_stats(encoded_text: str) -> tuple[int | None, int | None, int | None]:
    """
    根据最终发送的 base64 文本提取图片统计信息。

    Returns:
        (size_bytes, width, height)，任一项不可用时返回 None。
    """
    raw = _decode_base64_payload(encoded_text)
    if raw is None:
        return None, None, None

    size_bytes = len(raw)
    try:
        with Image.open(BytesIO(raw)) as image:
            image.load()
            width, height = image.size
            if width > 0 and height > 0:
                return size_bytes, int(width), int(height)
    except Exception:
        pass
    return size_bytes, None, None

def _estimate_image_tokens(width: int, height: int) -> int:
    """按 14x14 像素块估算图片 token 数。"""
    return ((max(1, int(width)) + 13) // 14) * ((max(1, int(height)) + 13) // 14)

def image_to_base64(image_data: bytes) -> str:
    """
    将图片字节数据压缩到 720p 后转换为 base64 字符串（用于多模态请求）。

    Args:
        image_data: 图片字节数据

    Returns:
        base64 编码字符串
    """
    compressed = _compress_image_bytes_720p(image_data)
    payload = compressed if compressed is not None else image_data
    return base64.b64encode(payload).decode("utf-8")

def images_to_ollama_payload(images: list | None) -> list[str]:
    """
    将图片列表转换为 Ollama 可接受的 JSON 载荷格式（base64 字符串数组）。
    支持输入 bytes / bytearray / str（含 data URL）。
    """
    if not images:
        return []

    result: list[str] = []
    total_size = 0
    sized_count = 0
    total_tokens = 0
    tokened_count = 0

    for item in images:
        encoded_payload: str | None = None
        if isinstance(item, (bytes, bytearray)):
            encoded_payload = image_to_base64(bytes(item))
        elif isinstance(item, str):
            text = item.strip()
            if not text:
                continue

            # 兼容 data URL：data:image/png;base64,xxxx
            text = _extract_data_url_payload(text)
            compressed = _compress_base64_payload(text)
            encoded_payload = compressed if compressed else text
        else:
            logger.warning("[Vision] 忽略不支持的图片类型: %s", type(item).__name__)
            continue

        result.append(encoded_payload)
        size_bytes, width, height = _encoded_image_stats(encoded_payload)
        if size_bytes is None:
            logger.warning(
                "[Vision] Ollama 图片[%d] 大小无法估算（base64 长度=%d）",
                len(result),
                len(encoded_payload),
            )
            continue

        sized_count += 1
        total_size += size_bytes
        if width is not None and height is not None:
            tokens = _estimate_image_tokens(width, height)
            total_tokens += tokens
            tokened_count += 1
            logger.info(
                "[Vision] Ollama 图片[%d] 发送大小: %d bytes, 分辨率: %dx%d, 估算token: %d",
                len(result),
                size_bytes,
                width,
                height,
                tokens,
            )
        else:
            logger.info(
                "[Vision] Ollama 图片[%d] 发送大小: %d bytes（分辨率不可解析，token无法估算）",
                len(result),
                size_bytes,
            )

    if result:
        logger.info(
            "[Vision] Ollama 图片总大小: %d bytes（可估算 %d/%d 张）",
            total_size,
            sized_count,
            len(result),
        )
        logger.info(
            "[Vision] Ollama 图片估算token总数: %d（可估算 %d/%d 张，规则: 每14x14像素块=1 token）",
            total_tokens,
            tokened_count,
            len(result),
        )

    return result

def images_to_openai_content(images: list | None) -> list[dict]:
    """
    将图片列表转换为 OpenAI 兼容 content 块列表。
    支持 bytes/base64/data-url/http(s) URL。
    """
    if not images:
        return []

    content_blocks: list[dict] = []
    total_size = 0
    sized_count = 0
    total_tokens = 0
    tokened_count = 0

    for item in images:
        encoded_payload_for_stat: str | None = None
        if isinstance(item, (bytes, bytearray)):
            # bytes 路径统一压缩为 JPEG 数据
            encoded = image_to_base64(bytes(item))
            url = f"data:image/jpeg;base64,{encoded}"
            encoded_payload_for_stat = encoded
        elif isinstance(item, str):
            text = item.strip()
            if not text:
                continue

            if text.startswith("http://") or text.startswith("https://"):
                url = text
            elif text.startswith("data:image/"):
                raw_payload = _extract_data_url_payload(text)
                compressed = _compress_base64_payload(raw_payload)
                if compressed:
                    url = f"data:image/jpeg;base64,{compressed}"
                    encoded_payload_for_stat = compressed
                else:
                    url = text
                    encoded_payload_for_stat = raw_payload
            else:
                # 视为裸 base64 字符串，尝试压缩
                compressed = _compress_base64_payload(text)
                if compressed:
                    url = f"data:image/jpeg;base64,{compressed}"
                    encoded_payload_for_stat = compressed
                else:
                    url = f"data:image/png;base64,{text}"
                    encoded_payload_for_stat = text
        else:
            logger.warning("[Vision] OpenAI 载荷忽略不支持的图片类型: %s", type(item).__name__)
            continue

        content_blocks.append({
            "type":      "image_url",
            "image_url": {"url": url},
        })

        size_bytes = None
        width = None
        height = None
        if encoded_payload_for_stat is not None:
            size_bytes, width, height = _encoded_image_stats(encoded_payload_for_stat)

        if size_bytes is None:
            logger.warning(
                "[Vision] OpenAI 图片[%d] 大小无法估算（可能为远程 URL）",
                len(content_blocks),
            )
            continue

        sized_count += 1
        total_size += size_bytes
        if width is not None and height is not None:
            tokens = _estimate_image_tokens(width, height)
            total_tokens += tokens
            tokened_count += 1
            logger.info(
                "[Vision] OpenAI 图片[%d] 发送大小: %d bytes, 分辨率: %dx%d, 估算token: %d",
                len(content_blocks),
                size_bytes,
                width,
                height,
                tokens,
            )
        else:
            logger.info(
                "[Vision] OpenAI 图片[%d] 发送大小: %d bytes（分辨率不可解析，token无法估算）",
                len(content_blocks),
                size_bytes,
            )

    if content_blocks:
        logger.info(
            "[Vision] OpenAI 图片总大小: %d bytes（可估算 %d/%d 张）",
            total_size,
            sized_count,
            len(content_blocks),
        )
        logger.info(
            "[Vision] OpenAI 图片估算token总数: %d（可估算 %d/%d 张，规则: 每14x14像素块=1 token）",
            total_tokens,
            tokened_count,
            len(content_blocks),
        )

    return content_blocks

def is_image_input_error(error_text) -> bool:
    """
    判断错误是否由图像输入不兼容导致。
    """
    if not error_text:
        return False

    if isinstance(error_text, str):
        text = error_text.lower()
    else:
        try:
            text = json.dumps(error_text, ensure_ascii=False).lower()
        except Exception:
            try:
                text = str(error_text).lower()
            except Exception:
                return False
    image_markers = (
        "image", "images", "vision", "multimodal", "multi-modal",
        "图像", "图片", "视觉",
    )
    error_markers = (
        "does not support", "not support", "unsupported",
        "cannot unmarshal", "invalid", "format", "expect",
        "不支持", "无效", "格式",
    )
    return any(m in text for m in image_markers) and any(m in text for m in error_markers)
