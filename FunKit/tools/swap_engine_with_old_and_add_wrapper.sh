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
cp -p "$NEW" "$NEW.bak.$ts"
cp -p "$OLD" "$NEW"

# Clean up duplicate __future__ lines (must be at the very top)
python3 - "$NEW" <<'PY'
import sys, re, io
p=sys.argv[1]
s=open(p,encoding='utf-8',errors='ignore').read()

# Keep only the first future-import occurrence
lines=s.splitlines(True)
seen=False
for i,l in enumerate(lines):
    if l.strip().startswith('from __future__ import'):
        if not seen:
            first=i; seen=True
        else:
            lines[i]=''  # drop duplicates
s=''.join(lines)

# Ensure the future import (if present) is above any non-docstring code
if 'from __future__ import' in s:
    doc = re.match(r'^\s*("""[\s\S]*?""")', s)
    fut = re.search(r'^\s*from __future__ import[^\n]*\n', s, flags=re.M)
    if fut:
        fut_line = fut.group(0)
        s = s.replace(fut_line,'',1)
        if doc:
            i = doc.end()
            s = s[:i] + "\n" + fut_line + s[i:]
        else:
            s = fut_line + s

open(p,'w',encoding='utf-8').write(s)
PY

# Make sure we don’t have Unicode arrows in headers
sed -i "s/URL→OPML/URL->OPML/g" "$NEW"

# Append url_to_opml wrapper if missing
python3 - "$NEW" <<'PY'
import sys, re
p=sys.argv[1]
s=open(p,encoding='utf-8',errors='ignore').read()

if not re.search(r"\bdef\s+url_to_opml\s*\(", s):
    block = r'''

# ---- Convenience: URL -> OPML (appended) ----
def url_to_opml(url: str, title_hint: str|None=None) -> str:
    """
    Fetch URL, detect HTML vs text using is_probably_html, then convert to OPML
    by calling build_opml_from_html / build_opml_from_text from this module.
    Returns an OPML XML string.
    """
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "FunKit URL->OPML"})
    with urllib.request.urlopen(req, timeout=25) as f:
        raw = f.read()
    try:
        text = raw.decode("utf-8", "ignore")
    except Exception:
        text = raw.decode("latin-1", "ignore")

    title = title_hint or url
    # Prefer module’s own helpers if present
    if "is_probably_html" in globals():
        htmlish = is_probably_html(text)
    else:
        htmlish = ("<html" in text.lower()) or ("</p>" in text.lower())
    if htmlish and "build_opml_from_html" in globals():
        doc = build_opml_from_html(title, text)
    elif "build_opml_from_text" in globals():
        doc = build_opml_from_text(title, text)
    else:
        # last-ditch minimal OPML
        from xml.etree import ElementTree as ET
        opml = ET.Element("opml", version="2.0")
        head = ET.SubElement(opml, "head"); ET.SubElement(head, "title").text = title
        body = ET.SubElement(opml, "body"); root = ET.SubElement(body, "outline", text=title)
        for line in (t.strip() for t in text.splitlines() if t.strip()):
            ET.SubElement(root, "outline", text=line[:200])
        return ET.tostring(opml, encoding="utf-8", xml_declaration=True).decode("utf-8")

    # The PiKit engine returns an OPMLDocument; convert to XML
    return doc.to_xml() if hasattr(doc, "to_xml") else str(doc)
'''
    s += block

open(p,'w',encoding='utf-8').write(s)
PY

echo "✅ Replaced engine with old PiKit version and appended url_to_opml wrapper."

