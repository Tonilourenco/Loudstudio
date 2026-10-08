"""Download the images and PDF from the old WordPress site and make web-sized copies.

Reads website/tools/assets.json, downloads every original from the old site's
uploads folder (cached in website/tools/.cache), and writes resized WebP/PNG
files and favicons into website/public. Also writes assets-report.json with
the size of every file and the main colours of each original, so the brand
colour and the width/height attributes in the HTML can be checked.

Usage:  python website/tools/fetch_assets.py [--base-url URL] [--force]
Needs:  pip install pillow
"""

import argparse
import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps

TOOLS = Path(__file__).resolve().parent
PUBLIC = TOOLS.parent / "public"
CACHE = TOOLS / ".cache"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) loudstudio-site-assets/1.0"


def download(url, dest, force=False):
    if dest.exists() and dest.stat().st_size > 0 and not force:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_error = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
                shutil.copyfileobj(resp, f)
            return dest
        except Exception as exc:  # network errors: retry with backoff
            last_error = exc
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"Could not download {url}: {last_error}")


def main_colours(img, count=6):
    """Most common colours of the visible, non-grey pixels, as hex strings."""
    rgba = img.convert("RGBA")
    rgba.thumbnail((300, 300))
    flat = getattr(rgba, "get_flattened_data", rgba.getdata)()
    pixels = [
        p[:3] for p in flat
        if p[3] > 200 and max(p[:3]) - min(p[:3]) > 40
    ]
    if not pixels:
        return []
    swatch = Image.new("RGB", (len(pixels), 1))
    swatch.putdata(pixels)
    quant = swatch.quantize(colors=count, method=Image.Quantize.MEDIANCUT)
    palette = quant.getpalette()
    ranked = sorted(quant.getcolors(), reverse=True)
    total = sum(n for n, _ in ranked)
    return [
        {
            "hex": "#{:02x}{:02x}{:02x}".format(*palette[i * 3:i * 3 + 3]),
            "share": round(n / total, 3),
        }
        for n, i in ranked
    ]


def save(img, path, fmt):
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "webp":
        img.save(path, "WEBP", quality=80, method=6)
    elif fmt == "png":
        img.save(path, "PNG", optimize=True)
    elif fmt == "jpg":
        img.convert("RGB").save(path, "JPEG", quality=82, optimize=True, progressive=True)
    else:
        raise ValueError(fmt)


def resized(img, width):
    if width >= img.width:
        return img
    height = round(img.height * width / img.width)
    return img.resize((width, height), Image.LANCZOS)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", help="override base_url from assets.json")
    parser.add_argument("--force", action="store_true", help="download again even if cached")
    args = parser.parse_args()

    config = json.loads((TOOLS / "assets.json").read_text())
    base = args.base_url or config["base_url"]
    report = {"sources": {}, "outputs": {}}

    def record(path):
        with Image.open(path) as im:
            w, h = im.size
        report["outputs"][str(path.relative_to(PUBLIC))] = {
            "width": w, "height": h, "bytes": path.stat().st_size,
        }

    for item in config["images"]:
        src = download(base + item["src"], CACHE / item["src"], args.force)
        with Image.open(src) as opened:
            img = ImageOps.exif_transpose(opened)
            img.load()
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "transparency" in img.info or img.mode in ("LA", "P") else "RGB")
        report["sources"][item["src"]] = {
            "width": img.width, "height": img.height, "mode": img.mode,
            "colours": main_colours(img),
        }
        # Files are named by the requested width so the HTML srcsets stay
        # valid even when an original is smaller than that width.
        for width in item["widths"]:
            variant = resized(img, width)
            for fmt in item["formats"]:
                out = PUBLIC / f"{item['out']}-{width}.{fmt}"
                save(variant, out, fmt)
                record(out)
        print(f"ok  {item['src']}  {img.width}x{img.height} {img.mode}")

    icons = config["icons"]
    src = download(base + icons["src"], CACHE / icons["src"], args.force)
    with Image.open(src) as opened:
        icon = opened.convert("RGBA")
    report["sources"][icons["src"]] = {
        "width": icon.width, "height": icon.height, "mode": icon.mode,
        "colours": main_colours(icon),
    }
    side = max(icon.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(icon, ((side - icon.width) // 2, (side - icon.height) // 2))
    for name, size in icons["out"].items():
        out = PUBLIC / name
        save(square.resize((size, size), Image.LANCZOS), out, "png")
        record(out)
    print(f"ok  {icons['src']}  icons")

    for item in config["files"]:
        src = download(base + item["src"], CACHE / item["src"], args.force)
        out = PUBLIC / item["out"]
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, out)
        report["outputs"][item["out"]] = {"bytes": out.stat().st_size}
        print(f"ok  {item['src']}")

    (TOOLS / "assets-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print("wrote", (TOOLS / "assets-report.json").relative_to(TOOLS.parent.parent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
