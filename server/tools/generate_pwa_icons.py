#!/usr/bin/env python3
"""Regenerate surgeon PWA icons (Clinical Trust blue, calendar glyph). Requires Pillow."""
from PIL import Image, ImageDraw

def make_icon(size: int) -> Image.Image:
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d2 = ImageDraw.Draw(out)
    m = max(2, size // 32)
    r = size // 5
    d2.rounded_rectangle([m, m, size - m, size - m], radius=r, fill=(0, 102, 204, 255))
    hs = size // 5
    d2.rounded_rectangle([m + m, m + m, size - m - m, m + hs], radius=max(4, size // 28), fill=(255, 255, 255, 38))
    wp = size // 5
    cx1, cx2 = m + wp, size - m - wp
    cy1 = m + size // 4
    cy2 = size - m - wp
    lw = max(2, size // 64)
    d2.rounded_rectangle([cx1, cy1, cx2, cy2], radius=max(4, size // 24), outline=(255, 255, 255, 230), width=lw)
    midy = cy1 + (cy2 - cy1) // 3
    d2.line([(cx1 + lw, midy), (cx2 - lw, midy)], fill=(255, 255, 255, 200), width=lw)
    dot = max(3, size // 28)
    d2.ellipse(
        [cx1 + wp // 2, midy + (cy2 - midy) // 4 - dot // 2, cx1 + wp // 2 + dot, midy + (cy2 - midy) // 4 + dot // 2],
        fill=(255, 255, 255, 255),
    )
    d2.ellipse(
        [cx2 - wp // 2 - dot, midy + (cy2 - midy) // 2 - dot // 2, cx2 - wp // 2, midy + (cy2 - midy) // 2 + dot // 2],
        fill=(255, 255, 255, 230),
    )
    return out


if __name__ == "__main__":
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "app" / "static"
    for name, sz in [("icon-192.png", 192), ("icon-512.png", 512), ("apple-touch-icon.png", 180)]:
        p = root / name
        make_icon(sz).save(p, "PNG")
        print("wrote", p)
