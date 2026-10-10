#!/usr/bin/env python3
"""Draw the home-screen icons (a football on dark turf). Needs Pillow.

    python3 tools/make_icons.py
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "site" / "icons"
BG, BALL, LACE = (18, 24, 21), (79, 191, 134), (18, 24, 21)


def football(size, scale):
    """Square icon; scale = share of the canvas the ball spans."""
    big = size * 4  # draw large, shrink for smooth edges
    img = Image.new("RGB", (big, big), BG)
    ball = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(ball)
    w, h = big * scale, big * scale * 0.58
    cx = cy = big / 2
    # Lens shape: two circle arcs meeting in points, like a football
    r = ((w / 2) ** 2 + (h / 2) ** 2) / h
    top = []
    for i in range(121):
        x = -w / 2 + w * i / 120
        top.append((cx + x, cy - (math.sqrt(max(r * r - x * x, 0)) - (r - h / 2))))
    d.polygon(top + [(x, 2 * cy - y) for x, y in reversed(top)], fill=BALL)
    lw = max(4, int(big * 0.022))
    d.line([cx - w * 0.2, cy, cx + w * 0.2, cy], fill=LACE, width=lw)
    for i in range(-2, 3):
        x = cx + i * w * 0.075
        d.line([x, cy - h * 0.13, x, cy + h * 0.13], fill=LACE, width=lw)
    ball = ball.rotate(35, resample=Image.BICUBIC, center=(cx, cy))
    img.paste(ball, (0, 0), ball)
    return img.resize((size, size), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    football(192, 0.78).save(OUT / "icon-192.png", optimize=True)
    football(512, 0.78).save(OUT / "icon-512.png", optimize=True)
    football(180, 0.74).save(OUT / "apple-touch-icon.png", optimize=True)
    football(512, 0.58).save(OUT / "icon-maskable-512.png", optimize=True)  # inside the safe zone
    print(f"Icons written to {OUT}")


if __name__ == "__main__":
    main()
