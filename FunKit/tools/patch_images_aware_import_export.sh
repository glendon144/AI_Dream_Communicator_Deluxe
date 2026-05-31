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

# --- 0) Ensure imports (idempotent) ------------------------------------------
def ensure_import(modname, line=""):
    global src
    if re.search(rf'^\s*import\s+{re.escape(modname)}\b', src, re.M) is None:
        # insert after first import block
        m = re.search(r'^(?:from\s+\S+\s+import\s+.*|import\s+.*)(\r?\n)+', src, re.M)
        pos = m.end() if m else 0
        src = src[:pos] + (line or f"import {modname}\n") + src[pos:]

ensure_import("base64")
ensure_import("mimetypes")

# --- 1) Find class DemoKitGUI -------------------------------------------------
cls_re = re.compile(r'^\s*class\s+DemoKitGUI\b.*?:\s*$', re.M)
mcls = cls_re.search(src)
if not mcls:
    print("❌ Could not find class DemoKitGUI", file=sys.stderr); sys.exit(2)

start_cls = mcls.start()
next_cls = cls_re.search(src, mcls.end())
end_cls = next_cls.start() if next_cls else len(src)
cls_block = src[start_cls:end_cls]

cls_indent = re.match(r'^\s*', src[mcls.start():mcls.end()]).group(0)
method_indent = cls_indent + "    "

# --- 2) Add helpers if missing ------------------------------------------------
def missing(name_pat):
    return re.search(rf'^\s*def\s+{name_pat}\s*\(', cls_block, re.M) is None

inserts = []

if missing(r"_data_url_from_path"):
    inserts.append(textwrap.dedent(f"""
    {method_indent}def _data_url_from_path(self, path):
    {method_indent}    \"\"\"Return data:image/...;base64,... for a local image file path.\"\"\"
    {method_indent}    from pathlib import Path
    {method_indent}    p = Path(path)
    {method_indent}    b = p.read_bytes()
    {method_indent}    mt, _ = mimetypes.guess_type(p.name)
    {method_indent}    if not mt or not mt.startswith('image/'):
    {method_indent}        # minimal sniff
    {method_indent}        if b.startswith(b"\\x89PNG\\r\\n\\x1a\\n"): mt = "image/png"
    {method_indent}        elif b.startswith(b"\\xff\\xd8"): mt = "image/jpeg"
    {method_indent}        elif b.startswith(b"GIF87a") or b.startswith(b"GIF89a"): mt = "image/gif"
    {method_indent}        elif b.startswith(b"BM"): mt = "image/bmp"
    {method_indent}        elif len(b) >= 12 and b[0:4] == b"RIFF" and b[8:12] == b"WEBP": mt = "image/webp"
    {method_indent}        else: mt = "application/octet-stream"
    {method_indent}    data = base64.b64encode(b).decode('ascii')
    {method_indent}    return f"data:{{mt}};base64,{{data}}"
    """).lstrip("\n"))

if missing(r"_sniff_image_bytes"):
    inserts.append(textwrap.dedent(f"""
    {method_indent}def _sniff_image_bytes(self, b: bytes):
    {method_indent}    if b.startswith(b"\\x89PNG\\r\\n\\x1a\\n"): return "image/png"
    {method_indent}    if b.startswith(b"\\xff\\xd8"): return "image/jpeg"
    {method_indent}    if b.startswith(b"GIF87a") or b.startswith(b"GIF89a"): return "image/gif"
    {method_indent}    if b.startswith(b"BM"): return "image/bmp"
    {method_indent}    if len(b) >= 12 and b[0:4] == b"RIFF" and b[8:12] == b"WEBP": return "image/webp"
    {method_indent}    return None
    """).lstrip("\n"))

if missing(r"_read_for_import"):
    inserts.append(textwrap.dedent(f"""
    {method_indent}def _read_for_import(self, path):
    {method_indent}    \"\"\"Return ('text', str) | ('image', data_url) | ('binary', bytes).\"\"\"
    {method_indent}    from pathlib import Path
    {method_indent}    p = Path(path)
    {method_indent}    try:
    {method_indent}        return 'text', p.read_text(encoding='utf-8')
    {method_indent}    except UnicodeDecodeError:
    {method_indent}        b = p.read_bytes()
    {method_indent}        mime = self._sniff_image_bytes(b)
    {method_indent}        if mime is None:
    {method_indent}            mt, _ = mimetypes.guess_type(p.name)
    {method_indent}            if mt and mt.startswith('image/'): mime = mt
    {method_indent}        if mime:
    {method_indent}            data = base64.b64encode(b).decode('ascii')
    {method_indent}            return 'image', f'data:{{mime}};base64,{{data}}'
    {method_indent}        return 'binary', b
    """).lstrip("\n"))

if missing(r"_create_doc_any"):
    inserts.append(textwrap.dedent(f"""
    {method_indent}def _create_doc_any(self, title, body):
    {method_indent}    \"\"\"Try several document store APIs; return doc_id or None.\"\"\" 
    {method_indent}    ds = getattr(self, 'doc_store', None)
    {method_indent}    # 1) a GUI helper, if you have one
    {method_indent}    for name in ('create_document', 'new_document', 'add_document_here'):
    {method_indent}        fn = getattr(self, name, None)
    {method_indent}        if callable(fn):
    {method_indent}            try:
    {method_indent}                return fn(title, body)
    {method_indent}            except TypeError:
    {method_indent}                try:
    {method_indent}                    return fn({{'title': title, 'body': body}})
    {method_indent}                except Exception:
    {method_indent}                    pass
    {method_indent}    # 2) the document_store module
    {method_indent}    if ds is not None:
    {method_indent}        for name in ('create_document','add_document','insert_document','new_document','create','add'):
    {method_indent}            fn = getattr(ds, name, None)
    {method_indent}            if callable(fn):
    {method_indent}                try:
    {method_indent}                    return fn(title, body)
    {method_indent}                except TypeError:
    {method_indent}                    try:
    {method_indent}                        return fn({{'title': title, 'body': body}})
    {method_indent}                    except Exception:
    {method_indent}                        pass
    {method_indent}    return None
    """).lstrip("\n"))

if missing(r"_select_doc_by_id"):
    inserts.append(textwrap.dedent(f"""
    {method_indent}def _select_doc_by_id(self, doc_id):
    {method_indent}    try:
    {method_indent}        tree = getattr(self, 'tree', None)
    {method_indent}        if not tree: return
    {method_indent}        # refresh index first
    {method_indent}        if hasattr(self, 'reload_index'): self.reload_index()
    {method_indent}        for it in tree.get_children(''):
    {method_indent}            vals = tree.item(it, 'values')
    {method_indent}            if not vals: continue
    {method_indent}            if str(vals[0]) == str(doc_id):
    {method_indent}                tree.selection_set(it)
    {method_indent}                tree.see(it)
    {method_indent}                # open if the app has such a method
    {method_indent}                if hasattr(self, 'open_doc_by_id'): self.open_doc_by_id(doc_id)
    {method_indent}                break
    {method_indent}    except Exception:
    {method_indent}        pass
    """).lstrip("\n"))

if missing(r"_on_import_images_clicked"):
    inserts.append(textwrap.dedent(f"""
    {method_indent}def _on_import_images_clicked(self, event=None):
    {method_indent}    from tkinter import filedialog, messagebox
    {method_indent}    paths = filedialog.askopenfilenames(
    {method_indent}        title="Import Images (as Docs)",
    {method_indent}        filetypes=[("Images","*.png *.jpg *.jpeg *.gif *.bmp *.webp"),("All files","*.*")]
    {method_indent}    )
    {method_indent}    if not paths: return
    {method_indent}    created_ids = []
    {method_indent}    for path in paths:
    {method_indent}        try:
    {method_indent}            body = self._data_url_from_path(path)
    {method_indent}            from pathlib import Path as _P
    {method_indent}            title = _P(path).name
    {method_indent}            doc_id = self._create_doc_any(title, body)
    {method_indent}            if doc_id is not None:
    {method_indent}                created_ids.append(doc_id)
    {method_indent}        except Exception:
    {method_indent}            continue
    {method_indent}    if created_ids:
    {method_indent}        last_id = created_ids[-1]
    {method_indent}        try:
    {method_indent}            from tkinter import messagebox
    {method_indent}            messagebox.showinfo("Import", f"Document {{last_id}} created")
    {method_indent}        except Exception:
    {method_indent}            pass
    {method_indent}        self._select_doc_by_id(last_id)
    """).lstrip("\n"))

if missing(r"_export_current_images_aware"):
    inserts.append(textwrap.dedent(f"""
    {method_indent}def _export_current_images_aware(self):
    {method_indent}    \"\"\"Export current doc; if body is data:image;base64, write real binary.\"\"\" 
    {method_indent}    try:
    {method_indent}        # Get current doc content via methods your app already has
    {method_indent}        body = None
    {method_indent}        if hasattr(self, 'get_current_body') and callable(getattr(self,'get_current_body')):
    {method_indent}            body = self.get_current_body()
    {method_indent}        elif hasattr(self, 'text'):
    {method_indent}            try: body = self.text.get("1.0","end-1c")
    {method_indent}            except Exception: body = None
    {method_indent}        if not isinstance(body, str) or not body.startswith("data:image/"):
    {method_indent}            # Fallback to your existing export
    {method_indent}            if hasattr(self, '_on_export_clicked'): return self._on_export_clicked()
    {method_indent}            return
    {method_indent}        import base64, re
    {method_indent}        m = re.match(r'^data:(image/[a-zA-Z0-9.+-]+);base64,(.*)$', body, re.S)
    {method_indent}        if not m:
    {method_indent}            if hasattr(self, '_on_export_clicked'): return self._on_export_clicked()
    {method_indent}            return
    {method_indent}        mime, b64 = m.groups()
    {method_indent}        ext = {{
    {method_indent}            'image/png': '.png','image/jpeg': '.jpg','image/gif': '.gif',
    {method_indent}            'image/bmp': '.bmp','image/webp': '.webp'
    {method_indent}        }}.get(mime, '.bin')
    {method_indent}        from tkinter import filedialog
    {method_indent}        fn = filedialog.asksaveasfilename(defaultextension=ext, filetypes=[("All files","*.*")])
    {method_indent}        if not fn: return
    {method_indent}        with open(fn, "wb") as f:
    {method_indent}            f.write(base64.b64decode(b64))
    {method_indent}    except Exception:
    {method_indent}        # Never crash UI on export
    {method_indent}        pass
    """).lstrip("\n"))

if inserts:
    cls_block = cls_block.rstrip() + "\n\n" + ("\n".join(inserts)).rstrip() + "\n"

# --- 3) Add Ctrl+Shift+I bind in __init__ (idempotent) ------------------------
def inject_keybind(block: str) -> str:
    m = re.search(r'^\s*def\s+__init__\s*\(\s*self[^\)]*\)\s*:\s*$', block, re.M)
    if not m: return block
    start = m.end()
    indent = re.match(r'^\s*', block[m.start():m.end()]).group(0)
    after = block[start:]
    mnext = re.search(rf'^{indent}def\s+\w+\s*\(', after, re.M)
    end = start + (mnext.start() if mnext else len(after))
    body = block[start:end]
    if "Control-Shift-I" in body or "Control-Shift-i" in body:
        return block
    bind_line = f'{method_indent}try: self.bind("<Control-Shift-I>", self._on_import_images_clicked)\n{method_indent}except Exception: pass\n'
    body = bind_line + body
    return block[:start] + body + block[end:]

cls_block2 = inject_keybind(cls_block)

# --- 4) Best-effort: add a toolbar button in _build_main_pane -----------------
def inject_toolbar_button(block: str) -> str:
    m = re.search(r'^\s*def\s+_build_main_pane\s*\(self\)\s*:\s*$', block, re.M)
    if not m: return block
    start = m.end()
    indent = re.match(r'^\s*', block[m.start():m.end()]).group(0)
    after = block[start:]
    mnext = re.search(rf'^{indent}def\s+\w+\s*\(', after, re.M)
    end = start + (mnext.start() if mnext else len(after))
    body = after[:(mnext.start() if mnext else len(after))]
    if "Import Images" in body:
        return block
    # detect a container var used for existing buttons
    mbtn = re.search(r'ttk\.Button\(\s*([A-Za-z_]\w*)\s*,\s*text=', body)
    container = mbtn.group(1) if mbtn else None
    if not container:
        return block
    insertion = (
        f"{method_indent}# Added: Import Images button\n"
        f"{method_indent}try:\n"
        f"{method_indent}    ttk.Button({container}, text=\"Import Images\", command=self._on_import_images_clicked).pack(side=tk.LEFT, padx=4, pady=4)\n"
        f"{method_indent}except Exception:\n"
        f"{method_indent}    pass\n"
    )
    where = re.search(r'ttk\.Button\(\s*' + re.escape(container) + r'\s*,\s*text=.*?\.pack\([^)]*\)\s*', body, re.S)
    if where:
        pos = where.end()
        body = body[:pos] + "\n" + insertion + body[pos:]
        return block[:start] + body + after[(mnext.start() if mnext else len(after)):]
    return block

cls_block3 = inject_toolbar_button(cls_block2)

# --- 5) Reassemble ------------------------------------------------------------
if cls_block3 != src[start_cls:end_cls]:
    src = src[:start_cls] + cls_block3 + src[end_cls:]

if src != orig:
    io.open(path, "w", encoding="utf-8").write(src)
    print("✅ Patched DemoKitGUI (images import + images-aware export)")
else:
    print("ℹ️ No changes needed (already patched)")
PY

# Syntax check; restore backup on failure
if python3 -m py_compile "$FILE" 2>/dev/null; then
  echo "✅ Patched $FILE (backup at $BACKUP)"
else
  echo "⚠️ Syntax error — restoring backup."
  mv "$BACKUP" "$FILE"
  exit 1
fi

echo "Now try:  python3 main.py"

