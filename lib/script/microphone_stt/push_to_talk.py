"""Push-to-talk hotkey integration for the microphone STT service."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from PyQt5.QtCore import Qt

from config.config import VOICE
from lib.core.event.center import Event, EventType, get_event_center
from lib.core.logger import get_logger

_MODIFIER_MASK = int(Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)
_MODIFIER_TOKENS: dict[str, int] = {
    "CTRL": int(Qt.ControlModifier),
    "CONTROL": int(Qt.ControlModifier),
    "SHIFT": int(Qt.ShiftModifier),
    "ALT": int(Qt.AltModifier),
    "OPTION": int(Qt.AltModifier),
    "WIN": int(Qt.MetaModifier),
    "CMD": int(Qt.MetaModifier),
    "META": int(Qt.MetaModifier),
    "SUPER": int(Qt.MetaModifier),
}
_SPECIAL_KEYS: dict[str, int] = {
    "SPACE": Qt.Key_Space,
    "TAB": Qt.Key_Tab,
    "ENTER": Qt.Key_Return,
    "RETURN": Qt.Key_Return,
    "ESC": Qt.Key_Escape,
    "ESCAPE": Qt.Key_Escape,
    "BACKSPACE": Qt.Key_Backspace,
    "DELETE": Qt.Key_Delete,
    "INS": Qt.Key_Insert,
    "INSERT": Qt.Key_Insert,
    "HOME": Qt.Key_Home,
    "END": Qt.Key_End,
    "PGUP": Qt.Key_PageUp,
    "PAGEUP": Qt.Key_PageUp,
    "PGDN": Qt.Key_PageDown,
    "PAGEDOWN": Qt.Key_PageDown,
    "UP": Qt.Key_Up,
    "DOWN": Qt.Key_Down,
    "LEFT": Qt.Key_Left,
    "RIGHT": Qt.Key_Right,
}


@dataclass(frozen=True)
class HotkeyBinding:
    """Parsed push-to-talk hotkey information."""

    key: int
    modifiers: int
    display: str

    def matches(self, key_code: int, modifiers) -> bool:
        if key_code != self.key:
            return False
        return _normalize_modifiers(modifiers) == self.modifiers


def _normalize_modifiers(modifiers) -> int:
    try:
        value = int(modifiers)
    except Exception:
        value = 0
    return value & _MODIFIER_MASK


def _resolve_letter_or_digit(token: str) -> Optional[int]:
    if len(token) != 1:
        return None
    if "A" <= token <= "Z":
        return int(getattr(Qt, f"Key_{token}"))
    if "0" <= token <= "9":
        return int(getattr(Qt, f"Key_{token}"))
    return None


def _resolve_function_key(token: str) -> Optional[int]:
    if not token.startswith("F"):
        return None
    suffix = token[1:]
    if not suffix.isdigit():
        return None
    index = int(suffix)
    if not 1 <= index <= 24:
        return None
    return getattr(Qt, f"Key_F{index}")


def _resolve_key_code(token: str) -> Optional[int]:
    letter_or_digit = _resolve_letter_or_digit(token)
    if letter_or_digit is not None:
        return letter_or_digit

    special = _SPECIAL_KEYS.get(token)
    if special is not None:
        return int(special)

    function_key = _resolve_function_key(token)
    if function_key is not None:
        return int(function_key)
    return None


def parse_hotkey_binding(text: str) -> Optional[HotkeyBinding]:
    """Parse a textual hotkey definition (e.g. ``Ctrl+Shift+V``)."""
    normalized = str(text or "").strip()
    if not normalized:
        return None

    tokens = [tok for tok in re.split(r"[+\s]+", normalized) if tok]
    if not tokens:
        return None

    key_token = tokens[-1].upper()
    modifier_tokens = [tok.upper() for tok in tokens[:-1]]

    modifiers = 0
    for modifier in modifier_tokens:
        mapped = _MODIFIER_TOKENS.get(modifier)
        if mapped is None:
            return None
        modifiers |= mapped

    key_code = _resolve_key_code(key_token)
    if key_code is None:
        return None

    display_tokens = modifier_tokens + [key_token]
    display = "+".join(display_tokens)
    return HotkeyBinding(key=key_code, modifiers=modifiers, display=display)


class MicrophonePushToTalkHotkey:
    """Listen for the configured hotkey and control microphone STT."""

    def __init__(self) -> None:
        self._logger = get_logger(__name__)
        self._event_center = get_event_center()
        self._binding = self._load_binding()
        self._subscriptions_active = False
        self._session_active = False

        if self._binding is not None:
            self._subscribe()
        else:
            self._logger.info("[MicPushToTalk] Hotkey disabled or not configured.")

    def _load_binding(self) -> Optional[HotkeyBinding]:
        raw_value = str(VOICE.get("microphone_push_to_talk_key", "") or "").strip()
        if not raw_value:
            return None
        binding = parse_hotkey_binding(raw_value)
        if binding is None:
            self._logger.warning("[MicPushToTalk] Invalid hotkey: %r", raw_value)
        else:
            self._logger.info("[MicPushToTalk] Push-to-talk hotkey: %s", binding.display)
        return binding

    def _subscribe(self) -> None:
        if self._subscriptions_active:
            return
        self._event_center.subscribe(EventType.KEY_PRESS, self._on_key_press)
        self._event_center.subscribe(EventType.KEY_RELEASE, self._on_key_release)
        self._event_center.subscribe(EventType.MIC_STT_STATE_CHANGE, self._on_stt_state_change)
        self._subscriptions_active = True

    def cleanup(self) -> None:
        if not self._subscriptions_active:
            return
        self._event_center.unsubscribe(EventType.KEY_PRESS, self._on_key_press)
        self._event_center.unsubscribe(EventType.KEY_RELEASE, self._on_key_release)
        self._event_center.unsubscribe(EventType.MIC_STT_STATE_CHANGE, self._on_stt_state_change)
        self._subscriptions_active = False
        self._session_active = False

    def _on_key_press(self, event: Event) -> None:
        if self._binding is None:
            return
        if event.data.get("is_auto_repeat"):
            return

        key_code = int(event.data.get("key", 0))
        modifiers = event.data.get("modifiers", Qt.NoModifier)
        if not self._binding.matches(key_code, modifiers):
            return

        self._session_active = True
        self._logger.debug("[MicPushToTalk] Hotkey pressed, starting STT session.")
        self._event_center.publish(Event(EventType.MIC_STT_START, {
            "source": "microphone_push_to_talk",
            "auto_mode": False,
            "auto_submit": True,
            "emit_partial": True,
        }))

    def _on_key_release(self, event: Event) -> None:
        if not self._session_active or self._binding is None:
            return

        key_code = int(event.data.get("key", 0))
        modifiers = event.data.get("modifiers", Qt.NoModifier)
        if not self._binding.matches(key_code, modifiers):
            return

        self._session_active = False
        self._logger.debug("[MicPushToTalk] Hotkey released, stopping STT session.")
        self._event_center.publish(Event(EventType.MIC_STT_STOP, {
            "source": "microphone_push_to_talk",
        }))

    def _on_stt_state_change(self, event: Event) -> None:
        if not self._session_active:
            return
        if event.data.get("is_listening"):
            return
        self._logger.debug("[MicPushToTalk] STT stopped externally, resetting session state.")
        self._session_active = False


_push_to_talk_instance: Optional[MicrophonePushToTalkHotkey] = None


def get_microphone_push_to_talk_manager() -> MicrophonePushToTalkHotkey:
    global _push_to_talk_instance
    if _push_to_talk_instance is None:
        _push_to_talk_instance = MicrophonePushToTalkHotkey()
    return _push_to_talk_instance


def cleanup_microphone_push_to_talk_manager() -> None:
    global _push_to_talk_instance
    if _push_to_talk_instance is not None:
        _push_to_talk_instance.cleanup()
        _push_to_talk_instance = None
