"""Make the gold versions of the Loudstudio mark and studio logo.

The old site had the studio logo ("estúdios e produção audio") and the mark
(flame and record) only in blue; the gold logo it had is the Pro Audio one,
which the site keeps for the Li.LAC pages. This recolours the blue to gold and
leaves the white letters and the black and white record as they are.

Usage:  python website/tools/make_gold_brand.py      (needs Pillow; run after fetch_assets.py)
Writes public/assets/img/brand/mark-gold-{32,180,192,512}.png
   and public/assets/img/brand/loudstudio-gold-{480,960}.{png,webp}.
"""

from pathlib import Path

from PIL import Image

BRAND = Path(__file__).resolve().parent.parent / "public" / "assets" / "img" / "brand"
MARK_GOLD = (168, 146, 94)     # --gold in style.css (#a8925e), for the small mark
LOGO_GOLD = (134, 118, 80)     # the gold of the official Pro Audio logo (#867650)
MARK_BLUE = (0, 159, 227)      # the blue of the original mark
LOGO_BLUE = (0, 174, 239)      # the blue of the original logo
SIZES = (32, 180, 192, 512)
LOGO_WIDTHS = (480, 960)


def recolour(img, blue, gold):
    """Blend each pixel towards gold by how blue it is (b - r), so edges stay smooth."""
    span = blue[2] - blue[0]
    out = []
    for r, g, b, a in getattr(img, "get_flattened_data", img.getdata)():
        t = max(0.0, min(1.0, (b - r) / span))
        out.append((
            round(r * (1 - t) + gold[0] * t),
            round(g * (1 - t) + gold[1] * t),
            round(b * (1 - t) + gold[2] * t),
            a,
        ))
    gold = Image.new("RGBA", img.size)
    gold.putdata(out)
    return gold


def main():
    mark = recolour(Image.open(BRAND / "icon-512.png").convert("RGBA"), MARK_BLUE, MARK_GOLD)
    for size in SIZES:
        out = BRAND / f"mark-gold-{size}.png"
        mark.resize((size, size), Image.LANCZOS).save(out, "PNG", optimize=True)
        print("wrote", out.relative_to(BRAND.parent.parent.parent))

    logo = recolour(Image.open(BRAND / "loudstudio-960.png").convert("RGBA"), LOGO_BLUE, LOGO_GOLD)
    for width in LOGO_WIDTHS:
        sized = logo if width == logo.width else logo.resize((width, round(logo.height * width / logo.width)), Image.LANCZOS)
        for fmt, opts in (("png", {"optimize": True}), ("webp", {"quality": 80, "method": 6})):
            out = BRAND / f"loudstudio-gold-{width}.{fmt}"
            sized.save(out, fmt.upper(), **opts)
            print("wrote", out.relative_to(BRAND.parent.parent.parent))


if __name__ == "__main__":
    main()
