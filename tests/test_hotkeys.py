from rift_translate.hotkeys import (
    DEFAULT_CHAT_HOTKEY,
    OneShotHotkeyLatch,
    normalize_chat_hotkey,
    pynput_hotkey_spec,
)


def test_chat_hotkey_defaults_away_from_f9() -> None:
    assert DEFAULT_CHAT_HOTKEY == "Ctrl+Shift+L"
    assert pynput_hotkey_spec(DEFAULT_CHAT_HOTKEY) == "<ctrl>+<shift>+l"


def test_unknown_chat_hotkey_falls_back_safely() -> None:
    assert normalize_chat_hotkey("F9") == DEFAULT_CHAT_HOTKEY


def test_fill_hotkey_latches_the_entire_key_cycle() -> None:
    latch = OneShotHotkeyLatch()

    assert latch.key_down(can_trigger=True).suppress is True
    repeated = latch.key_down(can_trigger=False)
    assert repeated.suppress is True
    assert repeated.trigger is False

    released = latch.key_up()
    assert released.suppress is True
    assert released.trigger is True


def test_fill_hotkey_does_not_start_intercepting_mid_cycle() -> None:
    latch = OneShotHotkeyLatch()

    assert latch.key_down(can_trigger=False).suppress is False
    repeat = latch.key_down(can_trigger=True)
    assert repeat.suppress is False
    assert repeat.trigger is False
    released = latch.key_up()
    assert released.suppress is False
    assert released.trigger is False


def test_fill_hotkey_queues_only_one_trigger_until_handled() -> None:
    latch = OneShotHotkeyLatch()

    latch.key_down(can_trigger=True)
    assert latch.key_up().trigger is True

    latch.key_down(can_trigger=True, block_only=True)
    second = latch.key_up()
    assert second.suppress is True
    assert second.trigger is False

    latch.mark_trigger_handled()
    latch.key_down(can_trigger=True)
    assert latch.key_up().trigger is True
