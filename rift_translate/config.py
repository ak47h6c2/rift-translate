from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from rift_translate.hotkeys import DEFAULT_CHAT_HOTKEY, normalize_chat_hotkey


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env.local"
SETTINGS_FILE = PROJECT_ROOT / ".rift_translate_settings.json"

load_dotenv(ENV_FILE)


@dataclass(slots=True)
class ChatRegion:
    left: int
    top: int
    width: int
    height: int

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ChatRegion | None":
        if not value:
            return None
        try:
            region = cls(
                left=int(value["left"]),
                top=int(value["top"]),
                width=int(value["width"]),
                height=int(value["height"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
        if region.width < 40 or region.height < 30:
            return None
        return region


@dataclass(slots=True)
class AppSettings:
    text_model: str = field(
        default_factory=lambda: os.getenv("OPENAI_TEXT_MODEL", "gpt-5.6-luna")
    )
    transcription_model: str = field(
        default_factory=lambda: os.getenv(
            "OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe"
        )
    )
    auto_copy: bool = True
    overlay_enabled: bool = True
    chat_hotkey: str = DEFAULT_CHAT_HOTKEY
    chat_region: ChatRegion | None = None

    @classmethod
    def load(cls) -> "AppSettings":
        settings = cls()
        if not SETTINGS_FILE.exists():
            return settings

        try:
            payload = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return settings

        if isinstance(payload.get("text_model"), str):
            settings.text_model = payload["text_model"]
        if isinstance(payload.get("transcription_model"), str):
            settings.transcription_model = payload["transcription_model"]
        if isinstance(payload.get("auto_copy"), bool):
            settings.auto_copy = payload["auto_copy"]
        if isinstance(payload.get("overlay_enabled"), bool):
            settings.overlay_enabled = payload["overlay_enabled"]
        settings.chat_hotkey = normalize_chat_hotkey(payload.get("chat_hotkey"))
        settings.chat_region = ChatRegion.from_dict(payload.get("chat_region"))
        return settings

    def save(self) -> None:
        SETTINGS_FILE.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def has_api_key() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())
