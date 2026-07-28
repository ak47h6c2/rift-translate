from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes


CF_TEXT = 1
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


class ClipboardWriteError(RuntimeError):
    pass


def build_clipboard_payloads(text: str) -> dict[int, bytes]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    ansi_encoding = "mbcs" if os.name == "nt" else "utf-8"
    return {
        CF_UNICODETEXT: (normalized + "\0").encode("utf-16-le"),
        CF_TEXT: (normalized + "\0").encode(ansi_encoding, errors="replace"),
    }


def native_clipboard_owner(widget_handle: int) -> int:
    if os.name != "nt":
        return widget_handle
    user32 = ctypes.windll.user32
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    parent = user32.GetParent(wintypes.HWND(widget_handle))
    return int(parent or widget_handle)


def copy_text_compatible(
    text: str,
    *,
    owner_hwnd: int,
    attempts: int = 12,
    retry_delay: float = 0.025,
) -> tuple[int, ...]:
    if os.name != "nt":
        raise ClipboardWriteError("原生兼容剪贴板仅支持 Windows。")
    if not text:
        raise ClipboardWriteError("没有可复制的文本。")

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL

    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL

    for attempt in range(max(1, attempts)):
        if user32.OpenClipboard(wintypes.HWND(owner_hwnd)):
            break
        if attempt + 1 < attempts:
            time.sleep(max(0.0, retry_delay))
    else:
        raise ClipboardWriteError("Windows 剪贴板正被其他程序占用。")

    written: list[int] = []
    try:
        if not user32.EmptyClipboard():
            raise ClipboardWriteError("无法清空 Windows 剪贴板。")
        for clipboard_format, payload in build_clipboard_payloads(text).items():
            try:
                _set_clipboard_payload(
                    clipboard_format,
                    payload,
                    user32=user32,
                    kernel32=kernel32,
                )
            except ClipboardWriteError:
                if not written:
                    raise
            else:
                written.append(clipboard_format)
    finally:
        user32.CloseClipboard()

    if CF_UNICODETEXT not in written:
        raise ClipboardWriteError("无法写入 Unicode 剪贴板文本。")
    return tuple(written)


def _set_clipboard_payload(
    clipboard_format: int,
    payload: bytes,
    *,
    user32: object,
    kernel32: object,
) -> None:
    memory = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(payload))
    if not memory:
        raise ClipboardWriteError("无法分配剪贴板内存。")

    transferred = False
    try:
        pointer = kernel32.GlobalLock(memory)
        if not pointer:
            raise ClipboardWriteError("无法锁定剪贴板内存。")
        try:
            ctypes.memmove(pointer, payload, len(payload))
        finally:
            kernel32.GlobalUnlock(memory)

        if not user32.SetClipboardData(clipboard_format, memory):
            raise ClipboardWriteError(f"无法写入剪贴板格式 {clipboard_format}。")
        transferred = True
    finally:
        if not transferred:
            kernel32.GlobalFree(memory)
