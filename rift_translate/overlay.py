from __future__ import annotations

import ctypes
import os
import tkinter as tk
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Callable


OVERLAY_BG = "#07111F"
OVERLAY_PANEL = "#0D1B2D"
OVERLAY_TEXT = "#F3F6FA"
OVERLAY_MUTED = "#9BB0C3"
OVERLAY_GOLD = "#C89B3C"
OVERLAY_TEAL = "#2BB7A9"
OVERLAY_PURPLE = "#B8A7FF"
OVERLAY_ERROR = "#F26D78"
OVERLAY_MIN_HEIGHT = 78
OVERLAY_MAX_HEIGHT = 420


@dataclass(frozen=True, slots=True)
class OverlayChatLine:
    speaker: str
    message: str


@dataclass(frozen=True, slots=True)
class OverlayContent:
    title: str
    body: str
    footer: str = ""
    kind: str = "info"
    duration_ms: int = 9_000
    chat_lines: tuple[OverlayChatLine, ...] = ()


def _compact(value: Any) -> str:
    return " ".join(str(value or "").split())


def overlay_body_font_size(content: OverlayContent) -> int:
    length = len(_compact(content.body))
    if content.kind == "voice":
        if length > 150:
            return 9
        if length > 90:
            return 10
        return 11
    if length > 220:
        return 9
    if length > 130:
        return 10
    return 11


def voice_panel_font_size(text: str) -> int:
    length = len(_compact(text))
    if length > 150:
        return 12
    if length > 90:
        return 13
    return 14


def clamp_overlay_height(requested_height: int, available_height: int) -> int:
    maximum = min(OVERLAY_MAX_HEIGHT, max(OVERLAY_MIN_HEIGHT, available_height - 40))
    return min(max(requested_height, OVERLAY_MIN_HEIGHT), maximum)


def build_chat_overlay_content(
    result: dict[str, Any],
    *,
    max_lines: int = 3,
    hotkey_label: str = "Ctrl+Shift+L",
) -> OverlayContent:
    source_lines = result.get("lines", [])
    if not isinstance(source_lines, list):
        source_lines = []

    chat_lines: list[OverlayChatLine] = []
    for line in source_lines:
        if not isinstance(line, dict):
            continue
        speaker = _compact(line.get("speaker"))
        chinese = _compact(line.get("chinese"))
        if chinese:
            chat_lines.append(OverlayChatLine(speaker=speaker, message=chinese))

    chat_lines = chat_lines[-max(1, max_lines) :]

    if not chat_lines:
        summary = _compact(result.get("summary"))
        chat_lines.append(
            OverlayChatLine(
                speaker="",
                message=summary or "没有识别到可翻译的聊天内容。",
            )
        )

    return OverlayContent(
        title="聊天翻译",
        body="\n".join(
            f"{line.speaker}：{line.message}" if line.speaker else line.message
            for line in chat_lines
        ),
        footer=f"{hotkey_label} 刷新 · F10 详情",
        kind="chat",
        duration_ms=12_000,
        chat_lines=tuple(chat_lines),
    )


def _monitor_work_area_for_point(
    point: tuple[int, int],
    fallback: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    if os.name != "nt":
        return fallback

    class MonitorInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    try:
        user32 = ctypes.windll.user32
        monitor = user32.MonitorFromPoint(wintypes.POINT(*point), 2)
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(MonitorInfo)
        if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return fallback
        return (
            int(info.rcWork.left),
            int(info.rcWork.top),
            int(info.rcWork.right),
            int(info.rcWork.bottom),
        )
    except (AttributeError, OSError, TypeError):
        return fallback


class GameOverlay(tk.Toplevel):
    WIDTH = 440

    def __init__(
        self,
        parent: tk.Misc,
        anchor_provider: Callable[[], tuple[int, int]],
    ) -> None:
        super().__init__(parent)
        self._anchor_provider = anchor_provider
        self._hide_job: str | None = None

        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=OVERLAY_BG)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.90)

        self._container = tk.Frame(
            self,
            bg=OVERLAY_PANEL,
            highlightthickness=1,
            highlightbackground="#263D52",
            padx=12,
            pady=9,
        )
        self._container.pack(fill="both", expand=True)
        self._container.grid_columnconfigure(1, weight=1)
        self._container.grid_rowconfigure(1, weight=1)

        self._accent = tk.Frame(self._container, bg=OVERLAY_TEAL, width=3)
        self._accent.grid(row=0, column=0, rowspan=3, padx=(0, 10), sticky="ns")

        self._title = tk.Label(
            self._container,
            text="",
            bg=OVERLAY_PANEL,
            fg=OVERLAY_TEAL,
            font=("Arial", 9, "bold"),
            anchor="w",
        )
        self._title.grid(row=0, column=1, sticky="ew")

        self._body = tk.Label(
            self._container,
            text="",
            bg=OVERLAY_PANEL,
            fg=OVERLAY_TEXT,
            font=("Microsoft YaHei UI", 12),
            justify="left",
            anchor="nw",
            wraplength=self.WIDTH - 54,
        )
        self._body.grid(row=1, column=1, pady=(4, 2), sticky="nsew")

        self._chat_body = tk.Frame(self._container, bg=OVERLAY_PANEL)
        self._chat_body.grid(row=1, column=1, pady=(4, 2), sticky="ew")
        self._chat_body.grid_columnconfigure(1, weight=1)
        self._chat_body.grid_remove()

        self._footer = tk.Label(
            self._container,
            text="",
            bg=OVERLAY_PANEL,
            fg=OVERLAY_MUTED,
            font=("Arial", 8),
            justify="left",
            anchor="w",
            wraplength=self.WIDTH - 54,
        )
        self._footer.grid(row=2, column=1, pady=(2, 0), sticky="ew")

        self.update_idletasks()
        self._apply_no_activate_click_through()

    def show_content(self, content: OverlayContent) -> None:
        if self._hide_job is not None:
            try:
                self.after_cancel(self._hide_job)
            except tk.TclError:
                pass
            self._hide_job = None

        accent_colors = {
            "recording": OVERLAY_ERROR,
            "busy": OVERLAY_PURPLE,
            "voice": OVERLAY_TEAL,
            "chat": OVERLAY_GOLD,
            "error": OVERLAY_ERROR,
            "info": OVERLAY_TEAL,
        }
        accent = accent_colors.get(content.kind, OVERLAY_TEAL)
        self._accent.configure(bg=accent)
        self._title.configure(text=content.title, fg=accent)
        self._footer.configure(text=content.footer)
        self._render_body(content)

        self.deiconify()
        self.update_idletasks()
        self._position()
        self._show_without_activation()

        if content.duration_ms > 0:
            self._hide_job = self.after(content.duration_ms, self.hide_overlay)

    def _render_body(self, content: OverlayContent) -> None:
        for child in self._chat_body.winfo_children():
            child.destroy()

        if not content.chat_lines:
            self._chat_body.grid_remove()
            self._body.configure(
                text=content.body,
                font=("Microsoft YaHei UI", overlay_body_font_size(content)),
            )
            self._body.grid()
            return

        self._body.grid_remove()
        self._chat_body.grid()
        for row, line in enumerate(content.chat_lines):
            if line.speaker:
                tk.Label(
                    self._chat_body,
                    text=line.speaker,
                    bg=OVERLAY_PANEL,
                    fg=OVERLAY_GOLD,
                    font=("Arial", 9, "bold"),
                    anchor="ne",
                    justify="right",
                    wraplength=110,
                ).grid(row=row, column=0, padx=(0, 7), pady=2, sticky="ne")
            tk.Label(
                self._chat_body,
                text=line.message,
                bg=OVERLAY_PANEL,
                fg=OVERLAY_TEXT,
                font=("Microsoft YaHei UI", 10),
                anchor="nw",
                justify="left",
                wraplength=self.WIDTH - 175 if line.speaker else self.WIDTH - 54,
            ).grid(
                row=row,
                column=1 if line.speaker else 0,
                columnspan=1 if line.speaker else 2,
                pady=2,
                sticky="nw",
            )

    def hide_overlay(self) -> None:
        if self._hide_job is not None:
            try:
                self.after_cancel(self._hide_job)
            except tk.TclError:
                pass
            self._hide_job = None
        self.withdraw()

    def _position(self) -> None:
        fallback = (
            int(self.winfo_vrootx()),
            int(self.winfo_vrooty()),
            int(self.winfo_vrootx() + self.winfo_vrootwidth()),
            int(self.winfo_vrooty() + self.winfo_vrootheight()),
        )
        left, top, right, bottom = _monitor_work_area_for_point(
            self._anchor_provider(),
            fallback,
        )
        requested_height = self.winfo_reqheight() + 8
        height = clamp_overlay_height(requested_height, bottom - top)
        x = max(left + 20, right - self.WIDTH - 30)
        y = min(max(top + 70, top + 20), bottom - height - 20)
        self.geometry(f"{self.WIDTH}x{height}{x:+d}{y:+d}")

    def _window_handle(self) -> int:
        handle = int(self.winfo_id())
        if os.name != "nt":
            return handle
        parent = ctypes.windll.user32.GetParent(handle)
        return int(parent or handle)

    def _apply_no_activate_click_through(self) -> None:
        if os.name != "nt":
            return
        try:
            user32 = ctypes.windll.user32
            handle = self._window_handle()
            style = user32.GetWindowLongW(handle, -20)
            style |= 0x00000080  # WS_EX_TOOLWINDOW
            style |= 0x00000020  # WS_EX_TRANSPARENT (mouse click-through)
            style |= 0x00080000  # WS_EX_LAYERED
            style |= 0x08000000  # WS_EX_NOACTIVATE
            user32.SetWindowLongW(handle, -20, style)
        except (AttributeError, OSError):
            return

    def _show_without_activation(self) -> None:
        if os.name != "nt":
            self.lift()
            return
        try:
            user32 = ctypes.windll.user32
            handle = self._window_handle()
            user32.SetWindowPos(
                handle,
                -1,  # HWND_TOPMOST
                0,
                0,
                0,
                0,
                0x0001 | 0x0002 | 0x0010 | 0x0040,
            )
        except (AttributeError, OSError):
            self.lift()
