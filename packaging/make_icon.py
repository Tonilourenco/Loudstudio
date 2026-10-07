"""Draw the Desk Check app icon (1024x1024 PNG): fader strips under an EQ curve."""

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

K = 4  # draw at 4x and scale down, for smooth (anti-aliased) edges


def main(path: str) -> None:
    s = 1024 * K
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def box(x0, y0, x1, y1):
        return (x0 * K, y0 * K, x1 * K, y1 * K)

    # macOS icon grid: ~824 px rounded square centred on the canvas.
    d.rounded_rectangle(box(100, 100, 924, 924), 185 * K, fill=(28, 32, 40, 255))
    # Fader slots and caps.
    for i, pos in enumerate([0.62, 0.40, 0.55, 0.30]):
        x = 270 + i * 160
        d.rounded_rectangle(box(x - 9, 330, x + 9, 800), 9 * K, fill=(70, 78, 92, 255))
        y = 330 + pos * 470
        d.rounded_rectangle(box(x - 48, y - 26, x + 48, y + 26), 12 * K, fill=(235, 238, 242, 255))
        d.rectangle(box(x - 36, y - 3, x + 36, y + 3), fill=(28, 32, 40, 255))
    # EQ curve (a boost and a cut), stroked by stamping discs along it.
    r = 13
    for i in range(1601):
        x = 190 + i * (834 - 190) / 1600
        y = (250 - 70 * math.exp(-((x - 420) / 75) ** 2)
             + 45 * math.exp(-((x - 640) / 55) ** 2))
        d.ellipse(box(x - r, y - r, x + r, y + r), fill=(255, 170, 40, 255))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    img.resize((1024, 1024), Image.LANCZOS).save(path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "icon.png")
