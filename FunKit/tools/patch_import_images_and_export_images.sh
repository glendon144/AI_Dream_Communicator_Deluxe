#!/usr/bin/env bash
set -euo pipefail

FILE="modules/gui_tkinter.py"
BACKUP="${FILE}.bak.$(date +%Y%m%d-%H%M%S)"

[[ -f "$FILE" ]] || { echo "❌ Not found: $FILE"; exit 1; }
cp -p "$FILE" "$BACKUP"

python3 - "$FILE" <<'PY'
import io, re, sys, textwrap

path = sys.argv[1]
src = io.open(path, "r", encoding="utf-8", errors="surrogatepass").read()
orig = src

def ensure_import(modname):
    global src
    if re.search(rf'^\s*import\s+{re.escape(modname)}\b', src, re.M) is None:
        # insert after first import-like line
        m = re.search(r'^(?:from\s+\S+\s+import\s+.*|import\s+.*)$', src, re.M)
        pos = m.end() if m else 0
        src = src[:pos] + f"\nimport {modname}\n" + src[pos:]

# needed for export + filetype helpers
ensure_import("base64")
ensure_import("mimetypes")

# ---- find DemoKitGUI class block -------------------------------------------
cls_re = re.compile(r'^\s*class\s+DemoKitGUI\b.*?:\s*$', re.M)
mcls = cls_re.search(src)
if not mcls:
    print("❌ Could not find class DemoKitGUI", file=sys.stderr); sys.exit(2)

start_cls = mcls.start()
next_cls = cls_re.search(src, mcls.end())
end_cls = next_cls.start() if next_cls else len(src)
cls_block = src[start_cls:end_cls]

class_indent = re.match(r'[ \t]*', src[mcls.start():mcls.end()]).group(0)
method_indent = class_indent + ("    " if "\t" not in class_indent else "\t")

def missing(funcname):
    return re.search(rf'^{method_indent}def\s+{funcname}\s*\(', cls_block, re.M) is None

inserts = []

# filetypes helper (images first)
if missing("_filetypes_images_first"):
    inserts.append(textwrap.dedent(f"""
    {method_indent}def _filetypes_images_first(self):
    {method_indent}    return [
    {method_indent}        ("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
    {method_indent}        ("Text files", "*.txt *.md *.opml *.xml *.html *.htm *.json"),
    {method_indent}        ("All files", "*.*"),
    {method_indent}    ]
    """).lstrip("\n"))

# minimal data-url builder for local images
if missing("_data_url_from_path"):
    inserts.append(textwrap.dedent(f"""
    {method_indent}def _data_url_from_path(self, path):
    {method_indent}    from pathlib import Path
    {method_indent}    p = Path(path)
    {method_indent}    b = p.read_bytes()
    {method_indent}    mt, _ = mimetypes.guess_type(p.name)
    {method_indent}    if not mt or not mt.startswith("image/"):
    {method_indent}        # sniff a few common formats
    {method_indent}        if b.startswith(b"\\x89PNG\\r\\n\\x1a\\n"): mt = "image/png"
    {method_indent}        elif b.startswith(b"\\xff\\xd8"): mt = "image/jpeg"
    {method_indent}        elif b.startswith(b"GIF87a") or b.startswith(b"GIF89a"): mt = "image/gif"
    {method_indent}        elif b.startswith(b"BM"): mt = "image/bmp"
    {method_indent}        elif len(b) >= 12 and b[0:4] == b"RIFF" and b[8:12] == b"WEBP": mt = "image/webp"
    {method_indent}        else: mt = "application/octet-stream"
    {method_indent}    return f"data:{{mt}};base64,{{base64.b64encode(b).decode('ascii')}}"
    """).lstrip("\n"))

# images-aware Export: if body is data:image…;base64,… write true bytes
if missing("_export_current_images_aware"):
    inserts.append(textwrap.dedent(f"""
    {method_indent}def _export_current_images_aware(self, event=None):
    {method_indent}    \"\"\"Export current doc; if body is data:image;base64, write real image bytes.\"\"\"
    {method_indent}    body = None
    {method_indent}    try:
    {method_indent}        if hasattr(self, "get_current_body") and callable(getattr(self, "get_current_body")):
    {method_indent}            body = self.get_current_body()
    {method_indent}        elif hasattr(self, "text"):
    {method_indent}            body = self.text.get("1.0", "end-1c")
    {method_indent}    except Exception:
    {method_indent}        body = None
    {method_indent}    if not isinstance(body, str) or not body.startswith("data:image/"):
    {method_indent}        # fallback to your existing export (if any)
    {method_indent}        if hasattr(self, "_on_export_clicked"):
    {method_indent}            try: return self._on_export_clicked()
    {method_indent}            except Exception: pass
    {method_indent}        return
    {method_indent}    import re
    {method_indent}    m = re.match(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.*)$", body, re.S)
    {method_indent}    if not m:
    {method_indent}        if hasattr(self, "_on_export_clicked"):
    {method_indent}            try: return self._on_export_clicked()
    {method_indent}            except Exception: pass
    {method_indent}        return
    {method_indent}    mime, b64 = m.groups()
    {method_indent}    ext = {{
    {method_indent}        "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
    {method_indent}        "image/bmp": ".bmp", "image/webp": ".webp"
    {method_indent}    }}.get(mime, ".bin")
    {method_indent}    from tkinter import filedialog, messagebox
    {method_indent}    fn = filedialog.asksaveasfilename(defaultextension=ext, filetypes=[("All files", "*.*")])
    {method_indent}    if not fn: return
    {method_indent}    try:
    {method_indent}        with open(fn, "wb") as f:
    {method_indent}            f.write(base64.b64decode(b64))
    {method_indent}        try: messagebox.showinfo("Export", f"Saved: {{fn}}")
    {method_indent}        except Exception: pass
    {method_indent}    except Exception:
    {method_indent}        # stay silent on export errors to keep UI responsive
    {method_indent}        pass
    """).lstrip("\n"))

# explicit Import Images flow (dialog defaults to images)
if missing("_on_import_images_clicked"):
    inserts.append(textwrap.dedent(f"""
    {method_indent}def _on_import_images_clicked(self, event=None):
    {method_indent}    from tkinter import filedialog, messagebox
    {method_indent}    paths = filedialog.askopenfilenames(
    {method_indent}        title="Import Images…",
    {method_indent}        filetypes=self._filetypes_images_first(),
    {method_indent}    )
    {method_indent}    if not paths: return
    {method_indent}    created = []
    {method_indent}    for path in paths:
    {method_indent}        try:
    {method_indent}            body = self._data_url_from_path(path)
    {method_indent}            from pathlib import Path as _P
    {method_indent}            title = _P(path).name
    {method_indent}            doc_id = None
    {method_indent}            # Try GUI helpers first
    {method_indent}            for name in ("create_document","new_document","add_document_here"):
    {method_indent}                fn = getattr(self, name, None)
    {method_indent}                if callable(fn):
    {method_indent}                    try:
    {method_indent}                        doc_id = fn(title, body); break
    {method_indent}                    except TypeError:
    {method_indent}                        try: doc_id = fn({{'title': title, 'body': body}}); break
    {method_indent}                        except Exception: pass
    {method_indent}            # Then document_store fallbacks
    {method_indent}            if doc_id is None:
    {method_indent}                try:
    {method_indent}                    from modules import document_store as _ds
    {method_indent}                    for name in ("create_document","add_document","insert_document","new_document","create","add"):
    {method_indent}                        fn = getattr(_ds, name, None)
    {method_indent}                        if callable(fn):
    {method_indent}                            try: doc_id = fn(title, body); break
    {method_indent}                            except TypeError:
    {method_indent}                                try: doc_id = fn({{'title': title, 'body': body}}); break
    {method_indent}                                except Exception: pass
    {method_indent}                except Exception: pass
    {method_indent}            if doc_id is not None: created.append(doc_id)
    {method_indent}        except Exception: continue
    {method_indent}    if created:
    {method_indent}        last_id = created[-1]
    {method_indent}        try: messagebox.showinfo("Import", f"Document {{last_id}} created")
    {method_indent}        except Exception: pass
    {method_indent}        try:
    {method_indent}            if hasattr(self, "reload_index"): self.reload_index()
    {method_indent}            tree = getattr(self, "tree", None)
    {method_indent}            if tree:
    {method_indent}                for it in tree.get_children(''):
    {method_indent}                    vals = tree.item(it, 'values')
    {method_indent}                    if vals and str(vals[0]) == str(last_id):
    {method_indent}                        tree.selection_set(it); tree.see(it)
    {method_indent}                        if hasattr(self, "open_doc_by_id"): self.open_doc_by_id(last_id)
    {method_indent}                        break
    {method_indent}        except Exception: pass
    """).lstrip("\n"))

# append methods (if any) just before end of class
if inserts:
    if not cls_block.endswith("\n"): cls_block += "\n"
    cls_block = cls_block + "\n" + ("\n".join(inserts)).rstrip() + "\n"

# ---- add keybindings in __init__ (Ctrl+Shift+I / Ctrl+Shift+E) ---------------
def inject_keybind(block: str) -> str:
    m = re.search(r'^\s*def\s+__init__\s*\(\s*self[^\)]*\)\s*:\s*$', block, re.M)
    if not m: return block
    start = m.end()
    indent = re.match(r'[ \t]*', block[m.start():m.end()]).group(0)
    after = block[start:]
    mnext = re.search(rf'^{indent}def\s+\w+\s*\(', after, re.M)
    end = start + (mnext.start() if mnext else len(after))
    body = block[start:end]
    if "Control-Shift-I" not in body:
        body = f'{method_indent}try: self.bind("<Control-Shift-I>", self._on_import_images_clicked)\n{method_indent}except Exception: pass\n' + body
    if "Control-Shift-E" not in body:
        body = f'{method_indent}try: self.bind("<Control-Shift-E>", self._export_current_images_aware)\n{method_indent}except Exception: pass\n' + body
    return block[:start] + body + block[end:]

cls_block2 = inject_keybind(cls_block)

# ---- best-effort: add menu items under File menu -----------------------------
def inject_file_menu_items(block: str) -> str:
    # Find the File menu var from add_cascade(label="File", menu=NAME)
    m = re.search(r'add_cascade\s*\(\s*label\s*=\s*["\\\']File["\\\']\s*,\s*menu\s*=\s*([A-Za-z_]\w*)\s*\)', block)
    if not m:
        return block
    menu_var = m.group(1)
    # Locate region after this line to insert commands
    pos = m.end()
    after = block[pos:]
    # If items already present, no-op
    if f'{menu_var}.add_command(label="Import Images' in after or f"{menu_var}.add_command(label='Import Images" in after:
        pass
    else:
        insertion = (
            f'{method_indent}# Added by patch: image import/export commands\n'
            f'{method_indent}try:\n'
            f'{method_indent}    {menu_var}.add_command(label="Import Images…", command=self._on_import_images_clicked)\n'
            f'{method_indent}    {menu_var}.add_command(label="Export Image…", command=self._export_current_images_aware)\n'
            f'{method_indent}except Exception:\n'
            f'{method_indent}    pass\n'
        )
        block = block[:pos] + "\n" + insertion + block[pos:]
    return block

cls_block3 = inject_file_menu_items(cls_block2)

# reassemble file
if cls_block3 != src[start_cls:end_cls]:
    src = src[:start_cls] + cls_block3 + src[end_cls:]

if src != orig:
    io.open(path, "w", encoding="utf-8").write(src)
    print("✅ Patched DemoKitGUI: Import Images menu + images-aware Export + shortcuts")
else:
    print("ℹ️ No changes needed (already patched)")
PY

# syntax check; restore on failure
if python3 -m py_compile "$FILE" 2>/dev/null; then
  echo "✅ Patched $FILE (backup at $BACKUP)"
else
  echo "⚠️ Syntax error — restoring backup."
  mv "$BACKUP" "$FILE"
  exit 1
fi

echo "Now run:  python3 main.py"
echo "Use File → Import Images… (or Ctrl+Shift+I) and File → Export Image… (or Ctrl+Shift+E)."

