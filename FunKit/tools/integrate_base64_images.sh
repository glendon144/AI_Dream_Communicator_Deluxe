#!/usr/bin/env bash
set -euo pipefail

GUI="modules/gui_tkinter.py"
IMG_MOD="modules/image_render.py"
SRC_IMG_MOD="${1:-}"

err() { printf "\n[ERROR] %s\n" "$*" >&2; exit 1; }
note(){ printf "[ok] %s\n" "$*"; }

[[ -f "$GUI" ]] || err "Run from your FunKit repo root. Missing: $GUI"

# 1) Ensure image_render.py exists under modules/
if [[ -n "$SRC_IMG_MOD" ]]; then
  [[ -f "$SRC_IMG_MOD" ]] || err "Provided image_render.py not found: $SRC_IMG_MOD"
  mkdir -p modules
  cp -f "$SRC_IMG_MOD" "$IMG_MOD"
  note "Copied image helper → $IMG_MOD"
else
  if [[ ! -f "$IMG_MOD" ]]; then
    printf "[WARN] %s not found and no source arg provided.\n" "$IMG_MOD"
    printf "       Put image_render.py at modules/image_render.py or rerun with path arg.\n"
  else
    note "Found $IMG_MOD"
  fi
fi

# 2) Backup gui_tkinter.py
ts="$(date +%Y%m%d-%H%M%S)"
cp -f "$GUI" "${GUI}.bak.${ts}"
note "Backed up $GUI → ${GUI}.bak.${ts}"

# 3) Patch gui_tkinter.py with Python (macOS/BSD-friendly)
python3 - <<'PY'
import io, sys, re, pathlib

gui = pathlib.Path("modules/gui_tkinter.py")
text = gui.read_text(encoding="utf-8")

changed = False

# (A) Ensure "from modules import image_render" is present near other modules imports
if re.search(r'^\s*from\s+modules\s+import\s+image_render\b', text, flags=re.MULTILINE) is None:
    # Find the anchor import line that already exists in your working file
    # e.g. "from modules import hypertext_parser, image_generator, document_store"
    m = re.search(r'^\s*from\s+modules\s+import\s+hypertext_parser,\s*image_generator,\s*document_store\s*$',
                  text, flags=re.MULTILINE)
    if m:
        insert_at = m.end()
        text = text[:insert_at] + "\nfrom modules import image_render" + text[insert_at:]
        changed = True
    else:
        # Fallback: insert after PIL import
        m2 = re.search(r'^\s*from\s+PIL\s+import\s+ImageTk,\s*Image\s*$', text, flags=re.MULTILINE)
        if not m2:
            print("[WARN] Could not find a stable import anchor; inserting image_render at top.")
            text = 'from modules import image_render\n' + text
        else:
            insert_at = m2.end()
            text = text[:insert_at] + "\nfrom modules import image_render" + text[insert_at:]
        changed = True

# (B) Inject inline base64 rendering into _render_document before "# 3) Fallbacks: show as text"
marker = "# 3) Fallbacks: show as text"
already = "Inline base64 images (image_render)"
if already not in text:
    # Locate the correct spot inside _render_document
    # Your file has earlier step: "# 2) Image? (base64 or binary)" then this marker line.
    spot = text.find(marker)
    if spot == -1:
        print("[WARN] Could not find fallback marker; no code injected.")
    else:
        # Compute indentation by looking backward to line start
        line_start = text.rfind("\n", 0, spot) + 1
        indent = re.match(r'[ \t]*', text[line_start:]).group(0)
        block = f"""\n{indent}# 2.5) Inline base64 images (image_render)\n{indent}if isinstance(body, str):\n{indent}    try:\n{indent}        blobs = image_render.extract_image_bytes_all(body)\n{indent}    except Exception:\n{indent}        blobs = []\n{indent}    if blobs:\n{indent}        self._hide_opml()\n{indent}        # Render images centered inside the Text widget; keep the image pane clear to avoid duplication\n{indent}        if image_render.show_images_in_text(self.text, blobs):\n{indent}            if hasattr(self, 'img_label'):\n{indent}                try: self.img_label.configure(image=\"\")\n{indent}                except Exception: pass\n{indent}            return\n"""
        text = text[:spot] + block + text[spot:]
        changed = True

if changed:
    gui.write_text(text, encoding="utf-8")
    print("[ok] Patched modules/gui_tkinter.py")
else:
    print("[ok] No changes were necessary (already patched)")
PY

note "Done. Try:  python3 main.py"

