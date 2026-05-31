#!/usr/bin/env bash
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "Usage: $0 /path/to/OLD_PIKIT/modules/aopml_engine.py /path/to/FUNKIT/modules/aopml_engine.py"
  echo "Example:"
  echo "  $0 /Volumes/WhiteMacBook/PiKit-2025-08-31/modules/aopml_engine.py modules/aopml_engine.py"
  exit 1
fi

OLD_ENGINE="$1"
NEW_ENGINE="$2"

[ -f "$OLD_ENGINE" ] || { echo "❌ Old engine not found: $OLD_ENGINE"; exit 2; }
[ -f "$NEW_ENGINE" ] || { echo "❌ New engine not found: $NEW_ENGINE"; exit 2; }

ts() { date +"%Y%m%d-%H%M%S"; }
cp -p "$NEW_ENGINE" "$NEW_ENGINE.bak.$(ts)"

python3 - "$OLD_ENGINE" "$NEW_ENGINE" <<'PY'
import sys, re, io, textwrap, hashlib

old_path, new_path = sys.argv[1], sys.argv[2]
old = open(old_path,'r',encoding='utf-8',errors='ignore').read()
new = open(new_path,'r',encoding='utf-8',errors='ignore').read()

# Helpers
def has_def(src, name): return re.search(rf"\bdef\s+{re.escape(name)}\s*\(", src) is not None
def has_class(src, name): return re.search(rf"\bclass\s+{re.escape(name)}\b", src) is not None
def extract_def(src, name):
    pat = re.compile(rf"(^def\s+{re.escape(name)}\s*\(.*?\)\s*:\s*[\s\S]*?)(?=^\S|\Z)", re.M)
    m = pat.search(src)
    return m.group(1).rstrip() if m else None

def ensure_header_imports(src):
    if "## URL→OPML imports (porter)" in src: return src
    block = '''
# ## URL→OPML imports (porter)
try:
    import urllib.request as _urlreq
except Exception:
    _urlreq = None
'''
    # put after docstring if present
    m = re.search(r'^(?P<doc>""".*?""")', src, flags=re.S)
    if m:
        i = m.end()
        return src[:i] + "\n" + block + "\n" + src[i:]
    return block + "\n" + src

# What we’ll ensure exists in NEW, sourcing from OLD if missing
NEEDED_FUNCS = [
    "is_probably_html",
    "build_opml_from_html",
    "build_opml_from_text",
    "html_to_outline",
    "text_to_outline",
    "split_paragraphs",
    "bulletize_lines",
]

inserted = []

# 1) Ensure support functions exist
for fn in NEEDED_FUNCS:
    if not has_def(new, fn):
        body = extract_def(old, fn)
        if body:
            new += "\n\n# ==== ported from 2025-08-31 aopml_engine.py ====\n" + body + "\n"
            inserted.append(fn)

# 2) Ensure url_to_opml exists (wrapper using existing builders)
if not has_def(new, "url_to_opml"):
    url_block = '''
# ---- Convenience: URL → OPML (ported) ----
def url_to_opml(url: str, title_hint: str|None=None) -> str:
    """
    Fetch URL, detect HTML vs text using is_probably_html, then convert to OPML.
    Reuses build_opml_from_html/build_opml_from_text already present in this module.
    Returns OPML XML string.
    """
    assert _urlreq is not None, "urllib is required for URL→OPML"
    req = _urlreq.Request(url, headers={"User-Agent":"FunKit URL→OPML"})
    with _urlreq.urlopen(req, timeout=25) as f:
        raw = f.read()
    try:
        text = raw.decode("utf-8", "ignore")
    except Exception:
        text = raw.decode("latin-1", "ignore")

    title = title_hint or url
    if is_probably_html(text):
        doc = build_opml_from_html(title, text)
    else:
        doc = build_opml_from_text(title, text)
    return doc.to_xml()
'''
    new = ensure_header_imports(new) + "\n" + url_block
    inserted.append("url_to_opml")

# 3) Guard: if classes Outline/OPMLDocument are missing in NEW but present in OLD, bring them (unlikely but safe)
for cls in ("Outline","OPMLDocument"):
    if not has_class(new, cls):
        pat = re.compile(rf"(^@dataclass[\s\S]*?^class\s+{cls}\b[\s\S]*?)(?=^@dataclass|^class\s|\Z)", re.M)
        m = pat.search(old)
        if m:
            new += "\n\n# ==== ported dataclass from 2025-08-31 aopml_engine.py ====\n" + m.group(1).rstrip() + "\n"
            inserted.append(cls)

open(new_path,'w',encoding='utf-8').write(new)

print("Inserted/ensured:", ", ".join(inserted) if inserted else "(nothing; all present)")

PY

echo "✅ Port complete. Backup at: $NEW_ENGINE.bak.$(ts)"

