"""Make the gold versions of the Loudstudio mark (flame and record) used as favicon and in the header.

The old site only had the mark in blue (favicon-loudstudio.png). This recolours its
blue to the site's gold and keeps the black and white of the record as they are.

Usage:  python website/tools/make_gold_icons.py      (needs Pillow; run after fetch_assets.py)
Writes public/assets/img/brand/mark-gold-{32,180,192,512}.png.
"""

from pathlib import Path

from PIL import Image

BRAND = Path(__file__).resolve().parent.parent / "public" / "assets" / "img" / "brand"
GOLD = (168, 146, 94)          # --accent in style.css (#a8925e)
BLUE = (0, 159, 227)           # the blue of the original mark
SIZES = (32, 180, 192, 512)


def recolour(img):
    """Blend each pixel towards gold by how blue it is (b - r), so edges stay smooth."""
    span = BLUE[2] - BLUE[0]
    out = []
    for r, g, b, a in getattr(img, "get_flattened_data", img.getdata)():
        t = max(0.0, min(1.0, (b - r) / span))
        out.append((
            round(r * (1 - t) + GOLD[0] * t),
            round(g * (1 - t) + GOLD[1] * t),
            round(b * (1 - t) + GOLD[2] * t),
            a,
        ))
    gold = Image.new("RGBA", img.size)
    gold.putdata(out)
    return gold


def main():
    source = Image.open(BRAND / "icon-512.png").convert("RGBA")
    gold = recolour(source)
    for size in SIZES:
        out = BRAND / f"mark-gold-{size}.png"
        gold.resize((size, size), Image.LANCZOS).save(out, "PNG", optimize=True)
        print("wrote", out.relative_to(BRAND.parent.parent.parent))


if __name__ == "__main__":
    main()
