from __future__ import annotations

import threading
from dataclasses import dataclass


DEFAULT_CHAT_HOTKEY = "Ctrl+Shift+L"

CHAT_HOTKEY_PRESETS: dict[str, str] = {
    "Ctrl+Shift+L": "<ctrl>+<shift>+l",
    "Ctrl+Shift+T": "<ctrl>+<shift>+t",
    "Ctrl+Alt+T": "<ctrl>+<alt>+t",
    "Alt+Shift+T": "<alt>+<shift>+t",
}


@dataclass(frozen=True)
class HotkeyCycleDecision:
    suppress: bool
    trigger: bool = False


class OneShotHotkeyLatch:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.is_down = False
        self.intercepting = False
        self.trigger_on_release = False
        self.trigger_queued = False

    def key_down(
        self,
        *,
        can_trigger: bool,
        block_only: bool = False,
    ) -> HotkeyCycleDecision:
        with self._lock:
            if not self.is_down:
                self.is_down = True
                self.intercepting = can_trigger or block_only
                self.trigger_on_release = can_trigger
            return HotkeyCycleDecision(suppress=self.intercepting)

    def key_up(self) -> HotkeyCycleDecision:
        with self._lock:
            if not self.is_down:
                return HotkeyCycleDecision(suppress=False)
            self.is_down = False
            if not self.intercepting:
                return HotkeyCycleDecision(suppress=False)

            should_trigger = (
                self.trigger_on_release
                and not self.trigger_queued
            )
            self.intercepting = False
            self.trigger_on_release = False
            if should_trigger:
                self.trigger_queued = True
            return HotkeyCycleDecision(
                suppress=True,
                trigger=should_trigger,
            )

    def mark_trigger_handled(self) -> None:
        with self._lock:
            self.trigger_queued = False

    def has_queued_trigger(self) -> bool:
        with self._lock:
            return self.trigger_queued


def normalize_chat_hotkey(value: object) -> str:
    label = str(value or "").strip()
    if label in CHAT_HOTKEY_PRESETS:
        return label
    return DEFAULT_CHAT_HOTKEY


def pynput_hotkey_spec(label: str) -> str:
    return CHAT_HOTKEY_PRESETS[normalize_chat_hotkey(label)]
