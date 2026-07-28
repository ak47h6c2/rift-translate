from __future__ import annotations

from io import BytesIO

import mss
from PIL import Image

from rift_translate.config import ChatRegion


def capture_region(region: ChatRegion) -> bytes:
    monitor = {
        "left": region.left,
        "top": region.top,
        "width": region.width,
        "height": region.height,
    }
    with mss.mss() as screen:
        shot = screen.grab(monitor)
    image = Image.frombytes("RGB", shot.size, shot.rgb)
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def virtual_desktop_bounds() -> ChatRegion:
    with mss.mss() as screen:
        monitor = screen.monitors[0]
    return ChatRegion(
        left=int(monitor["left"]),
        top=int(monitor["top"]),
        width=int(monitor["width"]),
        height=int(monitor["height"]),
    )
