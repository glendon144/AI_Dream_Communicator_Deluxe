#!/usr/bin/env bash
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "Usage: $0 /path/to/OLD_PIKIT_2025-08-31 /path/to/CURRENT_FUNKIT"
  echo "Example: $0 /Volumes/WhiteMacBook/PiKit-2025-08-31 ."
  exit 1
fi

OLD_ROOT="$(cd "$1" && pwd)"
NEW_ROOT="$(cd "$2" && pwd)"

echo "🔎 OLD: $OLD_ROOT"
echo "🛠  NEW: $NEW_ROOT"
[ -d "$OLD_ROOT/modules" ] || { echo "Old modules/ not found"; exit 2; }
[ -d "$NEW_ROOT/modules" ] || { echo "New modules/ not found"; exit 2; }

ts() { date +"%Y%m%d-%H%M%S"; }

backup() {
  local f="$1"
  [ -f "$f" ] && cp -p "$f" "$f.bak.$(ts)"
}

need_func() {
  local file="$1" name="$2"
  python3 - "$file" "$name" <<'PY'
import sys, re
p=sys.argv[1]; name=sys.argv[2]
s=open(p,'r',encoding='utf-8',errors='ignore').read()
print("YES" if re.search(rf"\bdef\s+{re.escape(name)}\s*\(", s) else "NO")
PY
}

insert_block_if_missing() {
  local target="$1" marker="$2" block="$3"
  if grep -q "$marker" "$target"; then
    echo "   • Marker already present: $marker"
  else
    echo -e "\n# ==== ${marker} (ported 8/31/25) ====\n${block}\n" >> "$target"
    echo "   ✅ Inserted: $marker"
  fi
}

# --- 1) Identify candidate source files in OLD tree ---
OLD_ENGINE="$OLD_ROOT/modules/aopml_engine.py"
[ -f "$OLD_ENGINE" ] || OLD_ENGINE="$OLD_ROOT/modules/aopmlengine.py"
if [ ! -f "$OLD_ENGINE" ]; then
  echo "❌ Could not find old aopml_engine.py or aopmlengine.py"
  exit 3
fi

OLD_GUI="$OLD_ROOT/modules/gui_tkinter.py"
[ -f "$OLD_GUI" ] || OLD_GUI=""

# --- 2) Prepare NEW targets & backups ---
NEW_ENGINE="$NEW_ROOT/modules/aopml_engine.py"
[ -f "$NEW_ENGINE" ] || NEW_ENGINE="$NEW_ROOT/modules/aopmlengine.py"
[ -f "$NEW_ENGINE" ] || { echo "❌ New aopml_engine[a].py not found"; exit 4; }

NEW_PARSER="$NEW_ROOT/modules/aopmlparser.py"
NEW_GUI="$NEW_ROOT/modules/gui_tkinter.py"

echo "📦 Backups:"
backup "$NEW_ENGINE"
backup "$NEW_PARSER"
backup "$NEW_GUI"

# --- 3) Extract blocks from OLD engine (URL→OPML helpers) ---
# We try to capture practical helpers by name; if not present, skip gracefully.
grab_func() {  # $1 oldfile $2 name
  python3 - "$1" "$2" <<'PY'
import sys, re, io
path, name = sys.argv[1], sys.argv[2]
src = open(path,'r',encoding='utf-8',errors='ignore').read()
pat = re.compile(rf"(^def\s+{re.escape(name)}\s*\(.*?\n)(?:\s*\"\"\".*?\"\"\"\n)?(.*?)(?=^\S|\Z)", re.S|re.M)
m = pat.search(src)
if not m:
    # Try classmethod or nested; fallback greedy def..:
    pat2 = re.compile(rf"^def\s+{re.escape(name)}\s*\(.*?\):.*?(?=^\S|\Z)", re.S|re.M)
    m = pat2.search(src)
if m:
    print(m.group(0).strip())
PY
}

FUNCS=("fetch_url" "html_to_outline" "build_opml_from_html" "url_to_opml" "normalize_links" "clean_html" )

BLOCKS=()
for fn in "${FUNCS[@]}"; do
  blk="$(grab_func "$OLD_ENGINE" "$fn" || true)"
  if [ -n "${blk:-}" ]; then
    BLOCKS+=("$fn<<<BLOCK>>>$blk")
  fi
done

if [ ${#BLOCKS[@]} -eq 0 ]; then
  echo "⚠️  No named helpers found in old engine; continuing with GUI wiring only."
fi

# --- 4) Insert missing helpers into NEW engine ---
tmp="$NEW_ENGINE.tmp.$$"
cp -p "$NEW_ENGINE" "$tmp"

# Ensure imports commonly needed for fetching/cleaning
if ! grep -q "requests" "$tmp"; then
  sed -i.bak.$(ts) '1s;^;# port: add requests+bs4 imports if available\ntry:\n    import requests\nexcept Exception:\n    requests=None\ntry:\n    from bs4 import BeautifulSoup\nexcept Exception:\n    BeautifulSoup=None\n\n;' "$tmp" || true
fi

for entry in "${BLOCKS[@]}"; do
  name="${entry%%<<<BLOCK>>>*}"
  body="${entry#*<<<BLOCK>>>}"
  if [ "$(need_func "$tmp" "$name")" = "NO" ]; then
    insert_block_if_missing "$tmp" "PORT_${name}" "$body"
  else
    echo "   • $name already exists in new engine"
  fi
done

mv "$tmp" "$NEW_ENGINE"

# --- 5) Add top-level convenience: url_to_opml_if_missing ---
if [ "$(need_func "$NEW_ENGINE" "url_to_opml")" = "NO" ]; then
  insert_block_if_missing "$NEW_ENGINE" "PORT_url_to_opml" $'def url_to_opml(url: str, title_hint: str = None) -> str:\n    \"\"\"Fetch URL → HTML → Outline → OPML (string).\"\"\"\n    if \'fetch_url\' in globals() and \'build_opml_from_html\' in globals():\n        html = fetch_url(url)\n        return build_opml_from_html(html, title_hint=title_hint or url)\n    raise RuntimeError(\"url_to_opml pipeline not available\")'
fi

# --- 6) Ensure parser module exists (shim) ---
if [ ! -f "$NEW_PARSER" ]; then
  cat > "$NEW_PARSER" <<'PY'
# aopmlparser.py (shim) — provides minimal OPML parse/build helpers
from xml.etree import ElementTree as ET

def outline_to_opml(root_title, items):
    opml = ET.Element("opml", version="2.0")
    head = ET.SubElement(opml, "head")
    ET.SubElement(head, "title").text = root_title or "Imported"
    body = ET.SubElement(opml, "body")
    root = ET.SubElement(body, "outline", text=root_title or "Imported")
    for it in items:
        ET.SubElement(root, "outline", text=it)
    return ET.tostring(opml, encoding="utf-8", xml_declaration=True).decode("utf-8")
PY
  echo "   ✅ Created shim: aopmlparser.py"
fi

# --- 7) GUI hook: add Tools→OPML→URL: Import as OPML and callback ---
if [ -f "$NEW_GUI" ]; then
  # Add menu if missing
  if ! grep -q "_open_url_to_opml" "$NEW_GUI"; then
    backup "$NEW_GUI"
    python3 - "$NEW_GUI" <<'PY'
import sys,re,io
p=sys.argv[1]
s=open(p,'r',encoding='utf-8',errors='ignore').read()
# 1) Add handler method to class DemoKitGUI (or main GUI class)
s=re.sub(
  r"(class\s+\w+\(.*?Tk.*?\):\s*?\n)",
  r"\1    def _open_url_to_opml(self):\n"
  r"        import tkinter as tk\n"
  r"        from tkinter import simpledialog, messagebox\n"
  r"        try:\n"
  r"            from modules import aopml_engine as eng\n"
  r"        except Exception:\n"
  r"            import modules.aopmlengine as eng\n"
  r"        url = simpledialog.askstring('URL → OPML','Enter a URL to import as OPML:')\n"
  r"        if not url: return\n"
  r"        try:\n"
  r"            opml = eng.url_to_opml(url)\n"
  r"        except Exception as e:\n"
  r"            messagebox.showerror('Import failed', str(e))\n"
  r"            return\n"
  r"        # Create a new document with OPML content\n"
  r"        try:\n"
  r"            doc_id = self.doc_store.create_document(title=f'OPML from {url}', content=opml, content_type='opml')\n"
  r"            self.refresh_list_and_open(doc_id)\n"
  r"        except Exception as e:\n"
  r"            messagebox.showerror('Save failed', str(e))\n"
  r"            return\n"
  r"\n",
  count=1, flags=re.S
)
# 2) Add menu entry under Tools → OPML
if "('OPEN OPML'" in s and "_open_url_to_opml" not in s:
    s=s.replace("('OPEN OPML'", "('OPEN OPML'", 1)  # anchor
if "OPML" in s and "_open_url_to_opml" not in s:
    s=re.sub(
      r"(\(\s*\"OPML\".*?menu\.add_command\(label=.*?)(\)\n)",
      r"\1\n        menu.add_command(label='URL → Import as OPML', command=self._open_url_to_opml)\2",
      s, count=1, flags=re.S
    )
open(p,'w',encoding='utf-8').write(s)
print("   ✅ GUI: added _open_url_to_opml handler + menu item")
PY
  else
    echo "   • GUI handler already present"
  fi
else
  echo "⚠️  GUI file not found; skipping menu wiring"
fi

# --- 8) Smoke test: importability & symbol presence ---
echo "🧪 Smoke test…"
python3 - <<'PY'
ok=True
try:
    from modules import aopml_engine as eng
except Exception:
    import modules.aopmlengine as eng
need = ["url_to_opml","html_to_outline","build_opml_from_html"]
present = {n: hasattr(eng,n) for n in need}
print("Symbols:", present)
if not present["url_to_opml"]:
    print("WARNING: url_to_opml not present; may rely on existing GUI path.")
PY

echo "🎉 Done. Restart the app to clear .pyc and try: Tools → OPML → URL → Import as OPML"

