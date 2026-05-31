#!/usr/bin/env bash
set -euo pipefail

ENG="modules/aopml_engine.py"
[ -f "$ENG" ] || ENG="modules/aopmlengine.py"
[ -f "$ENG" ] || { echo "❌ Engine not found"; exit 1; }

ts=$(date +%Y%m%d-%H%M%S)
cp -p "$ENG" "$ENG.bak.$ts"

python3 - "$ENG" <<'PY'
import re, sys
p=sys.argv[1]
s=open(p,encoding="utf-8",errors="ignore").read()

def ensure_fallbacks(txt):
    if "def _fallback_html_to_outline(" in txt:
        return txt
    block = r'''

# --- Fallbacks inserted by patch_resolve_html_to_outline ---
def _fallback_html_to_outline(html: str):
    """Very small fallback: extract <h1-3> then links/text if BeautifulSoup missing.
       Only used if html_to_outline is not found."""
    try:
        from bs4 import BeautifulSoup  # optional
    except Exception:
        BeautifulSoup = None

    items, title = [], "Imported"
    if BeautifulSoup:
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            title = (soup.title.string or "").strip() or title
        for tag in soup.find_all(["h1","h2","h3"]):
            t = (tag.get_text(" ", strip=True) or "").strip()
            if t: items.append(t)
        if len(items) < 3:
            for a in soup.find_all("a"):
                t = (a.get_text(" ", strip=True) or "").strip()
                if t: items.append(t)
    else:
        import re as _re
        m = _re.search(r"<title[^>]*>(.*?)</title>", html, flags=_re.I|_re.S)
        if m:
            title = _re.sub(r"\s+"," ", m.group(1)).strip() or title
        heads = _re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", html, flags=_re.I|_re.S)
        items = [ _re.sub(r"<[^>]+>","", h).strip() for h in heads if h.strip() ]
    # de-dup
    seen=set(); out=[]
    for t in items:
        if t and t not in seen:
            seen.add(t); out.append(t)
    return title, out[:200]
'''
    # insert near end
    return txt + block

def rewrite_builder(txt):
    # Find build_opml_from_html and insert a robust resolver at its start.
    pat = re.compile(r"(def\s+build_opml_from_html\s*\(.*?\):\s*\n)", re.S)
    m = pat.search(txt)
    if not m:
        return txt
    start = m.end()
    # Only insert once
    if "hto = (html_to_outline if 'html_to_outline' in globals()" in txt[start:start+300]:
        return txt
    resolver = (
        "    # Resolve html_to_outline robustly\n"
        "    hto = (html_to_outline if 'html_to_outline' in globals() else None)\n"
        "    if hto is None:\n"
        "        try:\n"
        "            import modules.aopml_engine as _eng\n"
        "            hto = getattr(_eng, 'html_to_outline', None)\n"
        "        except Exception:\n"
        "            try:\n"
        "                import modules.aopmlengine as _eng\n"
        "                hto = getattr(_eng, 'html_to_outline', None)\n"
        "            except Exception:\n"
        "                hto = None\n"
        "    if hto is None:\n"
        "        hto = _fallback_html_to_outline\n"
        "\n"
    )
    return txt[:start] + resolver + txt[start:]

# 1) Ensure fallback helper exists
s = ensure_fallbacks(s)
# 2) Ensure build_opml_from_html resolves helper safely
s = rewrite_builder(s)

open(p,"w",encoding="utf-8").write(s)
print("✅ Patched: robust html_to_outline resolution + fallback.")
PY

echo "Backup at: $ENG.bak.$ts"

