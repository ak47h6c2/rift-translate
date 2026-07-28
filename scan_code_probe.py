from __future__ import annotations

import argparse
import ctypes
import sys
import threading
import winsound
from ctypes import wintypes

from pynput import keyboard

from rift_translate.game_input import (
    GameInputError,
    send_league_text_once,
)


ERROR_ALREADY_EXISTS = 183
VK_F7 = 0x76
WM_KEYUP = 0x0101
WM_SYSKEYUP = 0x0105
LLKHF_INJECTED = 0x10
LLKHF_LOWER_IL_INJECTED = 0x02
PROBE_MUTEX_NAME = r"Local\RiftTranslateScanCodeProbe"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="一次性联盟聊天扫描码探针")
    parser.add_argument(
        "--text",
        default="x",
        help="只写入聊天输入框、不按 Enter 的 ASCII 测试文本",
    )
    parser.add_argument(
        "--delay-ms",
        type=int,
        default=20,
        help="每个扫描码按下/抬起事件之间的毫秒间隔",
    )
    args = parser.parse_args(argv)

    mutex = _acquire_single_instance()
    if mutex is None:
        print("扫描码探针已经在运行；请回到现有探针并只按一次 F7。")
        return 4

    print("联盟扫描码探针已启动。")
    print("留在游戏内：实体 Enter 打开聊天，点击输入框，然后松开 F7。")
    print(f"探针会拦截这一次实体 F7，输入 {args.text!r}，不会发送 Enter。")

    try:
        _wait_for_physical_f7()
        try:
            result = send_league_text_once(
                args.text,
                event_delay_ms=args.delay_ms,
            )
        except GameInputError as exc:
            print(f"已安全取消：{exc}")
            winsound.MessageBeep(winsound.MB_ICONHAND)
            return 2
        else:
            if not result.foreground_unchanged:
                print("文本已输入，但前台窗口随后发生变化；不会继续发送任何输入。")
                return_code = 3
            else:
                print(
                    f"已输入 {result.text!r}。请目视检查聊天输入框；没有按 Enter。"
                )
                return_code = 0
            winsound.MessageBeep(winsound.MB_OK)
            return return_code
    finally:
        _release_single_instance(mutex)


def _wait_for_physical_f7() -> None:
    triggered = threading.Event()
    listener_holder: list[keyboard.Listener] = []

    def event_filter(msg: int, data: object) -> bool:
        flags = int(data.flags)
        if int(data.vkCode) != VK_F7:
            return True
        if flags & (LLKHF_INJECTED | LLKHF_LOWER_IL_INJECTED):
            return True

        if msg in (WM_KEYUP, WM_SYSKEYUP):
            triggered.set()

        listener_holder[0].suppress_event()
        return False

    listener = keyboard.Listener(win32_event_filter=event_filter)
    listener_holder.append(listener)
    listener.start()
    listener.wait()
    triggered.wait()
    listener.stop()
    listener.join()


def _acquire_single_instance() -> tuple[object, int] | None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.CreateMutexW(None, False, PROBE_MUTEX_NAME)
    if not handle:
        raise OSError(ctypes.get_last_error(), "无法创建扫描码探针单实例锁")
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return kernel32, int(handle)


def _release_single_instance(mutex: tuple[object, int]) -> None:
    kernel32, handle = mutex
    kernel32.CloseHandle(wintypes.HANDLE(handle))


if __name__ == "__main__":
    sys.exit(main())
