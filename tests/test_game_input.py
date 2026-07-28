from pathlib import Path

import pytest

from rift_translate.game_input import (
    GameInputError,
    ForegroundWindow,
    INPUT,
    KEYEVENTF_KEYUP,
    KEYEVENTF_SCANCODE,
    KEYEVENTF_UNICODE,
    SCAN_CODE_X,
    SCAN_CODE_LEFT_SHIFT,
    _build_unicode_input,
    _send_scancode_batch,
    _send_scancode_paced,
    _send_scancode_pair,
    build_scancode_inputs,
    build_text_scancode_inputs,
    normalize_chat_text,
    validate_foreground,
)


EXPECTED = Path(r"E:\Riot Games\League of Legends\Game\League of Legends.exe")


def foreground(**overrides: object) -> ForegroundWindow:
    values: dict[str, object] = {
        "hwnd": 100,
        "process_id": 200,
        "process_path": EXPECTED,
        "visible": True,
        "minimized": False,
        "modifiers_down": (),
    }
    values.update(overrides)
    return ForegroundWindow(**values)


def test_builds_exact_x_scancode_down_and_up() -> None:
    key_down, key_up = build_scancode_inputs(SCAN_CODE_X)

    assert key_down.type == 1
    assert key_down.ki.wVk == 0
    assert key_down.ki.wScan == 0x2D
    assert key_down.ki.dwFlags == KEYEVENTF_SCANCODE

    assert key_up.type == 1
    assert key_up.ki.wVk == 0
    assert key_up.ki.wScan == 0x2D
    assert key_up.ki.dwFlags == KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP


def test_input_structure_has_windows_x64_sendinput_size() -> None:
    assert __import__("ctypes").sizeof(INPUT) == 40


def test_accepts_only_expected_visible_foreground_game() -> None:
    validate_foreground(foreground(), expected_exe=EXPECTED)


@pytest.mark.parametrize(
    "unsafe",
    [
        foreground(hwnd=0),
        foreground(visible=False),
        foreground(minimized=True),
        foreground(modifiers_down=(0x10,)),
        foreground(process_path=Path(r"C:\Windows\notepad.exe")),
    ],
)
def test_rejects_unsafe_foreground_state(unsafe: ForegroundWindow) -> None:
    with pytest.raises(GameInputError):
        validate_foreground(unsafe, expected_exe=EXPECTED)


class FakeUser32:
    def __init__(self, results: list[int]) -> None:
        self.results = iter(results)
        self.calls: list[tuple[int, tuple[tuple[int, int, int], ...], int]] = []

    def SendInput(self, count: int, inputs: object, size: int) -> int:
        captured = tuple(
            (
                int(inputs[index].ki.wVk),
                int(inputs[index].ki.wScan),
                int(inputs[index].ki.dwFlags),
            )
            for index in range(count)
        )
        self.calls.append((count, captured, size))
        return next(self.results)


def test_send_pair_calls_sendinput_once_with_only_x_down_and_up() -> None:
    user32 = FakeUser32([2])
    key_down, key_up = build_scancode_inputs(SCAN_CODE_X)

    assert _send_scancode_pair(user32, key_down, key_up) == 2
    assert user32.calls == [
        (
            2,
            (
                (0, SCAN_CODE_X, KEYEVENTF_SCANCODE),
                (0, SCAN_CODE_X, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP),
            ),
            40,
        )
    ]


def test_partial_send_immediately_recovers_with_x_keyup_only() -> None:
    user32 = FakeUser32([1, 1])
    key_down, key_up = build_scancode_inputs(SCAN_CODE_X)

    with pytest.raises(GameInputError, match="已自动补发抬起"):
        _send_scancode_pair(user32, key_down, key_up)

    assert user32.calls[1] == (
        1,
        ((0, SCAN_CODE_X, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP),),
        40,
    )


def test_normalizes_voice_translation_for_safe_game_chat() -> None:
    assert (
        normalize_chat_text("  Braum—block it!\nI’m coming…  ")
        == "Braum-block it! I'm coming..."
    )


def test_builds_ascii_sentence_without_enter_or_unicode_events() -> None:
    normalized, inputs = build_text_scancode_inputs("X 30?")

    assert normalized == "X 30?"
    assert all(item.ki.wVk == 0 for item in inputs)
    assert all(item.ki.dwFlags & KEYEVENTF_SCANCODE for item in inputs)
    assert all(item.ki.wScan != 0x1C for item in inputs)
    assert inputs[0].ki.wScan == SCAN_CODE_LEFT_SHIFT
    assert inputs[0].ki.dwFlags == KEYEVENTF_SCANCODE
    assert inputs[3].ki.wScan == SCAN_CODE_LEFT_SHIFT
    assert inputs[3].ki.dwFlags == KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP


def test_can_route_spaces_through_unicode_text_events_only() -> None:
    normalized, inputs = build_text_scancode_inputs(
        "A B",
        unicode_spaces=True,
    )

    assert normalized == "A B"
    unicode_events = [
        item for item in inputs if item.ki.dwFlags & KEYEVENTF_UNICODE
    ]
    assert len(unicode_events) == 2
    assert unicode_events[0].ki.wVk == 0
    assert unicode_events[0].ki.wScan == ord(" ")
    assert unicode_events[0].ki.dwFlags == KEYEVENTF_UNICODE
    assert unicode_events[1].ki.dwFlags == KEYEVENTF_UNICODE | KEYEVENTF_KEYUP


def test_caps_lock_inverts_shift_only_for_letters() -> None:
    _, inputs = build_text_scancode_inputs(
        "Aa?",
        caps_lock_on=True,
    )

    assert inputs[0].ki.wScan == 0x1E
    assert inputs[0].ki.dwFlags == KEYEVENTF_SCANCODE
    assert inputs[2].ki.wScan == SCAN_CODE_LEFT_SHIFT
    assert inputs[2].ki.dwFlags == KEYEVENTF_SCANCODE
    assert inputs[-4].ki.wScan == SCAN_CODE_LEFT_SHIFT
    assert inputs[-4].ki.dwFlags == KEYEVENTF_SCANCODE


@pytest.mark.parametrize("caps_lock_on", [False, True])
def test_full_supported_text_has_balanced_shift_and_never_enter(
    caps_lock_on: bool,
) -> None:
    _, inputs = build_text_scancode_inputs(
        "Aa Zz 09 !?.,:'-",
        unicode_spaces=True,
        caps_lock_on=caps_lock_on,
    )

    shift_depth = 0
    for item in inputs:
        if (
            item.ki.dwFlags & KEYEVENTF_SCANCODE
            and item.ki.wScan == SCAN_CODE_LEFT_SHIFT
        ):
            shift_depth += -1 if item.ki.dwFlags & KEYEVENTF_KEYUP else 1
            assert shift_depth in (0, 1)
        assert not (
            item.ki.dwFlags & KEYEVENTF_SCANCODE
            and item.ki.wScan == 0x1C
        )
        if item.ki.dwFlags & KEYEVENTF_UNICODE:
            assert item.ki.wScan == ord(" ")
    assert shift_depth == 0


def test_refuses_to_silently_drop_or_truncate_translation_text() -> None:
    with pytest.raises(GameInputError, match="无法安全输入"):
        normalize_chat_text("go 龙")
    with pytest.raises(GameInputError, match="拒绝截断"):
        normalize_chat_text("a" * 181)
    with pytest.raises(GameInputError, match="游戏命令"):
        normalize_chat_text("/all hello")


def test_batch_partial_send_releases_only_currently_held_scancodes() -> None:
    _, inputs = build_text_scancode_inputs("A")
    user32 = FakeUser32([2, 2])

    with pytest.raises(GameInputError, match="2/4"):
        _send_scancode_batch(user32, inputs)

    assert user32.calls[1] == (
        2,
        (
            (0, 0x1E, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP),
            (
                0,
                SCAN_CODE_LEFT_SHIFT,
                KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP,
            ),
        ),
        40,
    )


class FakePacedUser32(FakeUser32):
    def __init__(self, results: list[int], foregrounds: list[int]) -> None:
        super().__init__(results)
        self.foregrounds = iter(foregrounds)

    def GetForegroundWindow(self) -> int:
        return next(self.foregrounds)


def test_paced_send_releases_shift_if_sendinput_fails_mid_character() -> None:
    _, inputs = build_text_scancode_inputs("A")
    user32 = FakePacedUser32([1, 0, 1], [100, 100])

    with pytest.raises(GameInputError, match="逐字扫描码事件"):
        _send_scancode_paced(
            user32,
            inputs,
            expected_hwnd=100,
            event_delay_ms=0,
        )

    assert user32.calls[-1] == (
        1,
        (
            (
                0,
                SCAN_CODE_LEFT_SHIFT,
                KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP,
            ),
        ),
        40,
    )


def test_paced_send_releases_unicode_space_if_focus_changes_on_keyup() -> None:
    inputs = (
        _build_unicode_input(" ", key_up=False),
        _build_unicode_input(" ", key_up=True),
    )
    user32 = FakePacedUser32([1, 1], [100, 999])

    with pytest.raises(GameInputError, match="前台窗口发生变化"):
        _send_scancode_paced(
            user32,
            inputs,
            expected_hwnd=100,
            event_delay_ms=0,
        )

    assert user32.calls[-1] == (
        1,
        (
            (
                0,
                ord(" "),
                KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
            ),
        ),
        40,
    )
