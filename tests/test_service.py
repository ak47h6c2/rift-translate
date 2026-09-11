from rift_translate.service import parse_chat_result
import pytest
import json


def test_parse_chat_result_accepts_json_fence() -> None:
    raw = """```json
    {
      "lines": [{
        "speaker": "NoTranslate#NA1",
        "original": "jg diff",
        "chinese": "打野差距",
        "tone": "toxic",
        "notes": "在责怪双方打野表现差异"
      }],
      "summary": "",
      "terms": [{"term": "diff", "meaning": "差距"}],
      "reply_suggestion": "Let's focus on drake."
    }
    ```"""
    parsed = parse_chat_result(raw)
    assert parsed["lines"][0]["speaker"] == "NoTranslate#NA1"
    assert parsed["lines"][0]["chinese"] == "打野差距"
    assert parsed["terms"][0]["term"] == "diff"
    assert parsed["reply_suggestion"] == "Let's focus on drake."


def test_parse_chat_result_falls_back_to_plain_text() -> None:
    parsed = parse_chat_result("这是一句普通解释")
    assert parsed["lines"][0]["speaker"] == ""
    assert parsed["lines"][0]["chinese"] == "这是一句普通解释"


@pytest.mark.parametrize("raw", ["null", "[]", "42", '"text"', "true"])
def test_non_object_json_does_not_crash(raw: str) -> None:
    assert parse_chat_result(raw)["lines"] == []


def test_malformed_fields_are_empty_and_blank_messages_are_skipped() -> None:
    parsed = parse_chat_result(json.dumps({
        "lines": [None, {"chinese": None}, {"chinese": "  "},
                  {"speaker": None, "chinese": "等我", "notes": {}, "tone": None}],
        "summary": None, "reply_suggestion": [],
        "terms": [{"term": {}}, {"term": "ff", "meaning": None}],
    }))
    assert parsed["lines"] == [{"speaker": "", "original": "", "chinese": "等我",
                                "tone": "neutral", "notes": ""}]
    assert parsed["summary"] == parsed["reply_suggestion"] == ""
    assert parsed["terms"] == [{"term": "ff", "meaning": ""}]
