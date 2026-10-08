"""Check the built site in website/public before publishing.

- every local link, image, srcset entry, script and stylesheet points to a file
- every #anchor exists on the page it points to
- every <img> has an alt attribute and every page exactly one <h1>
- no template placeholders ({{...}}) were left in the HTML

Usage:  python website/tools/check_site.py
"""

import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

PUBLIC = Path(__file__).resolve().parent.parent / "public"
# Paths served by .htaccess redirects or by PHP rather than by a file
VIRTUAL = {"/contacto.php"}


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.refs = []          # (attribute, value)
        self.h1 = 0
        self.images_without_alt = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "h1":
            self.h1 += 1
        if tag == "img" and "alt" not in a:
            self.images_without_alt += 1
        for name in ("href", "src", "action"):
            if a.get(name):
                self.refs.append((name, a[name]))
        if a.get("srcset"):
            for part in a["srcset"].split(","):
                self.refs.append(("srcset", part.strip().split(" ")[0]))


def target_file(path):
    """File that serves a site path, or None."""
    path = unquote(path)
    candidate = PUBLIC / path.lstrip("/")
    if path.endswith("/"):
        candidate = candidate / "index.html"
    return candidate if candidate.is_file() else None


def main():
    pages = {}
    for html_file in PUBLIC.rglob("*.html"):
        parser = Page()
        text = html_file.read_text(encoding="utf-8")
        parser.feed(text)
        pages[html_file] = (parser, text)

    problems = []
    for html_file, (page, text) in sorted(pages.items()):
        rel = "/" + str(html_file.relative_to(PUBLIC)).replace("index.html", "")
        if page.h1 != 1:
            problems.append(f"{rel}: {page.h1} <h1> elements")
        if page.images_without_alt:
            problems.append(f"{rel}: {page.images_without_alt} <img> without alt")
        if re.search(r"\{\{[^}]*\}\}", text):
            problems.append(f"{rel}: template placeholder left in the HTML")

        for attr, ref in page.refs:
            parts = urlsplit(ref)
            if parts.scheme in ("http", "https", "mailto", "tel") or ref.startswith("//"):
                if parts.netloc in ("loudstudio.com", "www.loudstudio.com"):
                    pass  # absolute links to the site itself are fine (canonical, og:url)
                continue
            if not parts.path:  # same-page anchor
                if parts.fragment and parts.fragment not in page.ids:
                    problems.append(f"{rel}: anchor #{parts.fragment} not found")
                continue
            if not parts.path.startswith("/"):
                problems.append(f"{rel}: relative URL {ref} (use a path starting with /)")
                continue
            if parts.path in VIRTUAL:
                if not (PUBLIC / parts.path.lstrip("/")).is_file():
                    problems.append(f"{rel}: {parts.path} is missing")
                continue
            target = target_file(parts.path)
            if target is None:
                problems.append(f"{rel}: {attr} {ref} does not exist")
                continue
            if parts.fragment and target in pages:
                if parts.fragment not in pages[target][0].ids:
                    problems.append(f"{rel}: anchor {ref} not found")

    if problems:
        print("\n".join(problems))
        print(f"\n{len(problems)} problem(s) in {len(pages)} pages")
        return 1
    print(f"{len(pages)} pages checked, no problems")
    return 0


if __name__ == "__main__":
    sys.exit(main())
