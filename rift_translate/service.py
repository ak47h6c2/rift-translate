from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

from openai import OpenAI

from rift_translate.config import AppSettings
from rift_translate.glossary import compact_glossary, find_terms


VOICE_INSTRUCTIONS = """
Translate Mandarin spoken by a Chinese League of Legends player into concise,
natural English suitable for team chat. Use real League terminology rather than
literal translations. Keep the tactical intent, timings, subjects, and negations.
Prefer one short sentence and never exceed 180 characters. Do not add explanations,
quotation marks, markdown, or insults that the player did not say. Use plain ASCII
characters, keep the output on one line, and never start it with a slash command.
""".strip()

CHAT_INSTRUCTIONS = """
You explain English League of Legends chat to a Chinese player. Understand
abbreviations, role names, server slang, sarcasm, tactical calls, and toxicity in
context. Translate the intended game meaning instead of translating word by word.
Do not amplify insults.

Treat summoner names, Riot IDs, clan tags, champion names, and chat-channel labels
as identifiers, not text to translate. When a line has a speaker prefix, copy the
summoner name or Riot ID exactly into "speaker". Never translate, transliterate,
spell-correct, or include that identifier in "chinese". Put only the actual message
content in "original". If the speaker is unclear, use an empty string instead of
guessing.

Return JSON only, with this exact shape:
{
  "lines": [
    {
      "speaker": "exact visible summoner name or empty string",
      "original": "message text only, without speaker/channel prefix",
      "chinese": "one concise natural Chinese chat line",
      "tone": "neutral|positive|shotcall|sarcastic|toxic",
      "notes": "only essential slang/context explanation, or empty string"
    }
  ],
  "summary": "optional one-sentence situation summary",
  "terms": [{"term": "abbreviation", "meaning": "Chinese explanation"}],
  "reply_suggestion": "optional concise English reply, or empty string"
}
Keep each Chinese line short and immediately readable during a match. Avoid
repeating the same explanation in notes, summary, and terms. Use at most three
terms. Only include a summary when several lines together imply a useful tactical
situation. Never invent chat lines or speaker names that are not in the input.
""".strip()


def _clean_json_text(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*```$", "", value)
    if value.startswith("{") and value.endswith("}"):
        return value
    start = value.find("{")
    end = value.rfind("}")
    if start >= 0 and end > start:
        return value[start : end + 1]
    return value


def _text_field(value: Any) -> str:
    """Ignore malformed structured fields rather than exposing Python values."""
    return value.strip() if isinstance(value, str) else ""


def parse_chat_result(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(_clean_json_text(raw))
    except json.JSONDecodeError:
        return {
            "lines": [
                {
                    "speaker": "",
                    "original": "",
                    "chinese": raw.strip() or "没有识别到聊天内容。",
                    "tone": "neutral",
                    "notes": "",
                }
            ],
            "summary": "",
            "terms": [],
            "reply_suggestion": "",
        }

    if not isinstance(payload, dict):
        payload = {}

    lines = payload.get("lines")
    if not isinstance(lines, list):
        lines = []

    normalized_lines: list[dict[str, str]] = []
    for item in lines:
        if not isinstance(item, dict):
            continue
        if not _text_field(item.get("chinese")):
            continue
        normalized_lines.append(
            {
                "speaker": _text_field(item.get("speaker")),
                "original": _text_field(item.get("original")),
                "chinese": _text_field(item.get("chinese")),
                "tone": _text_field(item.get("tone")) or "neutral",
                "notes": _text_field(item.get("notes")),
            }
        )

    terms = payload.get("terms")
    if not isinstance(terms, list):
        terms = []
    normalized_terms = []
    for item in terms:
        if isinstance(item, dict) and _text_field(item.get("term")):
            normalized_terms.append(
                {
                    "term": _text_field(item.get("term")),
                    "meaning": _text_field(item.get("meaning")),
                }
            )

    return {
        "lines": normalized_lines,
        "summary": _text_field(payload.get("summary")),
        "terms": normalized_terms,
        "reply_suggestion": _text_field(payload.get("reply_suggestion")),
    }


class TranslationService:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.client = OpenAI(timeout=35.0, max_retries=2)

    def transcribe(self, audio_path: Path) -> str:
        with audio_path.open("rb") as audio_file:
            result = self.client.audio.transcriptions.create(
                model=self.settings.transcription_model,
                file=audio_file,
                language="zh",
                prompt=(
                    "这是一名玩家在英雄联盟对局中的中文语音。"
                    "可能出现大龙、小龙、先锋、巢虫、闪现、传送、打野、"
                    "上路、中路、下路、辅助、ADC 等游戏词汇。"
                ),
            )
        text = result.text.strip()
        if not text:
            raise RuntimeError("没有识别到语音内容。")
        return text

    def translate_voice(self, chinese: str) -> str:
        response = self.client.responses.create(
            model=self.settings.text_model,
            instructions=VOICE_INSTRUCTIONS,
            input=chinese,
            reasoning={"effort": "none"},
            text={"verbosity": "low"},
            max_output_tokens=120,
        )
        english = response.output_text.strip().strip('"')
        if not english:
            raise RuntimeError("翻译结果为空，请重试。")
        return english

    def voice_pipeline(self, audio_path: Path) -> dict[str, str]:
        chinese = self.transcribe(audio_path)
        english = self.translate_voice(chinese)
        return {"chinese": chinese, "english": english}

    def translate_chat_text(self, text: str) -> dict[str, Any]:
        hints = find_terms(text)
        hint_text = "; ".join(f"{item.term}={item.meaning}" for item in hints)
        prompt = f"Translate and explain these League chat messages:\n{text}"
        if hint_text:
            prompt += f"\nVerified local glossary hints: {hint_text}"

        response = self.client.responses.create(
            model=self.settings.text_model,
            instructions=CHAT_INSTRUCTIONS,
            input=prompt,
            reasoning={"effort": "none"},
            text={"verbosity": "low"},
            max_output_tokens=700,
        )
        return parse_chat_result(response.output_text)

    def translate_chat_image(self, png_bytes: bytes) -> dict[str, Any]:
        encoded = base64.b64encode(png_bytes).decode("ascii")
        prompt = (
            "Read only the player chat messages visible in this League of Legends "
            "chat-area screenshot. Ignore champion UI, scores, item names, system "
            "labels, timestamps, and unrelated HUD text. Separate each exact visible "
            "summoner name/Riot ID into the speaker field and never translate it. "
            "Do not mistake a player name for part of the message. Translate only "
            "the message written after that name.\n"
            f"Common glossary: {compact_glossary()}"
        )
        response = self.client.responses.create(
            model=self.settings.text_model,
            instructions=CHAT_INSTRUCTIONS,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "image_url": f"data:image/png;base64,{encoded}",
                        },
                    ],
                }
            ],
            reasoning={"effort": "none"},
            text={"verbosity": "low"},
            max_output_tokens=900,
        )
        return parse_chat_result(response.output_text)
