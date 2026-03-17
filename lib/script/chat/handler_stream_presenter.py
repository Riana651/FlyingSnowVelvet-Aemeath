"""ChatHandler ????????????"""

import re

from config.config import BUBBLE_CONFIG, VOICE
from config.ollama_config import OLLAMA
from lib.core.event.center import Event, EventType
from lib.core.logger import get_logger
from lib.script.chat import bot_reply
from .handler_auto_companion import AUTO_COMPANION_PROMPT

logger = get_logger(__name__)

BUBBLE_MIN_TICKS = BUBBLE_CONFIG.get('default_min_ticks', 2)
BUBBLE_MAX_TICKS = BUBBLE_CONFIG.get('default_max_ticks', 100)
STREAM_FINAL_MIN_PER_CHAR = 3
STREAM_FINAL_MIN_CAP = 300
TOOL_MARKER_PATTERN = re.compile(r'###.*?###', re.S)
TOPIC_MARKER_PATTERN = re.compile(r'^\s*///\s*([^/\r\n]{1,32}?)\s*///\s*', re.S)
VOICE_SENTENCE_SPLIT_PATTERN = re.compile('(?<=[。！？!?…])')
VISION_KEYWORDS = [
    '看.*一.*眼|看看这|看那|看屏幕',
    '看.*(我的|这个)?.*屏幕',
    '看.*桌面',
    '看看.*桌面',
    '桌面.*(什么|情况|显示)',
    '查看.*桌面',
    '识别.*屏幕',
    '分析.*屏幕',
    '你能看到',
    '你看(得|到)?',
    '截图',
    '截.*屏',
    '屏幕(上|里).*(什么|显示)',
    '这是什么',
    '图片(里|中).*',
    '照片(里|中).*',
    '画面(里|中)',
    '你在(看|瞅).*什么',
    '帮我看看',
    '帮我(看|瞅)',
    '瞅.*一.*眼|瞅瞅',
    '瞧.*一.*眼|瞧瞧',
    'look.*screen',
    'see.*screen',
    'show.*screen',
    'what.?s.*screen',
    'look.*desktop',
    'check.*desktop',
    'see.*desktop',
    'take.*screenshot',
    'screen.?shot',
    'screen.?capture',
    'capture.*screen',
    'screenshot',
    'record.*screen',
    'analy[sz]e.*screen',
    'what.*on.*desktop',
]


def _should_capture_screen(text: str) -> bool:
    """
    检查用户消息是否触发视觉请求。

    Args:
        text: 用户输入文本

    Returns:
        是否应该截图并发送给模型
    """
    normalized = str(text or "")
    condensed = re.sub(r"\s+", "", normalized)
    for pattern in VISION_KEYWORDS:
        if re.search(pattern, normalized, re.IGNORECASE):
            return True
        if condensed and condensed != normalized and re.search(pattern, condensed, re.IGNORECASE):
            return True
    return False

def _strip_tool_commands_for_display(text: str) -> str:
    """
    移除模型回复中的工具命令标记，避免用户看到 ###命令###。

    仅用于气泡显示；工具调度仍应使用原始文本。
    """
    if not text:
        return ""

    normalized = text.replace('＃', '#').replace('／', '/')
    cleaned = TOOL_MARKER_PATTERN.sub('', normalized)

    # 流式场景下可能出现未闭合命令片段（尾部 "###..."），直接截断尾部。
    tail_marker = cleaned.rfind('###')
    if tail_marker >= 0:
        cleaned = cleaned[:tail_marker]

    # 消除主题标记：模型可输出 ///主题///正文；气泡仅展示正文。
    topic_match = TOPIC_MARKER_PATTERN.match(cleaned)
    if topic_match:
        cleaned = cleaned[topic_match.end():]
    else:
        stripped = cleaned.lstrip()
        if stripped.startswith('///'):
            # 流式首段可能暂时未闭合 ///主题///，在闭合前不展示，避免闪烁。
            closed_at = stripped.find('///', 3)
            if closed_at < 0:
                return ''

    cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()

def _build_ai_voice_text(text: str) -> str:
    max_chars = int(OLLAMA.get("ai_voice_max_chars", 40))
    cleaned = _strip_tool_commands_for_display(str(text or ""))
    if not cleaned:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned

    first_sentence = VOICE_SENTENCE_SPLIT_PATTERN.split(cleaned, maxsplit=1)[0].strip()
    if first_sentence and len(first_sentence) <= max_chars:
        logger.debug("[ChatHandler] AI 语音超长，已截取首句（%d -> %d 字）", len(cleaned), len(first_sentence))
        return first_sentence

    truncated = cleaned[:max_chars].rstrip('，,。.!?！？；;、 ')
    if truncated:
        logger.debug("[ChatHandler] AI 语音超长，已截断到最大长度（%d -> %d 字）", len(cleaned), len(truncated))
    return truncated

class ChatHandlerStreamPresenterMixin:
    def _on_stream_chunk(self, accumulated_text: str):
        """
        流式块回调：将逐步累积的回复文本更新到气泡框。

        每个 chunk 以 min=0tick(即时) / max=100tick(5s) 显示；
        下一个 chunk 到来时自动替换当前气泡，形成打字机效果；
        最后一个 chunk 的气泡保持直至 max 计时到期后自然消失。

        particle 策略：首个 chunk 替换"..."等待气泡时触发上淡出粒子；
                       后续 chunk 静默更新文本，不重复产生粒子。
        """
        if self._stream_first_chunk:
            display_text = _strip_tool_commands_for_display(accumulated_text)
            self._stream_last_display = display_text
            logger.debug("[ChatHandler] 收到首个流式分片（累计 %d 字）", len(display_text))
            self._stream_first_chunk = False
            self._event_center.publish(Event(EventType.INFORMATION, {
                "text":     display_text,
                "min":      0,
                "max":      100,
                "particle": True,
                "force_replace": True,
            }))
            return

        self._stream_pending_raw = accumulated_text
        if not self._stream_flush_timer.isActive():
            self._stream_flush_timer.start(40)

    def _flush_stream_chunk(self):
        if not self._stream_pending_raw:
            return
        display_text = _strip_tool_commands_for_display(self._stream_pending_raw)
        self._stream_pending_raw = ""
        if display_text == self._stream_last_display:
            return
        self._stream_last_display = display_text
        self._event_center.publish(Event(EventType.INFORMATION, {
            "text":     display_text,
            "min":      0,
            "max":      100,
            "particle": False,
            "force_replace": True,
        }))

    @staticmethod
    def _calc_stream_final_min_ticks(text: str) -> int:
        """流式最终气泡 min：每字 3 tick，封顶 300 tick。"""
        char_count = len((text or "").strip())
        dynamic_min = min(char_count * STREAM_FINAL_MIN_PER_CHAR, STREAM_FINAL_MIN_CAP)
        return max(BUBBLE_MIN_TICKS, dynamic_min)

    def _publish_response(self, text: str, user_text: str | None = None, include_history: bool = True):
        """
        最终回调：处理流式请求的完成信号。
        - text 非空：流式块已由 _on_stream_chunk 逐步发布，无需重复
        - text 为空：所有模型均失败（或 Ollama 未启动），使用 bot_reply 预设回复兜底
        """
        if self._stream_flush_timer.isActive():
            self._stream_flush_timer.stop()
        if self._stream_pending_raw:
            self._flush_stream_chunk()

        if not text:
            # 所有模型失败或服务不可用：用关键词匹配原始消息，退回角色内预设回复
            text = bot_reply.get_reply(self._last_message)
            display_text = _strip_tool_commands_for_display(text)
            self._event_center.publish(Event(EventType.INFORMATION, {
                "text": display_text,
                "min":  BUBBLE_MIN_TICKS,
                "max":  BUBBLE_MAX_TICKS,
            }))
            logger.info("[ChatHandler] 降级回复: %s", text[:60])
        else:
            logger.debug("[ChatHandler] Final raw reply: %s", text[:160].replace('\n', '\\n'))
            display_text = _strip_tool_commands_for_display(text)
            final_min_ticks = self._calc_stream_final_min_ticks(display_text)
            final_max_ticks = max(BUBBLE_MAX_TICKS, final_min_ticks)

            if self._stream_first_chunk:
                # 兜底：若底层返回了完整文本但未触发任何 chunk，则回填最终气泡，
                # 避免用户只看到等待中的 "..."。
                self._event_center.publish(Event(EventType.INFORMATION, {
                    "text": display_text,
                    "min":  final_min_ticks,
                    "max":  final_max_ticks,
                }))
                logger.warning("[ChatHandler] 未收到流式分片，已回填最终回复（%d 字，min=%d）",
                               len(display_text), final_min_ticks)
            else:
                # 流式完成后重发同文最终气泡，应用按字数计算的 min（静默替换，无粒子）。
                self._event_center.publish(Event(EventType.INFORMATION, {
                    "text": display_text,
                    "min":  final_min_ticks,
                    "max":  final_max_ticks,
                    "particle": False,
                }))
                logger.debug("[ChatHandler] 流式响应完毕（共 %d 字，final_min=%d）",
                             len(display_text), final_min_ticks)

            voice_text = _build_ai_voice_text(display_text)
            if voice_text:
                self._event_center.publish(Event(EventType.AI_VOICE_REQUEST, {
                    "text": voice_text,
                    "interruptible": True,
                    # 实际语音音量由 VoiceCore 中的 VOICE.voice_volume 控制。
                    "voice_volume": VOICE.get("voice_volume", 1.0),
                }))

        if include_history:
            effective_user = str(user_text or self._last_message or '').strip()
            if effective_user:
                self._append_recent_context('user', effective_user)
            self._append_recent_context('assistant', text)

        # 无论成功还是降级，均发布最终文本供工具调度器处理
        self._event_center.publish(Event(EventType.STREAM_FINAL, {"text": text}))

    def _publish_auto_response(self, text: str, include_history: bool = False):
        """
        自动陪伴回调：显示气泡，并复用 STREAM_FINAL 管道识别 ###工具指令###。
        使用与流式回复结束相同的 min_ticks 计算逻辑（按字数计算，防顶出保护）。
        """
        raw_text = text
        from_ai = bool(raw_text)
        if not raw_text:
            raw_text = bot_reply.get_reply(AUTO_COMPANION_PROMPT)
        display_text = _strip_tool_commands_for_display(raw_text)
        
        # 使用与流式回复结束相同的 min_ticks 计算逻辑
        final_min_ticks = self._calc_stream_final_min_ticks(display_text)
        final_max_ticks = max(BUBBLE_MAX_TICKS, final_min_ticks)
        
        self._event_center.publish(Event(EventType.INFORMATION, {
            "text": display_text,
            "min":  final_min_ticks,
            "max":  final_max_ticks,
        }))
        voice_text = _build_ai_voice_text(display_text) if from_ai else ""
        if voice_text:
            self._event_center.publish(Event(EventType.AI_VOICE_REQUEST, {
                "text": voice_text,
                "interruptible": True,
                "voice_volume": VOICE.get("voice_volume", 1.0),
            }))
        if include_history and from_ai:
            self._append_recent_context('assistant', raw_text)
        self._event_center.publish(Event(EventType.STREAM_FINAL, {"text": raw_text}))
        logger.debug("[ChatHandler] 自动陪伴回复（%d 字，min=%d）: %s",
                     len(display_text), final_min_ticks, display_text[:60])

