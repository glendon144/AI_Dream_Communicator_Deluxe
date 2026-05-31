#!/usr/bin/env bash
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "Usage: $0 /path/to/OLD/PiKit/modules/aopml_engine.py /path/to/NEW/FunKit/modules/aopml_engine.py"
  echo "Example:"
  echo "  $0 ../../083125/PiKit/modules/aopml_engine.py modules/aopml_engine.py"
  exit 1
fi

OLD="$1"
NEW="$2"
[ -f "$OLD" ] || { echo "❌ Old engine not found: $OLD"; exit 1; }
[ -f "$NEW" ] || { echo "❌ New engine not found: $NEW"; exit 1; }

ts=$(date +%Y%m%d-%H%M%S)
backup="$NEW.bak.$ts"
cp -p "$NEW" "$backup"

tmp="$NEW.tmp.$ts"
cp -p "$OLD" "$tmp"

# Append a minimal ASCII-safe url_to_opml wrapper if missing.
python3 - "$tmp" <<'PY'
import sys, re
p=sys.argv[1]
s=open(p, encoding='utf-8', errors='ignore').read()

if not re.search(r"\bdef\s+url_to_opml\s*\(", s):
    s += r"""

# ---- Convenience: URL -> OPML (appended safely) ----
def url_to_opml(url: str, title_hint: str | None = None) -> str:
    \"\"\"Fetch URL, detect HTML vs text, and return OPML XML string.\"\"\"
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "FunKit URL->OPML"})
    with urllib.request.urlopen(req, timeout=25) as f:
        raw = f.read()
    try:
        text = raw.decode("utf-8", "ignore")
    except Exception:
        text = raw.decode("latin-1", "ignore")

    title = title_hint or url
    # Try to use module helpers if present
    try:
        htmlish = is_probably_html(text)
    except Exception:
        t = text.lower()
        htmlish = ("<html" in t) or ("</p>" in t) or ("<h1" in t)

    if htmlish and "build_opml_from_html" in globals():
        doc = build_opml_from_html(title, text)
    elif "build_opml_from_text" in globals():
        doc = build_opml_from_text(title, text)
    else:
        # Last-ditch minimal OPML
        from xml.etree import ElementTree as ET
        opml = ET.Element("opml", version="2.0")
        head = ET.SubElement(opml, "head"); ET.SubElement(head, "title").text = title
        body = ET.SubElement(opml, "body"); root = ET.SubElement(body, "outline", text=title)
        for line in (ln.strip() for ln in text.splitlines() if ln.strip()):
            ET.SubElement(root, "outline", text=line[:200])
        print("[url_to_opml] Fallback builder used")
        print("[url_to_opml] Tip: install beautifulsoup4 and requests for better results")
        print("[url_to_opml] pip install beautifulsoup4 requests")
        s = ET.tostring(opml, encoding="utf-8", xml_exclamation=True).decode("utf-8")
        # Note: returning here from nested scope not possible; using variable below
        return ET.tostring(opml, encoding="utf-8", xml_declaration=True).decode("utf-8")
    return doc.to_xml() if hasattr(doc, "to_xml") else str(doc)
"""
    open(p, "w", encoding="utf-8").write(s)
PY

# Try compiling the tmp engine before replacing the real one
set +e
python3 -m py_compile "$tmp"
rc=$?
set -e

if [ $rc -ne 0 ]; then
  echo "❌ New engine content did not compile. Leaving original in place."
  echo "Backup: $backup"
  exit 1
fi

# If compile is OK, move into place
mv "$tmp" "$NEW"
echo "✅ Engine swapped successfully. Backup at: $backup"

