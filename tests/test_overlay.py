from rift_translate.overlay import (
    OverlayContent,
    build_chat_overlay_content,
    clamp_overlay_height,
    overlay_body_font_size,
    voice_panel_font_size,
)


def test_chat_overlay_keeps_names_and_shows_only_recent_chinese() -> None:
    result = {
        "lines": [
            {
                "speaker": "OldPlayer",
                "original": "old message",
                "chinese": "旧消息",
                "tone": "neutral",
            },
            {
                "speaker": "xX_Dragon#NA1",
                "original": "play for drake",
                "chinese": "围绕小龙打",
                "tone": "shotcall",
            },
            {
                "speaker": "Support Main",
                "original": "stop inting",
                "chinese": "别再送了",
                "tone": "toxic",
            },
        ],
        "reply_suggestion": "On my way.",
    }

    content = build_chat_overlay_content(
        result,
        max_lines=2,
        hotkey_label="Ctrl+Alt+T",
    )

    assert "OldPlayer" not in content.body
    assert "play for drake" not in content.body
    assert "战术" not in content.body
    assert "On my way." not in content.footer
    assert "xX_Dragon#NA1：围绕小龙打" in content.body
    assert "Support Main：别再送了" in content.body
    assert content.chat_lines[0].speaker == "xX_Dragon#NA1"
    assert content.footer.startswith("Ctrl+Alt+T")
    assert content.duration_ms == 12_000


def test_chat_overlay_falls_back_when_no_lines_are_detected() -> None:
    content = build_chat_overlay_content(
        {"lines": [], "summary": "队友正在准备打大龙。"}
    )

    assert content.body == "队友正在准备打大龙。"


def test_long_voice_text_uses_smaller_fonts_without_truncation() -> None:
    text = "wait for me and do not engage until my teleport is ready " * 4
    content = OverlayContent(title="英文已就绪", body=text, kind="voice")

    assert overlay_body_font_size(content) == 9
    assert voice_panel_font_size(text) == 12
    assert content.body == text


def test_overlay_height_can_grow_beyond_old_260_pixel_cap() -> None:
    assert clamp_overlay_height(350, 1080) == 350
    assert clamp_overlay_height(900, 1080) == 420
    assert clamp_overlay_height(350, 300) == 260


def test_blank_tail_does_not_hide_recent_valid_chat() -> None:
    name = "很长的召唤师名字_WithTag#12345"
    content = build_chat_overlay_content({"lines": [
        {"speaker": name, "chinese": "等我再开团"},
        None, {}, {"chinese": "  "},
    ]}, max_lines=1)
    assert content.chat_lines[0].speaker == name
    assert content.chat_lines[0].message == "等我再开团"


def test_long_speaker_layout_preserves_name_and_fits_width() -> None:
    import tkinter as tk
    from rift_translate.overlay import GameOverlay

    root = tk.Tk()
    root.withdraw()
    try:
        overlay = GameOverlay(root, lambda: (0, 0))
        name = "超长召唤师名字" * 4 + "#SG2"
        overlay._render_body(build_chat_overlay_content({"lines": [
            {"speaker": name, "chinese": "等我再开团，我们先拿小龙。" * 4},
        ]}))
        root.update_idletasks()
        labels = overlay._chat_body.winfo_children()
        assert labels[0].cget("text") == name
        assert overlay._chat_body.winfo_reqwidth() <= overlay.WIDTH - 40
    finally:
        root.destroy()
