"""Build the static site: wrap each page in website/src/pages with the shared layout.

Every page starts with a JSON block in an HTML comment:

    <!--meta
    {"title": "...", "description": "...", "path": "/estudio/", "nav": "estudio"}
    -->

and the rest of the file is the page's <main> content. The layout and the
header/footer partials (header.<brand>.<lang>.html, footer.<brand>.<lang>.html,
brand "studio" or "proaudio") live in website/src. Output goes to website/public
with the same relative path (pages/estudio/index.html -> public/estudio/index.html).

Usage:  python website/tools/build.py          write the pages
        python website/tools/build.py --check  fail if public/ is out of date
"""

import argparse
import hashlib
import html
import json
import re
import sys
from pathlib import Path

WEBSITE = Path(__file__).resolve().parent.parent
SRC = WEBSITE / "src"
PUBLIC = WEBSITE / "public"
SITE_URL = "https://loudstudio.com"
DEFAULTS = {
    "lang": "pt-PT",
    "nav": "",
    "og_image": "/assets/img/og/loudstudio-og.jpg",
    "og_type": "website",
    "alternates": {},
    "robots": "index,follow",
    "body_class": "",
    "brand": "studio",       # "studio" or "proaudio" (the commercial Li.LAC side)
}
OG_LOCALE = {"pt-PT": "pt_PT", "es": "es_ES"}


def asset_version():
    """Short hash of the CSS and JS, appended to their URLs to bust caches."""
    digest = hashlib.sha256()
    for rel in ("assets/css/style.css", "assets/js/main.js"):
        digest.update((PUBLIC / rel).read_bytes())
    return digest.hexdigest()[:10]


def parse_page(path):
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\s*<!--meta\s*(\{.*?\})\s*-->\s*", text, re.S)
    if not match:
        raise SystemExit(f"{path}: missing <!--meta {{...}} --> block")
    meta = dict(DEFAULTS)
    meta.update(json.loads(match.group(1)))
    return meta, text[match.end():]


def render(meta, content, version):
    # Studio and Pro Audio are kept apart: each has its own header and footer
    short = meta["lang"].split("-")[0]
    header = (SRC / f"header.{meta['brand']}.{short}.html").read_text(encoding="utf-8")
    footer = (SRC / f"footer.{meta['brand']}.{short}.html").read_text(encoding="utf-8")

    # aria-current on the active navigation item
    def current(m):
        return ' aria-current="page"' if m.group(1) == meta["nav"] else ""
    header = re.sub(r"\{\{current:(\w+)\}\}", current, header)

    alternates = "".join(
        f'\n<link rel="alternate" hreflang="{lang}" href="{SITE_URL}{href}">'
        for lang, href in meta["alternates"].items()
    )
    head_extra = ""
    if meta.get("jsonld"):
        head_extra = (
            '\n<script type="application/ld+json">'
            + json.dumps(meta["jsonld"], ensure_ascii=False, separators=(",", ":"))
            + "</script>"
        )

    page = (SRC / "layout.html").read_text(encoding="utf-8")
    values = {
        "lang": meta["lang"],
        "title": html.escape(meta["title"]),
        "description": html.escape(meta["description"]),
        "canonical": SITE_URL + meta["path"],
        "og_image": SITE_URL + meta["og_image"],
        "og_type": meta["og_type"],
        "og_locale": OG_LOCALE.get(meta["lang"], "pt_PT"),
        "robots": meta["robots"],
        "alternates": alternates,
        "head_extra": head_extra,
        "body_class": meta["body_class"],
        "header": header.strip(),
        "footer": footer.strip(),
        "content": content.strip(),
        "v": version,
    }
    # content goes last so text inside a page can never be read as a placeholder
    for key, value in values.items():
        if key != "content":
            page = page.replace("{{" + key + "}}", value)
    page = page.replace("{{content}}", values["content"])
    leftover = re.findall(r"\{\{[a-z_:]+\}\}", page.replace(values["content"], ""))
    if leftover:
        raise SystemExit(f"unfilled placeholders: {leftover}")
    return page.replace("{{v}}", version)


def sitemap(entries):
    """sitemap.xml for every indexable page, with hreflang alternates."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">',
    ]
    for meta in sorted(entries, key=lambda m: (m["path"].count("/"), m["path"])):
        lines.append(f"  <url><loc>{SITE_URL}{meta['path']}</loc>")
        for lang, href in meta["alternates"].items():
            lines.append(f'    <xhtml:link rel="alternate" hreflang="{lang}" href="{SITE_URL}{href}"/>')
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only check public/ is up to date")
    args = parser.parse_args()

    version = asset_version()
    stale = []
    outputs = {}
    indexable = []
    pages = sorted((SRC / "pages").rglob("*.html"))
    for src in pages:
        rel = src.relative_to(SRC / "pages")
        meta, content = parse_page(src)
        outputs[PUBLIC / rel] = render(meta, content, version)
        if "noindex" not in meta["robots"]:
            indexable.append(meta)
    outputs[PUBLIC / "sitemap.xml"] = sitemap(indexable)

    for out, text in outputs.items():
        if args.check:
            if not out.exists() or out.read_text(encoding="utf-8") != text:
                stale.append(str(out.relative_to(PUBLIC)))
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print("built", out.relative_to(WEBSITE))

    if args.check:
        if stale:
            print("Out of date (run python website/tools/build.py):", *stale, sep="\n  ")
            return 1
        print(f"{len(outputs)} files up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
