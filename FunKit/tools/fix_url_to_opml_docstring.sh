#!/usr/bin/env bash
set -euo pipefail

ENG="modules/aopml_engine.py"
[ -f "$ENG" ] || ENG="modules/aopmlengine.py"
[ -f "$ENG" ] || { echo "❌ Engine not found"; exit 1; }

cp -p "$ENG" "$ENG.bak.$(date +%Y%m%d-%H%M%S)"

python3 - "$ENG" <<'PY'
import re, sys
p=sys.argv[1]
s=open(p,encoding="utf-8",errors="ignore").read()

# Remove any existing url_to_opml definitions
s = re.sub(
    r"(?s)^def\s+url_to_opml\s*\(.*?\):.*?(?=^def|^class|\Z)",
    "",
    s,
    flags=re.M
)

block = '''
# ---- Standalone URL -> OPML (safe docstring) ----
def url_to_opml(url: str, title_hint: str | None = None) -> str:
    """
    Fetch URL, parse headings/links, and return OPML XML string.
    This avoids using Outline/OPMLDocument so __init__ issues don’t matter.
    """
    import urllib.request
    from xml.etree import ElementTree as ET

    req = urllib.request.Request(url, headers={"User-Agent": "FunKit URL->OPML"})
    with urllib.request.urlopen(req, timeout=25) as f:
        raw = f.read()
    try:
        html = raw.decode("utf-8", "ignore")
    except Exception:
        html = raw.decode("latin-1", "ignore")

    items = []
    title = title_hint or url
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            t = soup.title.string.strip()
            if t: title = t
        for tag in soup.find_all(["h1","h2","h3"]):
            t = tag.get_text(" ", strip=True).strip()
            if t: items.append(t)
        if len(items) < 3:
            for a in soup.find_all("a"):
                t = a.get_text(" ", strip=True).strip()
                if t: items.append(t)
    except Exception:
        import re
        m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I|re.S)
        if m:
            title = re.sub(r"\\s+"," ", m.group(1)).strip() or title
        texts = re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", html, flags=re.I|re.S)
        if not texts:
            texts = re.findall(r"<a[^>]*>(.*?)</a>", html, flags=re.I|re.S)
        items = [ re.sub(r"<[^>]+>","", t).strip() for t in texts if t.strip() ]

    seen=set(); outline=[]
    for t in items:
        if t and t not in seen:
            seen.add(t); outline.append(t)
            if len(outline) >= 200: break

    opml = ET.Element("opml", version="2.0")
    head = ET.SubElement(opml, "head"); ET.SubElement(head, "title").text = title or "Imported"
    body = ET.SubElement(opml, "body")
    root = ET.SubElement(body, "outline", text=title or "Imported")
    for t in outline:
        ET.SubElement(root, "outline", text=t)
    return ET.tostring(opml, encoding="utf-8", xml_declaration=True).decode("utf-8")
'''

s += block
open(p,"w",encoding="utf-8").write(s)
print("✅ url_to_opml replaced with proper docstring version.")
PY

