from __future__ import annotations

import ctypes
import os
import re
import time
import unicodedata
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_CAPITAL = 0x14
VK_LWIN = 0x5B
VK_RWIN = 0x5C
MODIFIER_KEYS = (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN)

SCAN_CODE_X = 0x2D
SCAN_CODE_LEFT_SHIFT = 0x2A
MAX_CHAT_TEXT_LENGTH = 180
DEFAULT_LEAGUE_EXE = Path(
    r"E:\Riot Games\League of Legends\Game\League of Legends.exe"
)

US_BASE_SCAN_CODES = {
    "1": 0x02,
    "2": 0x03,
    "3": 0x04,
    "4": 0x05,
    "5": 0x06,
    "6": 0x07,
    "7": 0x08,
    "8": 0x09,
    "9": 0x0A,
    "0": 0x0B,
    "-": 0x0C,
    "=": 0x0D,
    "q": 0x10,
    "w": 0x11,
    "e": 0x12,
    "r": 0x13,
    "t": 0x14,
    "y": 0x15,
    "u": 0x16,
    "i": 0x17,
    "o": 0x18,
    "p": 0x19,
    "[": 0x1A,
    "]": 0x1B,
    "a": 0x1E,
    "s": 0x1F,
    "d": 0x20,
    "f": 0x21,
    "g": 0x22,
    "h": 0x23,
    "j": 0x24,
    "k": 0x25,
    "l": 0x26,
    ";": 0x27,
    "'": 0x28,
    "`": 0x29,
    "\\": 0x2B,
    "z": 0x2C,
    "x": 0x2D,
    "c": 0x2E,
    "v": 0x2F,
    "b": 0x30,
    "n": 0x31,
    "m": 0x32,
    ",": 0x33,
    ".": 0x34,
    "/": 0x35,
    " ": 0x39,
}

US_SHIFTED_BASE_CHAR = {
    "!": "1",
    "@": "2",
    "#": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
    "_": "-",
    "+": "=",
    "{": "[",
    "}": "]",
    ":": ";",
    '"': "'",
    "~": "`",
    "|": "\\",
    "<": ",",
    ">": ".",
    "?": "/",
}

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    )


class INPUTUNION(ctypes.Union):
    _fields_ = (
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    )


class INPUT(ctypes.Structure):
    _anonymous_ = ("payload",)
    _fields_ = (
        ("type", wintypes.DWORD),
        ("payload", INPUTUNION),
    )


@dataclass(frozen=True)
class ForegroundWindow:
    hwnd: int
    process_id: int
    process_path: Path
    visible: bool
    minimized: bool
    modifiers_down: tuple[int, ...]
    caps_lock_on: bool = False


@dataclass(frozen=True)
class ScanCodeResult:
    sent_inputs: int
    foreground_unchanged: bool


@dataclass(frozen=True)
class TextInputResult:
    text: str
    sent_inputs: int
    foreground_unchanged: bool


class User32Api(Protocol):
    def GetForegroundWindow(self) -> int: ...

    def GetWindowThreadProcessId(
        self, hwnd: wintypes.HWND, process_id: object
    ) -> int: ...

    def IsWindowVisible(self, hwnd: wintypes.HWND) -> int: ...

    def IsIconic(self, hwnd: wintypes.HWND) -> int: ...

    def GetAsyncKeyState(self, key: int) -> int: ...

    def GetKeyState(self, key: int) -> int: ...

    def SendInput(self, count: int, inputs: object, size: int) -> int: ...


class Kernel32Api(Protocol):
    def OpenProcess(self, access: int, inherit: bool, process_id: int) -> int: ...

    def QueryFullProcessImageNameW(
        self, process: wintypes.HANDLE, flags: int, path: object, size: object
    ) -> int: ...

    def CloseHandle(self, handle: wintypes.HANDLE) -> int: ...


class GameInputError(RuntimeError):
    pass


def build_scancode_inputs(scan_code: int) -> tuple[INPUT, INPUT]:
    if not 0 < scan_code <= 0xFFFF:
        raise ValueError("scan_code must fit in an unsigned 16-bit value")

    return (
        _build_keyboard_input(scan_code, key_up=False),
        _build_keyboard_input(scan_code, key_up=True),
    )


def _build_keyboard_input(scan_code: int, *, key_up: bool) -> INPUT:
    flags = KEYEVENTF_SCANCODE
    if key_up:
        flags |= KEYEVENTF_KEYUP
    return INPUT(
        type=INPUT_KEYBOARD,
        payload=INPUTUNION(
            ki=KEYBDINPUT(
                wVk=0,
                wScan=scan_code,
                dwFlags=flags,
                time=0,
                dwExtraInfo=0,
            )
        ),
    )


def _build_unicode_input(character: str, *, key_up: bool) -> INPUT:
    if len(character) != 1 or ord(character) > 0xFFFF:
        raise ValueError("character must be one UTF-16 code unit")
    flags = KEYEVENTF_UNICODE
    if key_up:
        flags |= KEYEVENTF_KEYUP
    return INPUT(
        type=INPUT_KEYBOARD,
        payload=INPUTUNION(
            ki=KEYBDINPUT(
                wVk=0,
                wScan=ord(character),
                dwFlags=flags,
                time=0,
                dwExtraInfo=0,
            )
        ),
    )


def normalize_chat_text(
    text: str,
    *,
    max_length: int = MAX_CHAT_TEXT_LENGTH,
) -> str:
    replacements = str.maketrans(
        {
            "\r": " ",
            "\n": " ",
            "\t": " ",
            "’": "'",
            "‘": "'",
            "“": '"',
            "”": '"',
            "–": "-",
            "—": "-",
            "…": "...",
            "\u00a0": " ",
        }
    )
    decomposed = unicodedata.normalize("NFKD", str(text).translate(replacements))
    unsupported = sorted(
        {
            char
            for char in decomposed
            if ord(char) > 0x7F and not unicodedata.combining(char)
        }
    )
    if unsupported:
        rendered = " ".join(repr(char) for char in unsupported)
        raise GameInputError(f"翻译中包含无法安全输入的字符：{rendered}")
    normalized = "".join(
        char for char in decomposed if ord(char) <= 0x7F
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        raise GameInputError("没有可输入的英文聊天内容。")
    if len(normalized) > max_length:
        raise GameInputError(
            f"英文聊天内容超过 {max_length} 个字符，已拒绝截断以免改变原意。"
        )
    if normalized.startswith("/"):
        raise GameInputError("为避免误执行游戏命令，自动输入内容不能以 / 开头。")

    unsupported_ascii = sorted(
        {
            char
            for char in normalized
            if not (
                char.lower() in US_BASE_SCAN_CODES
                or char in US_SHIFTED_BASE_CHAR
            )
        }
    )
    if unsupported_ascii:
        rendered = " ".join(repr(char) for char in unsupported_ascii)
        raise GameInputError(f"翻译中包含无法安全输入的字符：{rendered}")
    return normalized


def build_text_scancode_inputs(
    text: str,
    *,
    unicode_spaces: bool = False,
    caps_lock_on: bool = False,
) -> tuple[str, tuple[INPUT, ...]]:
    normalized = normalize_chat_text(text)
    inputs: list[INPUT] = []
    for char in normalized:
        if char == " " and unicode_spaces:
            inputs.extend(
                (
                    _build_unicode_input(" ", key_up=False),
                    _build_unicode_input(" ", key_up=True),
                )
            )
            continue

        shifted = (
            char.isalpha()
            and (char.isupper() != caps_lock_on)
        )
        base_char = char.lower() if char.isalpha() else char
        if char in US_SHIFTED_BASE_CHAR:
            shifted = True
            base_char = US_SHIFTED_BASE_CHAR[char]

        scan_code = US_BASE_SCAN_CODES[base_char]
        if shifted:
            inputs.append(
                _build_keyboard_input(SCAN_CODE_LEFT_SHIFT, key_up=False)
            )
        inputs.extend(build_scancode_inputs(scan_code))
        if shifted:
            inputs.append(
                _build_keyboard_input(SCAN_CODE_LEFT_SHIFT, key_up=True)
            )
    return normalized, tuple(inputs)


def validate_foreground(
    foreground: ForegroundWindow,
    *,
    expected_exe: Path = DEFAULT_LEAGUE_EXE,
) -> None:
    if not foreground.hwnd:
        raise GameInputError("没有前台窗口，已取消扫描码测试。")
    if not foreground.visible or foreground.minimized:
        raise GameInputError("联盟窗口不可见或已最小化，已取消扫描码测试。")
    if foreground.modifiers_down:
        raise GameInputError("检测到 Ctrl/Alt/Shift/Win 仍被按住，已取消扫描码测试。")
    actual = os.path.normcase(os.path.abspath(foreground.process_path))
    expected = os.path.normcase(os.path.abspath(expected_exe))
    if actual != expected:
        raise GameInputError(
            f"前台进程不是指定的联盟游戏进程：{foreground.process_path}"
        )


def send_league_scancode_once(
    scan_code: int,
    *,
    expected_exe: Path = DEFAULT_LEAGUE_EXE,
) -> ScanCodeResult:
    if os.name != "nt":
        raise GameInputError("扫描码测试仅支持 Windows。")

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _configure_winapi(user32, kernel32)

    before = _read_foreground(user32, kernel32)
    validate_foreground(before, expected_exe=expected_exe)

    key_down, key_up = build_scancode_inputs(scan_code)
    ready_hwnd = int(user32.GetForegroundWindow() or 0)
    if ready_hwnd != before.hwnd:
        raise GameInputError("发送前检测到前台窗口变化，已取消扫描码测试。")

    sent = _send_scancode_pair(user32, key_down, key_up)

    after_hwnd = int(user32.GetForegroundWindow() or 0)
    return ScanCodeResult(
        sent_inputs=sent,
        foreground_unchanged=after_hwnd == before.hwnd,
    )


def is_league_foreground(
    *,
    expected_exe: Path = DEFAULT_LEAGUE_EXE,
) -> bool:
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _configure_winapi(user32, kernel32)
        foreground = _read_foreground(user32, kernel32)
        validate_foreground(foreground, expected_exe=expected_exe)
    except (GameInputError, OSError):
        return False
    return True


def send_league_text_once(
    text: str,
    *,
    expected_exe: Path = DEFAULT_LEAGUE_EXE,
    event_delay_ms: int = 12,
    unicode_spaces: bool = True,
) -> TextInputResult:
    if os.name != "nt":
        raise GameInputError("游戏聊天扫描码输入仅支持 Windows。")

    if not 0 <= event_delay_ms <= 100:
        raise ValueError("event_delay_ms must be between 0 and 100")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _configure_winapi(user32, kernel32)

    before = _read_foreground(user32, kernel32)
    validate_foreground(before, expected_exe=expected_exe)
    normalized, input_events = build_text_scancode_inputs(
        text,
        unicode_spaces=unicode_spaces,
        caps_lock_on=before.caps_lock_on,
    )
    ready_hwnd = int(user32.GetForegroundWindow() or 0)
    if ready_hwnd != before.hwnd:
        raise GameInputError("输入前检测到前台窗口变化，已取消整句扫描码输入。")

    sent = _send_scancode_paced(
        user32,
        input_events,
        expected_hwnd=before.hwnd,
        event_delay_ms=event_delay_ms,
    )
    after_hwnd = int(user32.GetForegroundWindow() or 0)
    return TextInputResult(
        text=normalized,
        sent_inputs=sent,
        foreground_unchanged=after_hwnd == before.hwnd,
    )


def _send_scancode_pair(
    user32: object,
    key_down: INPUT,
    key_up: INPUT,
) -> int:
    inputs = (INPUT * 2)(key_down, key_up)
    sent = int(user32.SendInput(2, inputs, ctypes.sizeof(INPUT)))
    if sent == 1:
        release_inputs = (INPUT * 1)(key_up)
        released = int(user32.SendInput(1, release_inputs, ctypes.sizeof(INPUT)))
        if released != 1:
            raise GameInputError(
                "系统只接收了 X 按下事件，自动补发抬起也失败；请实体按一下再松开 X。"
            )
        raise GameInputError(
            "系统只接收了 X 按下事件；已自动补发抬起并停止，不会继续输入。"
        )
    if sent != 2:
        raise GameInputError(
            "SendInput 未完整发送 X 的按下/抬起事件；可能被权限或游戏输入层阻止。"
        )
    return sent


def _send_scancode_batch(user32: object, input_events: tuple[INPUT, ...]) -> int:
    if not input_events:
        raise GameInputError("没有扫描码事件可发送。")

    inputs = (INPUT * len(input_events))(*input_events)
    sent = int(
        user32.SendInput(
            len(input_events),
            inputs,
            ctypes.sizeof(INPUT),
        )
    )
    if sent == len(input_events):
        return sent

    active_scan_codes: list[int] = []
    for event in input_events[:sent]:
        scan_code = int(event.ki.wScan)
        if int(event.ki.dwFlags) & KEYEVENTF_KEYUP:
            for index in range(len(active_scan_codes) - 1, -1, -1):
                if active_scan_codes[index] == scan_code:
                    del active_scan_codes[index]
                    break
        else:
            active_scan_codes.append(scan_code)

    recovery_events = tuple(
        _build_keyboard_input(scan_code, key_up=True)
        for scan_code in reversed(active_scan_codes)
    )
    if recovery_events:
        recovery = (INPUT * len(recovery_events))(*recovery_events)
        released = int(
            user32.SendInput(
                len(recovery_events),
                recovery,
                ctypes.sizeof(INPUT),
            )
        )
        if released != len(recovery_events):
            raise GameInputError(
                "整句输入被部分阻止，自动释放未完成；请松开键盘并实体轻按一次 Shift。"
            )

    raise GameInputError(
        f"整句输入只完成了 {sent}/{len(input_events)} 个扫描码事件；"
        "已停止并释放可能残留的按键。"
    )


def _send_scancode_paced(
    user32: object,
    input_events: tuple[INPUT, ...],
    *,
    expected_hwnd: int,
    event_delay_ms: int,
) -> int:
    active_inputs: list[INPUT] = []
    sent_total = 0

    for event in input_events:
        identity = _keyboard_input_identity(event)
        is_key_up = bool(int(event.ki.dwFlags) & KEYEVENTF_KEYUP)
        foreground_unchanged = (
            int(user32.GetForegroundWindow() or 0) == expected_hwnd
        )
        if not foreground_unchanged:
            if is_key_up and any(
                _keyboard_input_identity(active) == identity
                for active in active_inputs
            ):
                _send_one_input(user32, event)
                _remove_last_active_input(active_inputs, identity)
            _release_active_inputs(user32, active_inputs)
            raise GameInputError(
                "逐字输入期间前台窗口发生变化，已停止并释放可能残留的按键。"
            )

        try:
            _send_one_input(user32, event)
        except GameInputError:
            _release_active_inputs(user32, active_inputs)
            raise

        sent_total += 1
        if is_key_up:
            _remove_last_active_input(active_inputs, identity)
        else:
            active_inputs.append(event)

        if event_delay_ms:
            time.sleep(event_delay_ms / 1000)

    return sent_total


def _send_one_input(user32: object, event: INPUT) -> None:
    inputs = (INPUT * 1)(event)
    sent = int(user32.SendInput(1, inputs, ctypes.sizeof(INPUT)))
    if sent != 1:
        raise GameInputError("逐字扫描码事件被系统或游戏输入层阻止。")


def _release_active_inputs(
    user32: object,
    active_inputs: list[INPUT],
) -> None:
    if not active_inputs:
        return
    releases = tuple(
        _key_up_for_input(event)
        for event in reversed(active_inputs)
    )
    inputs = (INPUT * len(releases))(*releases)
    sent = int(user32.SendInput(len(releases), inputs, ctypes.sizeof(INPUT)))
    active_inputs.clear()
    if sent != len(releases):
        raise GameInputError(
            "自动释放按键未完成；请松开键盘并实体轻按一次 Shift。"
        )


def _keyboard_input_identity(event: INPUT) -> tuple[str, int]:
    flags = int(event.ki.dwFlags)
    if flags & KEYEVENTF_UNICODE:
        return ("unicode", int(event.ki.wScan))
    if flags & KEYEVENTF_SCANCODE:
        return ("scancode", int(event.ki.wScan))
    return ("virtual_key", int(event.ki.wVk))


def _key_up_for_input(event: INPUT) -> INPUT:
    return INPUT(
        type=INPUT_KEYBOARD,
        payload=INPUTUNION(
            ki=KEYBDINPUT(
                wVk=int(event.ki.wVk),
                wScan=int(event.ki.wScan),
                dwFlags=int(event.ki.dwFlags) | KEYEVENTF_KEYUP,
                time=0,
                dwExtraInfo=int(event.ki.dwExtraInfo),
            )
        ),
    )


def _remove_last_active_input(
    active_inputs: list[INPUT],
    identity: tuple[str, int],
) -> None:
    for index in range(len(active_inputs) - 1, -1, -1):
        if _keyboard_input_identity(active_inputs[index]) == identity:
            del active_inputs[index]
            return


def _configure_winapi(user32: object, kernel32: object) -> None:
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.GetKeyState.argtypes = [ctypes.c_int]
    user32.GetKeyState.restype = ctypes.c_short
    user32.SendInput.argtypes = [
        wintypes.UINT,
        ctypes.POINTER(INPUT),
        ctypes.c_int,
    ]
    user32.SendInput.restype = wintypes.UINT

    kernel32.OpenProcess.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL


def _read_foreground(user32: object, kernel32: object) -> ForegroundWindow:
    hwnd = int(user32.GetForegroundWindow() or 0)
    if not hwnd:
        return ForegroundWindow(
            hwnd=0,
            process_id=0,
            process_path=Path(),
            visible=False,
            minimized=False,
            modifiers_down=(),
            caps_lock_on=False,
        )

    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(
        wintypes.HWND(hwnd),
        ctypes.byref(process_id),
    )
    process_path = _query_process_path(kernel32, int(process_id.value))
    modifiers_down = tuple(
        key for key in MODIFIER_KEYS if user32.GetAsyncKeyState(key) & 0x8000
    )
    return ForegroundWindow(
        hwnd=hwnd,
        process_id=int(process_id.value),
        process_path=process_path,
        visible=bool(user32.IsWindowVisible(wintypes.HWND(hwnd))),
        minimized=bool(user32.IsIconic(wintypes.HWND(hwnd))),
        modifiers_down=modifiers_down,
        caps_lock_on=bool(user32.GetKeyState(VK_CAPITAL) & 0x0001),
    )


def _query_process_path(kernel32: object, process_id: int) -> Path:
    process = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION,
        False,
        process_id,
    )
    if not process:
        raise GameInputError("无法读取前台进程路径，已取消扫描码测试。")

    try:
        capacity = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(capacity.value)
        if not kernel32.QueryFullProcessImageNameW(
            process,
            0,
            buffer,
            ctypes.byref(capacity),
        ):
            raise GameInputError("无法确认前台进程身份，已取消扫描码测试。")
        return Path(buffer.value)
    finally:
        kernel32.CloseHandle(process)
