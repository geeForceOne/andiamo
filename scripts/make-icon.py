"""Draws the Andiamo icon: a clock face with a bold arrow heading out of it.

Writes custom_components/andiamo/brand/icon.png (256 px) and icon@2x.png (512 px).
Run with any Python that has Pillow:  python scripts/make-icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "custom_components" / "andiamo" / "brand"
TEAL = (0, 150, 136, 255)
WHITE = (255, 255, 255, 255)
ORANGE = (255, 152, 0, 255)
SCALE = 4  # Draw large, then shrink for smooth edges.


def draw(size: int) -> Image.Image:
    s = size * SCALE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = s / 256  # One unit of the 256 grid.

    # Clock face, a little left of center so the arrow has room to leave it.
    cx, cy, r = 112 * u, 128 * u, 104 * u
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=TEAL)
    ring = 14 * u
    d.ellipse((cx - r + ring, cy - r + ring, cx + r - ring, cy + r - ring), outline=WHITE, width=int(10 * u))

    # Hands: one straight up, one heading right into the arrow.
    hand = int(16 * u)
    d.line((cx, cy, cx, cy - 58 * u), fill=WHITE, width=hand)
    d.ellipse((cx - 14 * u, cy - 14 * u, cx + 14 * u, cy + 14 * u), fill=WHITE)

    # The arrow: shaft from the center, head past the clock's edge.
    shaft = 26 * u
    d.rounded_rectangle((cx, cy - shaft / 2, 196 * u, cy + shaft / 2), radius=shaft / 2, fill=ORANGE)
    d.polygon(
        [(176 * u, cy - 52 * u), (252 * u, cy), (176 * u, cy + 52 * u)],
        fill=ORANGE,
    )
    d.ellipse((cx - 14 * u, cy - 14 * u, cx + 14 * u, cy + 14 * u), fill=WHITE)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        draw(size).save(OUT / name, optimize=True)
        print(OUT / name)


if __name__ == "__main__":
    main()
