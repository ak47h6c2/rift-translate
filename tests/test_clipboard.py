from rift_translate.clipboard import CF_TEXT, CF_UNICODETEXT, build_clipboard_payloads


def test_builds_unicode_and_ansi_clipboard_formats() -> None:
    payloads = build_clipboard_payloads("group drake\nno flash")

    assert set(payloads) == {CF_UNICODETEXT, CF_TEXT}
    assert payloads[CF_UNICODETEXT].decode("utf-16-le") == (
        "group drake\r\nno flash\0"
    )
    assert payloads[CF_TEXT].endswith(b"\0")
    assert b"group drake\r\nno flash" in payloads[CF_TEXT]
