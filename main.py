from __future__ import annotations

import ctypes
import sys


def enable_windows_dpi_awareness() -> None:
    if sys.platform != "win32":
        return

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def main() -> None:
    enable_windows_dpi_awareness()

    from rift_translate.app import RiftTranslateApp

    app = RiftTranslateApp()
    app.mainloop()


if __name__ == "__main__":
    main()
