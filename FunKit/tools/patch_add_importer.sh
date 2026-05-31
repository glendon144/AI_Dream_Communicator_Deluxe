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

# -------------------------------------------------------------------
# 0) Ensure base64 & mimetypes imports exist (idempotent)
# -------------------------------------------------------------------
if re.search(r'^\s*import\s+base64\b', src, re.M) is None:
    # insert after first block of imports
    m = re.search(r'^(?:from\s+\S+\s+import\s+.*|import\s+.*)(\r?\n)+', src, re.M)
    ins_at = m.end() if m else 0
    src = src[:ins_at] + "import base64\n" + src[ins_at:]

if re.search(r'^\s*import\s+mimetypes\b', src, re.M) is None:
    m = re.search(r'^(?:from\s+\S+\s+import\s+.*|import\s+.*)(\r?\n)+', src, re.M)
    ins_at = m.end() if m else 0
    src = src[:ins_at] + "import mimetypes\n" + src[ins_at:]

# -------------------------------------------------------------------
# 1) Locate class DemoKitGUI block boundaries
# -------------------------------------------------------------------
cls_re = re.compile(r'^\s*class\s+DemoKitGUI\b.*?:\s*$', re.M)
mcls = cls_re.search(src)
if not mcls:
    print("❌ Could not find class DemoKitGUI", file=sys.stderr); sys.exit(2)

start_cls = mcls.start()
next_cls = cls_re.search(src, mcls.end())
end_cls = next_cls.start() if next_cls else len(src)
cls_block = src[start_cls:end_cls]

# Determine class indent
cls_indent = re.match(r'^\s*', src[mcls.start():mcls.end()]).group(0)
method_indent = cls_indent + "    "

# -------------------------------------------------------------------
# 2) Inject helpers into DemoKitGUI if missing
# -------------------------------------------------------------------
need_data_url = re.search(r'^\s*def\s+_data_url_from_path\s*\(self,\s*path\)\s*:', cls_block, re.M) is None
need_importer = re.search(r'^\s*def\s+_on_import_images_clicked\s*\(self(?:,\s*event=None)?\)\s*:', cls_block, re.M) is None

insertion_methods = ""

if need_data_url:
    insertion_methods += textwrap.dedent(f"""
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
    {method_indent}    return f"data:{mt};base64,{{data}}"
    """).lstrip("\n")

if need_importer:
    insertion_methods += textwrap.dedent(f"""
    {method_indent}def _on_import_images_clicked(self, event=None):
    {method_indent}    \"\"\"Ask for image files and import each as a document with a base64 data-URL body.\"\"\"
    {method_indent}    try:
    {method_indent}        from tkinter import filedialog
    {method_indent}        paths = filedialog.askopenfilenames(
    {method_indent}            title="Import Images (as Docs)",
    {method_indent}            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"), ("All files", "*.*")]
    {method_indent}        )
    {method_indent}    except Exception:
    {method_indent}        return
    {method_indent}    if not paths: return
    {method_indent}    created = 0
    {method_indent}    for path in paths:
    {method_indent}        try:
    {method_indent}            body = self._data_url_from_path(path)
    {method_indent}            title = getattr(getattr(__import__('pathlib'), 'Path')(path), 'name', str(path))
    {method_indent}            ds = getattr(self, 'doc_store', None)
    {method_indent}            doc_id = None
    {method_indent}            if ds is not None:
    {method_indent}                # Try common document-store APIs without breaking your existing ones.
    {method_indent}                for name in ("create_document","add_document","insert_document","new_document","create","add"):
    {method_indent}                    fn = getattr(ds, name, None)
    {method_indent}                    if callable(fn):
    {method_indent}                        try:
    {method_indent}                            doc_id = fn(title, body)
    {method_indent}                            break
    {method_indent}                        except TypeError:
    {method_indent}                            try:
    {method_indent}                                doc_id = fn({{'title': title, 'body': body}})
    {method_indent}                                break
    {method_indent}                            except TypeError:
    {method_indent}                                pass
    {method_indent}            if doc_id is None and hasattr(self, "create_document"):
    {method_indent}                try:
    {method_indent}                    doc_id = self.create_document(title, body)
    {method_indent}                except Exception:
    {method_indent}                    pass
    {method_indent}            created += 1
    {method_indent}        except Exception:
    {method_indent}            continue
    {method_indent}    # Refresh index/UI if possible
    {method_indent}    try:
    {method_indent}        if hasattr(self, "reload_index"): self.reload_index()
    {method_indent}    except Exception:
    {method_indent}        pass
    """).lstrip("\n")

if insertion_methods:
    # Insert methods just before end of class block
    insert_pos = len(cls_block)
    cls_block = cls_block[:insert_pos] + "\n" + insertion_methods + cls_block[insert_pos:]

# -------------------------------------------------------------------
# 3) Add a toolbar button in _build_main_pane (best-effort, optional)
#    We search for any existing ttk.Button(..., text=..., command=...).pack attached to a variable "toolbar".
#    If found, append ours right after.
# -------------------------------------------------------------------
def inject_toolbar_button(block: str) -> str:
    m = re.search(r'^\s*def\s+_build_main_pane\s*\(self\)\s*:\s*$', block, re.M)
    if not m: return block
    start = m.end()
    # end of method = next def at same indent
    indent = re.match(r'^\s*', block[m.start():m.end()]).group(0)
    after = block[start:]
    mnext = re.search(rf'^{indent}def\s+\w+\s*\(', after, re.M)
    end = start + (mnext.start() if mnext else len(after))
    body = block[start:end]

    # Try to detect the toolbar variable name by spotting any ttk.Button(container,...).pack
    mbtn = re.search(r'ttk\.Button\(\s*([A-Za-z_]\w*)\s*,\s*text=', body)
    container = mbtn.group(1) if mbtn else None
    if not container:
        return block  # give up quietly; keybinding will still exist

    # Do not insert twice
    if re.search(r'Import Images', body):
        return block

    insertion = (
        f"{method_indent}# Added: Import Images button\n"
        f"{method_indent}try:\n"
        f"{method_indent}    ttk.Button({container}, text=\"Import Images\", command=self._on_import_images_clicked).pack(side=tk.LEFT, padx=4, pady=4)\n"
        f"{method_indent}except Exception:\n"
        f"{method_indent}    pass\n"
    )

    # Place insertion after the first detected button (keeps style consistent)
    where = re.search(r'ttk\.Button\(\s*' + re.escape(container) + r'\s*,\s*text=.*?\.pack\([^)]*\)\s*', body, re.S)
    if where:
        insert_at = where.end()
        body = body[:insert_at] + "\n" + insertion + body[insert_at:]
        return block[:start] + body + block[end:]
    return block

cls_block2 = inject_toolbar_button(cls_block)

# -------------------------------------------------------------------
# 4) Add a global keybinding in __init__: Ctrl+Shift+I → _on_import_images_clicked
# -------------------------------------------------------------------
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
    # Insert right after the first real line of body
    body = body[:0] + bind_line + body[0:]
    return block[:start] + body + block[end:]

cls_block3 = inject_keybind(cls_block2)

# -------------------------------------------------------------------
# 5) Reassemble file if anything changed in class block
# -------------------------------------------------------------------
if cls_block3 != cls_block:
    src = src[:start_cls] + cls_block3 + src[end_cls:]

if src != orig:
    io.open(path, "w", encoding="utf-8").write(src)
    print("✅ Patched DemoKitGUI with image importer (button+shortcut)")
else:
    print("ℹ️ No changes needed (already patched)")
PY

# Syntax check; restore if fail
if python3 -m py_compile "$FILE" 2>/dev/null; then
  echo "✅ Patched $FILE (backup at $BACKUP)"
else
  echo "⚠️ Syntax error — restoring backup."
  mv "$BACKUP" "$FILE"
  exit 1
fi

echo "Now try:  python3 main.py"

