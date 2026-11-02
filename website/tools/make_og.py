"""Make the 1200x630 social sharing images (Open Graph) from the logos and photos.

Usage:  python website/tools/make_og.py      (needs Pillow; run after fetch_assets.py)
Writes public/assets/img/og/loudstudio-og.jpg, lilac-og.jpg and lilac-og-es.jpg.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

PUBLIC = Path(__file__).resolve().parent.parent / "public"
IMG = PUBLIC / "assets" / "img"
FONTS = PUBLIC / "assets" / "fonts"
W, H = 1200, 630
BG = (11, 12, 14)


def font(name, size, weight, width=100):
    f = ImageFont.truetype(str(FONTS / name), size)
    axes = [a["name"] for a in f.get_variation_axes()]
    values = {b"Weight": weight, b"Width": width}
    f.set_variation_by_axes([values[a] for a in axes])
    return f


def glow(colour, centre, radius, strength):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    x, y = centre
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=colour + (strength,))
    return layer.filter(ImageFilter.GaussianBlur(radius * 0.55))


def fit(img, max_w, max_h):
    img = img.copy()
    img.thumbnail((max_w, max_h), Image.LANCZOS)
    return img


def studio():
    canvas = Image.new("RGBA", (W, H), BG + (255,))
    canvas.alpha_composite(glow((168, 146, 94), (980, 640), 420, 60))
    logo = fit(Image.open(IMG / "brand" / "loudstudio-proaudio-960.png").convert("RGBA"), 470, 360)
    canvas.alpha_composite(logo, (70, (H - logo.height) // 2))

    draw = ImageDraw.Draw(canvas)
    small = font("manrope-latin-var.woff2", 24, 700)
    big = font("archivo-latin-var.woff2", 76, 800, 112)
    x = 610
    draw.text((x, 196), "ESTÚDIO DE PRODUÇÃO ÁUDIO · COIMBRA", font=small, fill=(168, 146, 94))
    draw.text((x, 240), "Em alto", font=big, fill=(243, 244, 246))
    draw.text((x, 322), "e bom som.", font=big, fill=(243, 244, 246))
    draw.text((x, 436), "Gravação · Mistura · Masterização · Produção", font=font("manrope-latin-var.woff2", 22, 500), fill=(180, 185, 193))
    return canvas


LILAC_TEXT = {
    "pt": ("Desinfeção de", "microfones por UV-C", "Representante oficial LAC Labs", "Portugal e Espanha · loudstudio.com"),
    "es": ("Desinfección de", "micrófonos por UV-C", "Distribuidor oficial LAC Labs", "Portugal y España · loudstudio.com"),
}


def lilac(lang="pt"):
    line1, line2, line3, line4 = LILAC_TEXT[lang]
    canvas = Image.new("RGBA", (W, H), (14, 13, 18, 255))
    canvas.alpha_composite(glow((176, 107, 255), (840, 330), 360, 120))
    product = fit(Image.open(IMG / "lilac" / "gaveta-perfil-1200.webp").convert("RGBA"), 640, 470)
    canvas.alpha_composite(product, (W - product.width - 30, (H - product.height) // 2 + 20))
    logo = fit(Image.open(IMG / "brand" / "lilac-logo-white-768.png").convert("RGBA"), 300, 150)
    canvas.alpha_composite(logo, (70, 90))

    draw = ImageDraw.Draw(canvas)
    big = font("archivo-latin-var.woff2", 52, 800, 108)
    draw.text((70, 300), line1, font=big, fill=(243, 244, 246))
    draw.text((70, 358), line2, font=big, fill=(243, 244, 246))
    draw.text((70, 440), line3, font=font("manrope-latin-var.woff2", 24, 700), fill=(201, 155, 255))
    draw.text((70, 474), line4, font=font("manrope-latin-var.woff2", 24, 500), fill=(180, 185, 193))
    return canvas


def main():
    out = IMG / "og"
    out.mkdir(parents=True, exist_ok=True)
    jobs = (
        ("loudstudio-og.jpg", studio),
        ("lilac-og.jpg", lambda: lilac("pt")),
        ("lilac-og-es.jpg", lambda: lilac("es")),
    )
    for name, make in jobs:
        make().convert("RGB").save(out / name, "JPEG", quality=86, optimize=True, progressive=True)
        print("wrote", (out / name).relative_to(PUBLIC))


if __name__ == "__main__":
    main()
