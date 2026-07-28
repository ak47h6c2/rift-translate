from __future__ import annotations

import os
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from typing import Any, Callable

import customtkinter as ctk
from openai import APIConnectionError, APIStatusError, AuthenticationError, RateLimitError
from pynput import keyboard

from rift_translate.audio import AudioRecorder
from rift_translate.capture import capture_region, virtual_desktop_bounds
from rift_translate.clipboard import (
    ClipboardWriteError,
    copy_text_compatible,
    native_clipboard_owner,
)
from rift_translate.config import AppSettings, ChatRegion, has_api_key
from rift_translate.game_input import (
    TextInputResult,
    is_league_foreground,
    send_league_text_once,
)
from rift_translate.hotkeys import (
    CHAT_HOTKEY_PRESETS,
    OneShotHotkeyLatch,
    pynput_hotkey_spec,
)
from rift_translate.overlay import (
    GameOverlay,
    OverlayChatLine,
    OverlayContent,
    build_chat_overlay_content,
    voice_panel_font_size,
)
from rift_translate.service import TranslationService


BG = "#07111F"
PANEL = "#0D1B2D"
PANEL_ALT = "#11243A"
GOLD = "#C89B3C"
GOLD_HOVER = "#E0B95B"
TEAL = "#2BB7A9"
TEXT = "#F3F6FA"
MUTED = "#8FA7BD"
ERROR = "#F26D78"
FILL_HOTKEY_VK = 0x76
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
LLKHF_INJECTED = 0x10
LLKHF_LOWER_IL_INJECTED = 0x02
PENDING_INPUT_TTL_SECONDS = 45


class RegionSelector(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        on_selected: Callable[[ChatRegion], None],
    ) -> None:
        super().__init__(parent)
        self.on_selected = on_selected
        self.bounds = virtual_desktop_bounds()
        self.start_x = 0
        self.start_y = 0
        self.rectangle: int | None = None

        geometry = (
            f"{self.bounds.width}x{self.bounds.height}"
            f"{self.bounds.left:+d}{self.bounds.top:+d}"
        )
        self.geometry(geometry)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.42)

        self.canvas = tk.Canvas(self, bg="#02060C", highlightthickness=0, cursor="cross")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_text(
            self.bounds.width // 2,
            52,
            text="拖动框选游戏聊天区域  ·  Esc 取消",
            fill="#FFFFFF",
            font=("Microsoft YaHei UI", 20, "bold"),
        )
        self.canvas.bind("<ButtonPress-1>", self._start)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._finish)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.focus_force()

    def _start(self, event: tk.Event) -> None:
        self.start_x = int(event.x)
        self.start_y = int(event.y)
        if self.rectangle is not None:
            self.canvas.delete(self.rectangle)
        self.rectangle = self.canvas.create_rectangle(
            self.start_x,
            self.start_y,
            self.start_x,
            self.start_y,
            outline=GOLD,
            width=4,
            fill="#173B56",
        )

    def _drag(self, event: tk.Event) -> None:
        if self.rectangle is not None:
            self.canvas.coords(
                self.rectangle,
                self.start_x,
                self.start_y,
                int(event.x),
                int(event.y),
            )

    def _finish(self, event: tk.Event) -> None:
        end_x, end_y = int(event.x), int(event.y)
        left = min(self.start_x, end_x)
        top = min(self.start_y, end_y)
        width = abs(end_x - self.start_x)
        height = abs(end_y - self.start_y)
        if width < 80 or height < 45:
            self.destroy()
            return
        region = ChatRegion(
            left=self.bounds.left + left,
            top=self.bounds.top + top,
            width=width,
            height=height,
        )
        self.destroy()
        self.on_selected(region)


class RiftTranslateApp(ctk.CTk):
    def __init__(self) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        super().__init__(fg_color=BG)

        self.title("峡谷翻译助手")
        self.geometry("1160x760")
        self.minsize(1020, 680)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.settings = AppSettings.load()
        self.recorder = AudioRecorder()
        self.service: TranslationService | None = None
        self.listener: keyboard.Listener | None = None
        self._chat_hotkey: keyboard.HotKey | None = None
        self._f8_down = False
        self._busy_count = 0
        self._latest_reply = ""
        self._pending_english = ""
        self._pending_english_deadline = 0.0
        self._pending_generation = 0
        self._typing_pending = False
        self._fill_hotkey_latch = OneShotHotkeyLatch()
        self._hotkey_events: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._league_foreground_cached = False
        self._next_foreground_refresh = 0.0
        self._closing = False

        self._build_ui()
        self.overlay = GameOverlay(self, self._overlay_anchor)
        # Creating a native Toplevel maps CustomTkinter's root earlier than usual,
        # so explicitly show the main setup window on first launch.
        self.deiconify()
        self._start_hotkeys()
        self.after(20, self._poll_hotkey_events)

        if has_api_key():
            self.service = TranslationService(self.settings)
            self.set_status(
                f"已就绪 · F8 语音 · {self.settings.chat_hotkey} 翻译聊天",
                "ready",
            )
        else:
            self.set_status("缺少 OPENAI_API_KEY，请检查 .env.local", "error")

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        header.grid(row=0, column=0, padx=26, pady=(22, 12), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            header,
            text="峡谷翻译助手",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=27, weight="bold"),
            text_color=TEXT,
        )
        title.grid(row=0, column=0, sticky="w")
        subtitle = ctk.CTkLabel(
            header,
            text="双向翻译 · 游戏俚语 · 不读取游戏内存",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
            text_color=MUTED,
        )
        subtitle.grid(row=1, column=0, pady=(2, 0), sticky="w")

        self.status_badge = ctk.CTkLabel(
            header,
            text="正在启动…",
            height=34,
            corner_radius=17,
            fg_color=PANEL_ALT,
            text_color=MUTED,
            padx=16,
        )
        self.status_badge.grid(row=0, column=1, rowspan=2, sticky="e")

        body = ctk.CTkFrame(self, fg_color=BG)
        body.grid(row=1, column=0, padx=26, pady=(0, 24), sticky="nsew")
        body.grid_columnconfigure((0, 1), weight=1, uniform="column")
        body.grid_rowconfigure(0, weight=1)

        self._build_voice_panel(body)
        self._build_chat_panel(body)

    def _build_voice_panel(self, parent: ctk.CTkFrame) -> None:
        panel = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=18)
        panel.grid(row=0, column=0, padx=(0, 8), sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(5, weight=1)

        ctk.CTkLabel(
            panel,
            text="我想对队友说",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=20, weight="bold"),
            text_color=TEXT,
        ).grid(row=0, column=0, padx=22, pady=(22, 3), sticky="w")
        ctk.CTkLabel(
            panel,
            text="按住 F8 说中文；翻译完成后在联盟聊天框按 F7 填入",
            text_color=MUTED,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
        ).grid(row=1, column=0, padx=22, pady=(0, 14), sticky="w")

        self.record_button = ctk.CTkButton(
            panel,
            text="按住说话  F8",
            height=58,
            corner_radius=14,
            fg_color=GOLD,
            hover_color=GOLD_HOVER,
            text_color="#07111F",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=17, weight="bold"),
        )
        self.record_button.grid(row=2, column=0, padx=22, pady=(0, 18), sticky="ew")
        self.record_button.bind("<ButtonPress-1>", lambda _event: self.start_recording())
        self.record_button.bind("<ButtonRelease-1>", lambda _event: self.stop_recording())

        ctk.CTkLabel(panel, text="中文识别", text_color=MUTED).grid(
            row=3, column=0, padx=22, sticky="w"
        )
        self.chinese_box = ctk.CTkTextbox(
            panel,
            height=105,
            fg_color=PANEL_ALT,
            corner_radius=12,
            border_width=0,
            text_color=TEXT,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=14),
            wrap="word",
        )
        self.chinese_box.grid(row=4, column=0, padx=22, pady=(7, 16), sticky="ew")

        result_frame = ctk.CTkFrame(panel, fg_color=PANEL_ALT, corner_radius=12)
        result_frame.grid(row=5, column=0, padx=22, pady=(0, 16), sticky="nsew")
        result_frame.grid_columnconfigure(0, weight=1)
        result_frame.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            result_frame,
            text="游戏英语",
            text_color=TEAL,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13, weight="bold"),
        ).grid(row=0, column=0, padx=14, pady=(12, 4), sticky="w")
        self.english_box = ctk.CTkTextbox(
            result_frame,
            fg_color="transparent",
            text_color=TEXT,
            font=ctk.CTkFont(family="Segoe UI", size=14),
            wrap="word",
        )
        self.english_box.grid(row=1, column=0, padx=9, pady=(0, 8), sticky="nsew")

        footer = ctk.CTkFrame(panel, fg_color="transparent")
        footer.grid(row=6, column=0, padx=22, pady=(0, 20), sticky="ew")
        footer.grid_columnconfigure((0, 1), weight=1)
        self.auto_copy_switch = ctk.CTkSwitch(
            footer,
            text="翻译后同时复制（备用）",
            command=self._toggle_auto_copy,
            progress_color=TEAL,
            text_color=MUTED,
        )
        self.auto_copy_switch.grid(row=0, column=0, sticky="w")
        if self.settings.auto_copy:
            self.auto_copy_switch.select()
        ctk.CTkButton(
            footer,
            text="复制英文",
            width=100,
            fg_color=PANEL_ALT,
            hover_color="#193550",
            command=self.copy_english,
        ).grid(row=0, column=1, sticky="e")
        self.overlay_switch = ctk.CTkSwitch(
            footer,
            text="游戏内悬浮字幕（零切换）",
            command=self._toggle_overlay,
            progress_color=GOLD,
            text_color=MUTED,
        )
        self.overlay_switch.grid(
            row=1, column=0, pady=(14, 0), sticky="w"
        )
        if self.settings.overlay_enabled:
            self.overlay_switch.select()
        ctk.CTkButton(
            footer,
            text="预览悬浮字幕",
            width=112,
            fg_color=PANEL_ALT,
            hover_color="#193550",
            command=self.preview_overlay,
        ).grid(row=1, column=1, pady=(14, 0), sticky="e")

    def _build_chat_panel(self, parent: ctk.CTkFrame) -> None:
        panel = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=18)
        panel.grid(row=0, column=1, padx=(8, 0), sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(6, weight=1)

        ctk.CTkLabel(
            panel,
            text="队友在说什么",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=20, weight="bold"),
            text_color=TEXT,
        ).grid(row=0, column=0, padx=22, pady=(22, 3), sticky="w")
        self.chat_subtitle = ctk.CTkLabel(
            panel,
            text=(
                f"{self.settings.chat_hotkey} 截取聊天区；"
                "召唤师名保持原样，只显示简洁中文"
            ),
            text_color=MUTED,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
        )
        self.chat_subtitle.grid(
            row=1, column=0, padx=22, pady=(0, 12), sticky="w"
        )

        capture_bar = ctk.CTkFrame(panel, fg_color="transparent")
        capture_bar.grid(row=2, column=0, padx=22, pady=(0, 12), sticky="ew")
        capture_bar.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(
            capture_bar,
            text="① 选择聊天区域",
            height=40,
            fg_color=PANEL_ALT,
            hover_color="#193550",
            command=self.select_chat_region,
        ).grid(row=0, column=0, padx=(0, 5), sticky="ew")
        self.capture_button = ctk.CTkButton(
            capture_bar,
            text=f"② 截图翻译  {self.settings.chat_hotkey}",
            height=40,
            fg_color=TEAL,
            hover_color="#3BC7B8",
            text_color="#061716",
            command=self.capture_and_translate,
        )
        self.capture_button.grid(row=0, column=1, padx=(5, 0), sticky="ew")

        chat_settings = ctk.CTkFrame(panel, fg_color="transparent")
        chat_settings.grid(row=3, column=0, padx=22, pady=(0, 10), sticky="ew")
        chat_settings.grid_columnconfigure(0, weight=1)
        self.region_label = ctk.CTkLabel(
            chat_settings,
            text=self._region_description(),
            text_color=MUTED,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=11),
        )
        self.region_label.grid(row=0, column=0, sticky="w")
        self.hotkey_menu = ctk.CTkOptionMenu(
            chat_settings,
            values=list(CHAT_HOTKEY_PRESETS),
            command=self._change_chat_hotkey,
            width=142,
            height=30,
            fg_color=PANEL_ALT,
            button_color="#193550",
            button_hover_color="#234663",
        )
        self.hotkey_menu.set(self.settings.chat_hotkey)
        self.hotkey_menu.grid(row=0, column=1, sticky="e")

        self.chat_input = ctk.CTkTextbox(
            panel,
            height=90,
            fg_color=PANEL_ALT,
            corner_radius=12,
            text_color=TEXT,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            wrap="word",
        )
        self.chat_input.grid(row=4, column=0, padx=22, pady=(0, 9), sticky="ew")
        self.chat_input.insert("1.0", "Paste chat here, e.g. jg diff, stop inting and play for drake")
        self.chat_input.bind("<Control-Return>", lambda _event: self.translate_manual_chat())

        input_actions = ctk.CTkFrame(panel, fg_color="transparent")
        input_actions.grid(row=5, column=0, padx=22, pady=(0, 13), sticky="ew")
        input_actions.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(
            input_actions,
            text="从剪贴板粘贴",
            width=120,
            fg_color=PANEL_ALT,
            hover_color="#193550",
            command=self.paste_chat,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            input_actions,
            text="翻译并解释  Ctrl+Enter",
            width=170,
            fg_color=GOLD,
            hover_color=GOLD_HOVER,
            text_color="#07111F",
            command=self.translate_manual_chat,
        ).grid(row=0, column=1, sticky="e")

        self.chat_output = ctk.CTkTextbox(
            panel,
            fg_color=PANEL_ALT,
            corner_radius=12,
            text_color=TEXT,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
            wrap="word",
        )
        self.chat_output.grid(row=6, column=0, padx=22, pady=(0, 10), sticky="nsew")
        self._replace_text(
            self.chat_output,
            "识别结果会显示在这里。\n\n"
            "例：jg diff → “打野差距”，通常是在责怪双方打野表现差异。",
        )

        ctk.CTkButton(
            panel,
            text="复制建议回复",
            height=36,
            fg_color="transparent",
            border_width=1,
            border_color="#2A4963",
            hover_color=PANEL_ALT,
            command=self.copy_reply,
        ).grid(row=7, column=0, padx=22, pady=(0, 20), sticky="ew")

    def _start_hotkeys(self) -> None:
        self._chat_hotkey = self._make_chat_hotkey(self.settings.chat_hotkey)

        def win32_event_filter(msg: int, data: object) -> bool:
            if int(data.vkCode) != FILL_HOTKEY_VK:
                return True
            if int(data.flags) & (LLKHF_INJECTED | LLKHF_LOWER_IL_INJECTED):
                return True

            if msg in (WM_KEYDOWN, WM_SYSKEYDOWN):
                league_foreground = self._league_foreground_cached
                decision = self._fill_hotkey_latch.key_down(
                    can_trigger=(
                        self._has_pending_game_text()
                        and league_foreground
                    ),
                    block_only=(
                        (
                            self._typing_pending
                            or self._fill_hotkey_latch.has_queued_trigger()
                        )
                        and league_foreground
                    ),
                )
                if decision.suppress and self.listener is not None:
                    self.listener.suppress_event()
                return True

            if msg in (WM_KEYUP, WM_SYSKEYUP):
                decision = self._fill_hotkey_latch.key_up()
                if decision.trigger:
                    self._hotkey_events.put("fill_pending")
                if decision.suppress and self.listener is not None:
                    self.listener.suppress_event()
            return True

        def on_press(key: keyboard.Key | keyboard.KeyCode | None) -> None:
            if (
                key is not None
                and self.listener is not None
                and self._chat_hotkey is not None
            ):
                self._chat_hotkey.press(self.listener.canonical(key))
            if key == keyboard.Key.f8 and not self._f8_down:
                self._f8_down = True
                self.after(0, self._start_recording_from_hotkey)
            elif key == keyboard.Key.f10:
                self.after(0, self.toggle_visibility)

        def on_release(key: keyboard.Key | keyboard.KeyCode | None) -> None:
            if (
                key is not None
                and self.listener is not None
                and self._chat_hotkey is not None
            ):
                self._chat_hotkey.release(self.listener.canonical(key))
            if key == keyboard.Key.f8:
                self._f8_down = False
                self.after(0, self.stop_recording)

        self.listener = keyboard.Listener(
            on_press=on_press,
            on_release=on_release,
            win32_event_filter=win32_event_filter,
        )
        self.listener.daemon = True
        self.listener.start()

    def _poll_hotkey_events(self) -> None:
        if self._closing:
            return

        now = time.monotonic()
        if now >= self._next_foreground_refresh:
            self._league_foreground_cached = is_league_foreground()
            self._next_foreground_refresh = now + 0.25

        while True:
            try:
                event = self._hotkey_events.get_nowait()
            except queue.Empty:
                break
            if event == "fill_pending":
                self._type_pending_from_hotkey()

        self.after(20, self._poll_hotkey_events)

    def _has_pending_game_text(self) -> bool:
        return bool(
            self._pending_english
            and not self._typing_pending
            and time.monotonic() <= self._pending_english_deadline
        )

    def _clear_pending_game_text(self) -> None:
        self._pending_generation += 1
        self._pending_english = ""
        self._pending_english_deadline = 0.0
        self._typing_pending = False
        self._fill_hotkey_latch.mark_trigger_handled()

    def _consume_pending_game_text(self) -> str:
        english = self._pending_english
        self._pending_generation += 1
        self._pending_english = ""
        self._pending_english_deadline = 0.0
        self._fill_hotkey_latch.mark_trigger_handled()
        return english

    def _expire_pending_game_text(self, generation: int) -> None:
        if (
            generation != self._pending_generation
            or not self._pending_english
            or self._typing_pending
        ):
            return
        self._clear_pending_game_text()
        self.set_status("待输入的英文已过期，请重新按 F8 说话", "info")

    def _make_chat_hotkey(self, label: str) -> keyboard.HotKey:
        return keyboard.HotKey(
            keyboard.HotKey.parse(pynput_hotkey_spec(label)),
            lambda: self.after(0, self._capture_from_hotkey),
        )

    def _change_chat_hotkey(self, label: str) -> None:
        self.settings.chat_hotkey = label
        self.settings.save()
        self._chat_hotkey = self._make_chat_hotkey(label)
        self.capture_button.configure(text=f"② 截图翻译  {label}")
        self.chat_subtitle.configure(
            text=f"{label} 截取聊天区；召唤师名保持原样，只显示简洁中文"
        )
        self.set_status(f"聊天翻译热键已改为 {label}", "ready")

    def set_status(self, message: str, kind: str = "info") -> None:
        colors = {
            "ready": (PANEL_ALT, TEAL),
            "info": (PANEL_ALT, MUTED),
            "busy": ("#2B2945", "#C7B7FF"),
            "error": ("#3A1C29", ERROR),
        }
        background, foreground = colors.get(kind, colors["info"])
        self.status_badge.configure(
            text=message, fg_color=background, text_color=foreground
        )

    def _overlay_anchor(self) -> tuple[int, int]:
        region = self.settings.chat_region
        if region is not None:
            return (
                region.left + region.width // 2,
                region.top + region.height // 2,
            )
        return (self.winfo_screenwidth() // 2, self.winfo_screenheight() // 2)

    def _show_game_overlay(self, content: OverlayContent) -> None:
        if not self.settings.overlay_enabled or self.state() != "withdrawn":
            return
        self.overlay.show_content(content)

    def _enter_game_mode(self) -> None:
        if self.settings.overlay_enabled and self.state() != "withdrawn":
            self.withdraw()

    def _start_recording_from_hotkey(self) -> None:
        self._enter_game_mode()
        self.start_recording()

    def _capture_from_hotkey(self) -> None:
        self._enter_game_mode()
        self.capture_and_translate()

    def _service_or_error(self) -> TranslationService | None:
        if self.service is None:
            self.set_status("API 密钥不可用，请检查 .env.local", "error")
            return None
        return self.service

    def start_recording(self) -> None:
        if self.recorder.is_recording or self._busy_count:
            return
        self._clear_pending_game_text()
        try:
            self.recorder.start()
        except Exception as exc:
            self.set_status(f"麦克风错误：{exc}", "error")
            return
        self.record_button.configure(text="正在听… 松开翻译", fg_color=ERROR)
        self.set_status("正在录音，只会发送你按住期间的声音", "busy")
        self._show_game_overlay(
            OverlayContent(
                title="F8 语音",
                body="正在听你说话…",
                footer="松开 F8 后翻译；完成后在聊天输入框按 F7 填入",
                kind="recording",
                duration_ms=0,
            )
        )

    def stop_recording(self) -> None:
        if not self.recorder.is_recording:
            return
        self.record_button.configure(text="按住说话  F8", fg_color=GOLD)
        try:
            audio_path = self.recorder.stop()
        except Exception as exc:
            self.set_status(str(exc), "error")
            return

        service = self._service_or_error()
        if service is None:
            audio_path.unlink(missing_ok=True)
            return

        def work() -> dict[str, str]:
            try:
                return service.voice_pipeline(audio_path)
            finally:
                audio_path.unlink(missing_ok=True)

        self._run_task("正在识别并翻译语音…", work, self._show_voice_result)

    def _show_voice_result(self, result: dict[str, str]) -> None:
        chinese = result["chinese"]
        english = result["english"]
        self._replace_text(self.chinese_box, chinese)
        self.english_box.configure(
            font=ctk.CTkFont(
                family="Segoe UI",
                size=voice_panel_font_size(english),
            )
        )
        self._replace_text(self.english_box, english)
        self.english_box.see("1.0")
        self._pending_generation += 1
        generation = self._pending_generation
        self._pending_english = english
        self._pending_english_deadline = (
            time.monotonic() + PENDING_INPUT_TTL_SECONDS
        )
        self._typing_pending = False
        self.after(
            PENDING_INPUT_TTL_SECONDS * 1_000,
            lambda current_generation=generation: self._expire_pending_game_text(
                current_generation
            ),
        )

        copied = False
        if self.settings.auto_copy:
            copied = self._copy_text(english)

        self.set_status("翻译完成 · 游戏内 Enter → 点击输入框 → F7 填入", "ready")
        footer = "Enter → 点输入框 → F7；检查后 Enter"
        if copied:
            footer += " · 剪贴板仅作备用"

        self._show_game_overlay(
            OverlayContent(
                title="英文已就绪",
                body=english,
                footer=footer,
                kind="voice",
                duration_ms=PENDING_INPUT_TTL_SECONDS * 1_000,
            )
        )

    def _type_pending_from_hotkey(self) -> None:
        self._fill_hotkey_latch.mark_trigger_handled()
        if self._typing_pending or not self._pending_english:
            return
        if time.monotonic() > self._pending_english_deadline:
            self._clear_pending_game_text()
            self.set_status("待输入的英文已过期，请重新按 F8 说话", "info")
            self._show_game_overlay(
                OverlayContent(
                    title="英文已过期",
                    body="请重新按住 F8 说话并翻译。",
                    kind="error",
                    duration_ms=5_000,
                )
            )
            return
        if self._busy_count:
            return

        english = self._consume_pending_game_text()
        self._typing_pending = True

        def work() -> TextInputResult:
            return send_league_text_once(
                english,
                event_delay_ms=20,
                unicode_spaces=True,
            )

        def completed(result: TextInputResult) -> None:
            self._typing_pending = False
            self._clear_pending_game_text()
            if result.foreground_unchanged:
                self.set_status("英文已填入联盟聊天框 · 实体 Enter 发送", "ready")
                footer = "请检查内容，然后按实体 Enter 发送"
            else:
                self.set_status("英文已填入，但前台窗口随后发生变化", "error")
                footer = "不会继续输入；请回到联盟检查聊天框"
            self._show_game_overlay(
                OverlayContent(
                    title="英文已填入（尚未发送）",
                    body=result.text,
                    footer=footer,
                    kind="voice",
                    duration_ms=12_000,
                )
            )

        def failed(_exc: Exception) -> None:
            self._typing_pending = False
            self._fill_hotkey_latch.mark_trigger_handled()
            self._show_game_overlay(
                OverlayContent(
                    title="填入已停止",
                    body="本条翻译不会自动重试，以免重复追加；若聊天框已有前缀，请按实体 Esc 清空。",
                    kind="error",
                    duration_ms=9_000,
                )
            )

        self._run_task(
            "正在把英文写入联盟聊天框…期间请勿操作键鼠",
            work,
            completed,
            on_error=failed,
        )

    def copy_english(self) -> None:
        text = self.english_box.get("1.0", "end").strip()
        if not text:
            self.set_status("还没有可复制的英文", "info")
            return
        if self._copy_text(text):
            self.set_status("英文已写入 Windows 兼容剪贴板", "ready")

    def _toggle_auto_copy(self) -> None:
        self.settings.auto_copy = bool(self.auto_copy_switch.get())
        self.settings.save()

    def _toggle_overlay(self) -> None:
        self.settings.overlay_enabled = bool(self.overlay_switch.get())
        self.settings.save()
        if not self.settings.overlay_enabled:
            self.overlay.hide_overlay()

    def preview_overlay(self) -> None:
        if not self.settings.overlay_enabled:
            self.set_status("请先开启“游戏内悬浮字幕”", "info")
            return
        self.withdraw()
        self.overlay.show_content(
            OverlayContent(
                title="聊天翻译",
                body="ExamplePlayer：布隆，你能用 E 帮我挡一下吗？",
                footer="悬浮字幕不会抢焦点 · 鼠标可穿透 · F10 返回设置",
                kind="chat",
                duration_ms=30_000,
                chat_lines=(
                    OverlayChatLine(
                        speaker="ExamplePlayer",
                        message="布隆，你能用 E 帮我挡一下吗？",
                    ),
                ),
            )
        )

    def select_chat_region(self) -> None:
        self.set_status("请拖动框选游戏聊天区域", "info")

        def selected(region: ChatRegion) -> None:
            self.settings.chat_region = region
            self.settings.save()
            self.region_label.configure(text=self._region_description())
            self.set_status(
                f"聊天区域已保存，按 {self.settings.chat_hotkey} 即可翻译",
                "ready",
            )

        RegionSelector(self, selected)

    def _region_description(self) -> str:
        region = self.settings.chat_region
        if region is None:
            return "尚未选择聊天区域"
        return (
            f"聊天区域：{region.width}×{region.height} "
            f"@ ({region.left}, {region.top})"
        )

    def capture_and_translate(self) -> None:
        region = self.settings.chat_region
        if region is None:
            self.set_status("请先点击“选择聊天区域”", "error")
            return
        service = self._service_or_error()
        if service is None:
            return

        try:
            png_bytes = capture_region(region)
        except Exception as exc:
            self._finish_error(exc)
            return

        self._run_task(
            "正在读取并翻译聊天截图…",
            lambda: service.translate_chat_image(png_bytes),
            self._show_chat_result,
        )

    def paste_chat(self) -> None:
        try:
            value = self.clipboard_get()
        except tk.TclError:
            value = ""
        self._replace_text(self.chat_input, value)

    def translate_manual_chat(self) -> None:
        text = self.chat_input.get("1.0", "end").strip()
        placeholder = "Paste chat here, e.g."
        if not text or text.startswith(placeholder):
            self.set_status("请先粘贴要翻译的英文聊天", "error")
            return
        service = self._service_or_error()
        if service is None:
            return
        self._run_task(
            "正在解释聊天和游戏俚语…",
            lambda: service.translate_chat_text(text),
            self._show_chat_result,
        )

    def _show_chat_result(self, result: dict[str, Any]) -> None:
        chunks: list[str] = []
        tone_labels = {
            "neutral": "普通",
            "positive": "友好",
            "shotcall": "战术指令",
            "sarcastic": "讽刺",
            "toxic": "攻击性",
        }
        for line in result.get("lines", []):
            speaker = line.get("speaker", "")
            chinese = line.get("chinese", "")
            tone = tone_labels.get(line.get("tone", "neutral"), line.get("tone", ""))
            heading = speaker or "队伍聊天"
            if tone and tone != "普通":
                heading = f"{heading} · {tone}"
            chunks.append(heading)
            chunks.append(chinese or "（未识别到消息内容）")
            if line.get("notes"):
                chunks.append(f"说明：{line['notes']}")
            chunks.append("")

        if result.get("summary") and len(result.get("lines", [])) > 1:
            chunks.append(f"局势：{result['summary']}\n")

        terms = result.get("terms", [])
        if terms:
            rendered_terms = " · ".join(
                f"{item.get('term', '')}={item.get('meaning', '')}" for item in terms
            )
            chunks.append(f"缩写：{rendered_terms}")
            chunks.append("")

        reply = result.get("reply_suggestion", "")
        self._latest_reply = reply
        if reply:
            chunks.append(f"建议回复：{reply}")

        rendered = "\n".join(chunks).strip() or "没有识别到可翻译的聊天内容。"
        self._replace_text(self.chat_output, rendered)
        self.set_status("聊天翻译完成", "ready")
        self._show_game_overlay(
            build_chat_overlay_content(
                result,
                hotkey_label=self.settings.chat_hotkey,
            )
        )

    def copy_reply(self) -> None:
        if not self._latest_reply:
            self.set_status("当前没有建议回复", "info")
            return
        if self._copy_text(self._latest_reply):
            self.set_status("建议回复已写入 Windows 兼容剪贴板", "ready")

    def _copy_text(self, text: str) -> bool:
        try:
            owner = native_clipboard_owner(self.winfo_id())
            copy_text_compatible(text, owner_hwnd=owner)
            return True
        except (ClipboardWriteError, OSError):
            try:
                self.clipboard_clear()
                self.clipboard_append(text)
                self.update_idletasks()
                return True
            except tk.TclError:
                self.set_status("无法写入 Windows 剪贴板，请稍后重试", "error")
                return False

    def _run_task(
        self,
        label: str,
        work: Callable[[], Any],
        on_success: Callable[[Any], None],
        *,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        if self._busy_count:
            self.set_status("正在处理上一个请求，请稍等", "info")
            self._show_game_overlay(
                OverlayContent(
                    title="翻译助手",
                    body="正在处理上一个请求，请稍等…",
                    kind="busy",
                    duration_ms=3_000,
                )
            )
            return
        self._busy_count += 1
        self.set_status(label, "busy")
        self._show_game_overlay(
            OverlayContent(
                title="翻译助手",
                body=label,
                footer="完成后会直接显示在游戏画面上",
                kind="busy",
                duration_ms=0,
            )
        )

        def runner() -> None:
            try:
                result = work()
            except Exception as exc:
                self.after(
                    0,
                    lambda error=exc: self._finish_task_error(
                        error,
                        on_error,
                    ),
                )
            else:
                self.after(
                    0,
                    lambda value=result: self._finish_success(
                        value,
                        on_success,
                    ),
                )

        threading.Thread(target=runner, daemon=True).start()

    def _finish_success(
        self, result: Any, on_success: Callable[[Any], None]
    ) -> None:
        self._busy_count = max(0, self._busy_count - 1)
        on_success(result)

    def _finish_task_error(
        self,
        exc: Exception,
        on_error: Callable[[Exception], None] | None,
    ) -> None:
        self._finish_error(exc)
        if on_error is not None:
            on_error(exc)

    def _finish_error(self, exc: Exception) -> None:
        self._busy_count = max(0, self._busy_count - 1)
        if isinstance(exc, AuthenticationError):
            message = "API 密钥无效或项目权限不足。"
        elif isinstance(exc, RateLimitError):
            message = "API 额度、余额或请求频率受限，请检查 Platform Billing。"
        elif isinstance(exc, APIConnectionError):
            message = "无法连接 OpenAI，请检查网络或代理。"
        elif isinstance(exc, APIStatusError):
            message = f"OpenAI 请求失败（HTTP {exc.status_code}）。"
        else:
            message = str(exc) or exc.__class__.__name__
        self.set_status(message, "error")
        self._show_game_overlay(
            OverlayContent(
                title="翻译失败",
                body=message,
                footer="按 F10 打开助手查看设置",
                kind="error",
                duration_ms=9_000,
            )
        )

    @staticmethod
    def _replace_text(widget: ctk.CTkTextbox, text: str) -> None:
        widget.delete("1.0", "end")
        widget.insert("1.0", text)

    def toggle_visibility(self) -> None:
        if self.state() == "withdrawn":
            self.overlay.hide_overlay()
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self.after(150, lambda: self.attributes("-topmost", False))
        else:
            self.withdraw()

    def _on_close(self) -> None:
        self._closing = True
        self.recorder.cancel()
        if self.listener is not None:
            self.listener.stop()
        self.overlay.destroy()
        self.destroy()
