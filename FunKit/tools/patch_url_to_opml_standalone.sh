#!/usr/bin/env bash
set -euo pipefail

ENG="modules/aopml_engine.py"
[ -f "$ENG" ] || { ENG="modules/aopmlengine.py"; }
[ -f "$ENG" ] || { echo "❌ Engine not found"; exit 1; }

cp -p "$ENG" "$ENG.bak.$(date +%Y%m%d-%H%M%S)"

python3 - "$ENG" <<'PY'
import re, sys
p=sys.argv[1]
s=open(p,encoding="utf-8",errors="ignore").read()

# Remove any existing url_to_opml definition
s = re.sub(
    r"(?s)^def\s+url_to_opml\s*\(.*?\):\s*.*?(?=^\S|\Z)",
    "",
    s,
    flags=re.M
)

# Append a standalone, dependency-light implementation.
s += r"""

# ---- Standalone URL -> OPML (no Outline/OPMLDocument deps) ----
def url_to_opml(url: str, title_hint: str | None = None) -> str:
    \"\"\"Fetch URL, parse headings/links, and return OPML XML string.
    This implementation avoids engine classes to bypass '__init__ must return None' issues.
    \"\"\"
    import urllib.request
    from xml.etree import ElementTree as ET

    # 1) fetch (ASCII-safe User-Agent)
    req = urllib.request.Request(url, headers={"User-Agent": "FunKit URL->OPML"})
    with urllib.request.urlopen(req, timeout=25) as f:
        raw = f.read()
    try:
        html = raw.decode("utf-8", "ignore")
    except Exception:
        html = raw.decode("latin-1", "ignore")

    # 2) parse to outline (prefer BeautifulSoup; fallback to regex)
    items = []
    title = title_hint or url
    try:
        from bs4 import BeautifulSoup  # optional
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            v = (soup.title.string or "").strip()
            if v: title = v
        # headings first
        for tag in soup.find_all(["h1","h2","h3"]):
            t = (tag.get_text(" ", strip=True) or "").strip()
            if t: items.append(t)
        # links as fallback
        if len(items) < 3:
            for a in soup.find_all("a"):
                t = (a.get_text(" ", strip=True) or "").strip()
                if t: items.append(t)
        # paragraphs as last fallback
        if len(items) < 3:
            for pnode in soup.find_all("p"):
                t = (pnode.get_text(" ", strip=True) or "").strip()
                if t: items.append(t)
    except Exception:
        import re as _re
        # title
        m = _re.search(r"<title[^>]*>(.*?)</title>", html, flags=_re.I|_re.S)
        if m:
            title = _re.sub(r"\s+", " ", m.group(1)).strip() or title
        # headings then links
        texts = _re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", html, flags=_re.I|_re.S)
        if not texts:
            texts = _re.findall(r"<a[^>]*>(.*?)</a>", html, flags=_re.I|_re.S)
        items = [ _re.sub(r"<[^>]+>","", t).strip() for t in texts if t and t.strip() ]

    # 3) normalize & dedupe
    seen=set(); outline=[]
    for t in items:
        if not t: continue
        if t in seen: continue
        seen.add(t)
        outline.append(t)
        if len(outline) >= 200: break

    # 4) build minimal OPML 2.0
    opml = ET.Element("opml", version="2.0")
    head = ET.SubElement(opml, "head")
    ET.SubElement(head, "title").text = title or "Imported"
    body = ET.SubElement(opml, "body")
    root = ET.SubElement(body, "outline", text=title or "Imported")
    for t in outline:
        ET.SubElement(root, "outline", text=t)
    return ET.tostring(opml, encoding="utf-8", xml_declaration=True).decode("utf-8")
"""

open(p,"w",encoding="utf-8").write(s)
print("✅ Replaced url_to_opml with a standalone implementation.")
PY

