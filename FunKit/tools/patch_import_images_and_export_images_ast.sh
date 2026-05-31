#!/usr/bin/env bash
set -euo pipefail

FILE="modules/gui_tkinter.py"
BACKUP="${FILE}.bak.$(date +%Y%m%d-%H%M%S)"

[[ -f "$FILE" ]] || { echo "❌ Not found: $FILE"; exit 1; }
cp -p "$FILE" "$BACKUP"

python3 - "$FILE" <<'PY'
import ast, io, re, sys, textwrap

path = sys.argv[1]
src = io.open(path, "r", encoding="utf-8", errors="surrogatepass").read()
lines = src.splitlines(True)

def insert_lines_at(idx, new_text):
    """Insert new_text (string, already includes trailing newline if needed) after line index idx."""
    lines.insert(idx + 1, new_text)

# ---------------- AST: find DemoKitGUI and __init__ ----------------
tree = ast.parse(src)
demo_cls = None
for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name == "DemoKitGUI":
        demo_cls = node
        break

if demo_cls is None:
    print("❌ Could not find class DemoKitGUI", file=sys.stderr)
    sys.exit(2)

init_fn = None
for node in demo_cls.body:
    if isinstance(node, ast.FunctionDef) and node.name == "__init__":
        init_fn = node
        break

# compute indents
class_header_line = lines[demo_cls.lineno - 1]
class_indent = re.match(r'[ \t]*', class_header_line).group(0)
method_indent = class_indent + ("    " if "\t" not in class_indent else "\t")

# ---------------- ensure imports (idempotent) ----------------------
def ensure_import(modname):
    g = re.search(r'^\s*import\s+' + re.escape(modname) + r'\b', src, re.M)
    if g is None:
        # insert after the first import-like line
        m = re.search(r'^(?:from\s+\S+\s+import\s+.*|import\s+.*)$', "".join(lines), re.M)
        pos = m.end() if m else 0
        # find line index at pos
        cum = 0
        for i, ln in enumerate(lines):
            cum += len(ln)
            if cum >= pos:
                lines.insert(i+1, "import "+modname+"\n")
                break

ensure_import("base64")
ensure_import("mimetypes")

# ---------------- insert helper methods (idempotent) ---------------
def class_has_func(name):
    for n in demo_cls.body:
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return True
    return False

to_add = []

if not class_has_func("_filetypes_images_first"):
    to_add.append((
        "_filetypes_images_first",
        textwrap.dedent("""\
        {indent}def _filetypes_images_first(self):
        {indent}    return [
        {indent}        ("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
        {indent}        ("Text files", "*.txt *.md *.opml *.xml *.html *.htm *.json"),
        {indent}        ("All files", "*.*"),
        {indent}    ]
        """)
    ))

if not class_has_func("_data_url_from_path"):
    to_add.append((
        "_data_url_from_path",
        textwrap.dedent("""\
        {indent}def _data_url_from_path(self, path):
        {indent}    from pathlib import Path
        {indent}    p = Path(path)
        {indent}    b = p.read_bytes()
        {indent}    import mimetypes
        {indent}    mt, _ = mimetypes.guess_type(p.name)
        {indent}    if not mt or not mt.startswith("image/"):
        {indent}        if b.startswith(b"\\x89PNG\\r\\n\\x1a\\n"):
        {indent}            mt = "image/png"
        {indent}        elif b.startswith(b"\\xff\\xd8"):
        {indent}            mt = "image/jpeg"
        {indent}        elif b.startswith(b"GIF87a") or b.startswith(b"GIF89a"):
        {indent}            mt = "image/gif"
        {indent}        elif b.startswith(b"BM"):
        {indent}            mt = "image/bmp"
        {indent}        elif len(b) >= 12 and b[0:4] == b"RIFF" and b[8:12] == b"WEBP":
        {indent}            mt = "image/webp"
        {indent}        else:
        {indent}            mt = "application/octet-stream"
        {indent}    import base64
        {indent}    return "data:" + mt + ";base64," + base64.b64encode(b).decode("ascii")
        """)
    ))

if not class_has_func("_export_current_images_aware"):
    to_add.append((
        "_export_current_images_aware",
        textwrap.dedent("""\
        {indent}def _export_current_images_aware(self, event=None):
        {indent}    """ + '"""' + """Export current doc; if body is data:image;base64, write real bytes.""" + '"""' + """
        {indent}    body = None
        {indent}    try:
        {indent}        if hasattr(self, "get_current_body") and callable(getattr(self, "get_current_body")):
        {indent}            body = self.get_current_body()
        {indent}        elif hasattr(self, "text"):
        {indent}            body = self.text.get("1.0", "end-1c")
        {indent}    except Exception:
        {indent}        body = None
        {indent}    if not isinstance(body, str) or not body.startswith("data:image/"):
        {indent}        if hasattr(self, "_on_export_clicked"):
        {indent}            try:
        {indent}                return self._on_export_clicked()
        {indent}            except Exception:
        {indent}                pass
        {indent}        return
        {indent}    import re, base64
        {indent}    m = re.match(r"^data:(image/[A-Za-z0-9.+-]+);base64,(.*)$", body, re.S)
        {indent}    if not m:
        {indent}        if hasattr(self, "_on_export_clicked"):
        {indent}            try:
        {indent}                return self._on_export_clicked()
        {indent}            except Exception:
        {indent}                pass
        {indent}        return
        {indent}    mime, b64 = m.groups()
        {indent}    extmap = {{"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/bmp": ".bmp", "image/webp": ".webp"}}
        {indent}    ext = extmap.get(mime, ".bin")
        {indent}    from tkinter import filedialog, messagebox
        {indent}    fn = filedialog.asksaveasfilename(defaultextension=ext, filetypes=[("All files", "*.*")])
        {indent}    if not fn:
        {indent}        return
        {indent}    try:
        {indent}        with open(fn, "wb") as f:
        {indent}            f.write(base64.b64decode(b64))
        {indent}        try:
        {indent}            messagebox.showinfo("Export", "Saved: " + str(fn))
        {indent}        except Exception:
        {indent}            pass
        {indent}    except Exception:
        {indent}        pass
        """)
    ))

if not class_has_func("_on_import_images_clicked"):
    to_add.append((
        "_on_import_images_clicked",
        textwrap.dedent("""\
        {indent}def _on_import_images_clicked(self, event=None):
        {indent}    from tkinter import filedialog, messagebox
        {indent}    paths = filedialog.askopenfilenames(
        {indent}        title="Import Images...",
        {indent}        filetypes=self._filetypes_images_first()
        {indent}    )
        {indent}    if not paths:
        {indent}        return
        {indent}    created = []
        {indent}    for path in paths:
        {indent}        try:
        {indent}            body = self._data_url_from_path(path)
        {indent}            try:
        {indent}                from pathlib import Path as _P
        {indent}                title = _P(path).name
        {indent}            except Exception:
        {indent}                title = "image"
        {indent}            doc_id = None
        {indent}            # GUI helpers
        {indent}            for name in ("create_document","new_document","add_document_here"):
        {indent}                fn = getattr(self, name, None)
        {indent}                if callable(fn):
        {indent}                    try:
        {indent}                        doc_id = fn(title, body); break
        {indent}                    except TypeError:
        {indent}                        try:
        {indent}                            doc_id = fn({"title": title, "body": body}); break
        {indent}                        except Exception:
        {indent}                            pass
        {indent}            if doc_id is None:
        {indent}                try:
        {indent}                    from modules import document_store as _ds
        {indent}                    for name in ("create_document","add_document","insert_document","new_document","create","add"):
        {indent}                        fn = getattr(_ds, name, None)
        {indent}                        if callable(fn):
        {indent}                            try:
        {indent}                                doc_id = fn(title, body); break
        {indent}                            except TypeError:
        {indent}                                try:
        {indent}                                    doc_id = fn({"title": title, "body": body}); break
        {indent}                                except Exception:
        {indent}                                    pass
        {indent}                except Exception:
        {indent}                    pass
        {indent}            if doc_id is not None:
        {indent}                created.append(doc_id)
        {indent}        except Exception:
        {indent}            continue
        {indent}    if created:
        {indent}        last_id = created[-1]
        {indent}        try:
        {indent}            messagebox.showinfo("Import", "Document " + str(last_id) + " created")
        {indent}        except Exception:
        {indent}            pass
        {indent}        try:
        {indent}            if hasattr(self, "reload_index"):
        {indent}                self.reload_index()
        {indent}            tree = getattr(self, "tree", None)
        {indent}            if tree:
        {indent}                for it in tree.get_children(""):
        {indent}                    vals = tree.item(it, "values")
        {indent}                    if vals and str(vals[0]) == str(last_id):
        {indent}                        tree.selection_set(it); tree.see(it)
        {indent}                        if hasattr(self, "open_doc_by_id"):
        {indent}                            self.open_doc_by_id(last_id)
        {indent}                        break
        {indent}        except Exception:
        {indent}            pass
        """)
    ))

# Insert methods at the end of class block
if to_add:
    insert_at = (demo_cls.end_lineno or demo_cls.lineno) - 1
    block = "\n"
    for _, tmpl in to_add:
        block += tmpl.format(indent=method_indent).rstrip() + "\n\n"
    insert_lines_at(insert_at, block)

# ---------------- add shortcuts in __init__ (idempotent) -----------
if init_fn is not None:
    init_def_line_idx = init_fn.lineno - 1
    # Find insertion line: after def line and docstring (if present)
    insert_after_idx = init_def_line_idx
    if init_fn.body and isinstance(init_fn.body[0], ast.Expr) and isinstance(getattr(init_fn.body[0], "value", None), ast.Constant) and isinstance(init_fn.body[0].value.value, str):
        insert_after_idx = init_fn.body[0].end_lineno - 1
    # Determine body indent
    body_line = lines[insert_after_idx+1] if insert_after_idx+1 < len(lines) else (method_indent + "pass\n")
    body_indent = re.match(r'[ \t]*', body_line).group(0) or method_indent
    # Only insert if not already present
    class_block_text = "".join(lines[demo_cls.lineno-1 : (demo_cls.end_lineno or demo_cls.lineno)])
    if "Control-Shift-I" not in class_block_text:
        insert_lines_at(insert_after_idx, f'{body_indent}try: self.bind("<Control-Shift-I>", self._on_import_images_clicked)\n{body_indent}except Exception: pass\n')
        insert_after_idx += 1
    if "Control-Shift-E" not in class_block_text:
        insert_lines_at(insert_after_idx, f'{body_indent}try: self.bind("<Control-Shift-E>", self._export_current_images_aware)\n{body_indent}except Exception: pass\n')

# ---------------- add File menu items (best-effort, idempotent) ----
# Find the 'File' cascade line anywhere in the class; inject add_command lines immediately after that line.
class_text = "".join(lines[demo_cls.lineno-1 : (demo_cls.end_lineno or demo_cls.lineno)])
if ('Import Images...' not in class_text) and ('Export Image...' not in class_text):
    # Regex captures: indent, menubar var, file menu var
    # Example it matches: menubar.add_cascade(label="File", menu=file_menu)
    m = re.search(r'^([ \t]*)([A-Za-z_]\w*)\.add_cascade\(\s*label\s*=\s*["\']File["\']\s*,\s*menu\s*=\s*([A-Za-z_]\w*)\s*\)\s*$', class_text, re.M)
    if m:
        file_line_offset = m.start()
        # Convert offset to global line index
        cumulative = 0
        base_idx = demo_cls.lineno - 1
        target_idx = None
        for i in range(base_idx, (demo_cls.end_lineno or demo_cls.lineno)):
            cumulative += len(lines[i])
            if cumulative > file_line_offset:
                target_idx = i
                break
        if target_idx is not None:
            indent = m.group(1)
            menu_var = m.group(3)
            injection = (
                indent + "try:\n" +
                indent + f"    {menu_var}.add_command(label=\"Import Images...\", command=self._on_import_images_clicked)\n" +
                indent + f"    {menu_var}.add_command(label=\"Export Image...\", command=self._export_current_images_aware)\n" +
                indent + "except Exception:\n" +
                indent + "    pass\n"
            )
            insert_lines_at(target_idx, injection)

# ---------------- write back ----------------
new_src = "".join(lines)
io.open(path, "w", encoding="utf-8").write(new_src)
print("✅ Patched DemoKitGUI: Import Images menu + images-aware Export + shortcuts (AST-safe)")
PY

# Syntax check; restore backup on failure
if python3 -m py_compile "$FILE" 2>/dev/null; then
  echo "✅ Patched $FILE (backup at $BACKUP)"
else
  echo "⚠️ Syntax error — restoring backup."
  mv "$BACKUP" "$FILE"
  exit 1
fi

echo "Now run:  python3 main.py"
echo "Use File → Import Images… (or Ctrl+Shift+I) and File → Export Image… (or Ctrl+Shift+E)."

