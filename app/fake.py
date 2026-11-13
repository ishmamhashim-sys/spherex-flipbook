"""Placeholder sky frames for the skeleton UI (never label as real SPHEREx)."""
from __future__ import annotations

import io
import random

from PIL import Image, ImageDraw

N_FRAMES = 8
SIZE = 256


def fake_frame_list(ra: float, dec: float, fov: float = 0.1) -> list[dict]:
    return [
        {"id": str(i), "mjd": 60800 + i * 30, "band": "fake", "status": "placeholder"}
        for i in range(N_FRAMES)
    ]


def render_fake_png(i: int, ra: float, dec: float, fov: float = 0.1) -> bytes:
    rng = random.Random(int(ra * 1000) + int(dec * 1000))
    img = Image.new("L", (SIZE, SIZE), 10)
    d = ImageDraw.Draw(img)
    for _ in range(40):
        x, y = rng.randrange(SIZE), rng.randrange(SIZE)
        d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=200)
    x = 40 + (i % N_FRAMES) * 25
    d.ellipse((x - 4, 124, x + 4, 132), fill=255)
    # watermark so nobody confuses with real data
    d.text((8, 8), "FAKE (not SPHEREx)", fill=160)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
