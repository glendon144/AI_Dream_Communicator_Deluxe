#!/usr/bin/env bash
set -euo pipefail

FILE="modules/gui_tkinter.py"
BACKUP="${FILE}.bak.$(date +%Y%m%d-%H%M%S)"

[[ -f "$FILE" ]] || { echo "❌ Not found: $FILE"; exit 1; }
cp -p "$FILE" "$BACKUP"

python3 - "$FILE" <<'PY'
import ast, io, re, sys

path = sys.argv[1]
src = io.open(path, "r", encoding="utf-8", errors="surrogatepass").read()
lines = src.splitlines(True)

def insert_after_line(idx, text):
    """Insert `text` (string) AFTER line index `idx`."""
    if not text.endswith("\n"):
        text += "\n"
    lines.insert(idx + 1, text)

# ---------- parse & locate DemoKitGUI ----------
tree = ast.parse(src)
demo_cls = None
for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name == "DemoKitGUI":
        demo_cls = node
        break
if demo_cls is None:
    print("❌ Could not find class DemoKitGUI", file=sys.stderr); sys.exit(2)

# Find __init__ if present
init_fn = None
for n in demo_cls.body:
    if isinstance(n, ast.FunctionDef) and n.name == "__init__":
        init_fn = n
        break

# ---------- compute indents ----------
class_header_line = lines[demo_cls.lineno - 1]
class_indent = re.match(r'[ \t]*', class_header_line).group(0)
method_indent = class_indent + ("    " if "\t" not in class_indent else "\t")

# ---------- ensure imports (idempotent) ----------
def ensure_import(name):
    global lines
    if not re.search(r'^\s*import\s+' + re.escape(name) + r'\b', "".join(lines), re.M):
        # insert after first import-like line (from/import)
        text = "".join(lines)
        m = re.search(r'^(?:from\s+\S+\s+import\s+.*|import\s+.*)$', text, re.M)
        pos = m.end() if m else 0
        # convert pos to line index
        acc = 0
        for idx, ln in enumerate(lines):
            acc += len(ln)
            if acc >= pos:
                insert_after_line(idx, f"import {name}")
                break

ensure_import("base64")
ensure_import("mimetypes")

# ---------- helper: does class already have a function? ----------
def class_has_func(name):
    for n in demo_cls.body:
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return True
    return False

# ---------- build method blocks with token __IND__ for indent ----------
to_append = []

if not class_has_func("_filetypes_images_first"):
    to_append.append(
        "__IND__def _filetypes_images_first(self):\n"
        "__IND__    return [\n"
        "__IND__        (\"Images\", \"*.png *.jpg *.jpeg *.gif *.bmp *.webp\"),\n"
        "__IND__        (\"Text files\", \"*.txt *.md *.opml *.xml *.html *.htm *.json\"),\n"
        "__IND__        (\"All files\", \"*.*\"),\n"
        "__IND__    ]\n"
    )

if not class_has_func("_data_url_from_path"):
    to_append.append(
        "__IND__def _data_url_from_path(self, path):\n"
        "__IND__    from pathlib import Path\n"
        "__IND__    p = Path(path)\n"
        "__IND__    b = p.read_bytes()\n"
        "__IND__    import mimetypes\n"
        "__IND__    mt, _ = mimetypes.guess_type(p.name)\n"
        "__IND__    if not mt or not mt.startswith(\"image/\"):\n"
        "__IND__        if b.startswith(b\"\\x89PNG\\r\\n\\x1a\\n\"):\n"
        "__IND__            mt = \"image/png\"\n"
        "__IND__        elif b.startswith(b\"\\xff\\xd8\"):\n"
        "__IND__            mt = \"image/jpeg\"\n"
        "__IND__        elif b.startswith(b\"GIF87a\") or b.startswith(b\"GIF89a\"):\n"
        "__IND__            mt = \"image/gif\"\n"
        "__IND__        elif b.startswith(b\"BM\"):\n"
        "__IND__            mt = \"image/bmp\"\n"
        "__IND__        elif len(b) >= 12 and b[0:4] == b\"RIFF\" and b[8:12] == b\"WEBP\":\n"
        "__IND__            mt = \"image/webp\"\n"
        "__IND__        else:\n"
        "__IND__            mt = \"application/octet-stream\"\n"
        "__IND__    import base64\n"
        "__IND__    return \"data:\" + mt + \";base64,\" + base64.b64encode(b).decode(\"ascii\")\n"
    )

if not class_has_func("_export_current_images_aware"):
    to_append.append(
        "__IND__def _export_current_images_aware(self, event=None):\n"
        "__IND__    \"\"\"Export current doc; if body is data:image;base64, write real bytes.\"\"\"\n"
        "__IND__    body = None\n"
        "__IND__    try:\n"
        "__IND__        if hasattr(self, \"get_current_body\") and callable(getattr(self, \"get_current_body\")):\n"
        "__IND__            body = self.get_current_body()\n"
        "__IND__        elif hasattr(self, \"text\"):\n"
        "__IND__            body = self.text.get(\"1.0\", \"end-1c\")\n"
        "__IND__    except Exception:\n"
        "__IND__        body = None\n"
        "__IND__    if not isinstance(body, str) or not body.startswith(\"data:image/\"):\n"
        "__IND__        if hasattr(self, \"_on_export_clicked\"):\n"
        "__IND__            try:\n"
        "__IND__                return self._on_export_clicked()\n"
        "__IND__            except Exception:\n"
        "__IND__                pass\n"
        "__IND__        return\n"
        "__IND__    import re, base64\n"
        "__IND__    m = re.match(r\"^data:(image/[A-Za-z0-9.+-]+);base64,(.*)$\", body, re.S)\n"
        "__IND__    if not m:\n"
        "__IND__        if hasattr(self, \"_on_export_clicked\"):\n"
        "__IND__            try:\n"
        "__IND__                return self._on_export_clicked()\n"
        "__IND__            except Exception:\n"
        "__IND__                pass\n"
        "__IND__        return\n"
        "__IND__    mime, b64 = m.groups()\n"
        "__IND__    extmap = {\"image/png\": \".png\", \"image/jpeg\": \".jpg\", \"image/gif\": \".gif\", \"image/bmp\": \".bmp\", \"image/webp\": \".webp\"}\n"
        "__IND__    ext = extmap.get(mime, \".bin\")\n"
        "__IND__    from tkinter import filedialog, messagebox\n"
        "__IND__    fn = filedialog.asksaveasfilename(defaultextension=ext, filetypes=[(\"All files\", \"*.*\")])\n"
        "__IND__    if not fn:\n"
        "__IND__        return\n"
        "__IND__    try:\n"
        "__IND__        with open(fn, \"wb\") as f:\n"
        "__IND__            f.write(base64.b64decode(b64))\n"
        "__IND__        try:\n"
        "__IND__            messagebox.showinfo(\"Export\", \"Saved: \" + str(fn))\n"
        "__IND__        except Exception:\n"
        "__IND__            pass\n"
        "__IND__    except Exception:\n"
        "__IND__        pass\n"
    )

if not class_has_func("_on_import_images_clicked"):
    to_append.append(
        "__IND__def _on_import_images_clicked(self, event=None):\n"
        "__IND__    from tkinter import filedialog, messagebox\n"
        "__IND__    paths = filedialog.askopenfilenames(\n"
        "__IND__        title=\"Import Images...\",\n"
        "__IND__        filetypes=self._filetypes_images_first()\n"
        "__IND__    )\n"
        "__IND__    if not paths:\n"
        "__IND__        return\n"
        "__IND__    created = []\n"
        "__IND__    for path in paths:\n"
        "__IND__        try:\n"
        "__IND__            body = self._data_url_from_path(path)\n"
        "__IND__            try:\n"
        "__IND__                from pathlib import Path as _P\n"
        "__IND__                title = _P(path).name\n"
        "__IND__            except Exception:\n"
        "__IND__                title = \"image\"\n"
        "__IND__            doc_id = None\n"
        "__IND__            # GUI helpers\n"
        "__IND__            for name in (\"create_document\",\"new_document\",\"add_document_here\"):\n"
        "__IND__                fn = getattr(self, name, None)\n"
        "__IND__                if callable(fn):\n"
        "__IND__                    try:\n"
        "__IND__                        doc_id = fn(title, body); break\n"
        "__IND__                    except TypeError:\n"
        "__IND__                        try:\n"
        "__IND__                            doc_id = fn({'title': title, 'body': body}); break\n"
        "__IND__                        except Exception:\n"
        "__IND__                            pass\n"
        "__IND__            if doc_id is None:\n"
        "__IND__                try:\n"
        "__IND__                    from modules import document_store as _ds\n"
        "__IND__                    for name in (\"create_document\",\"add_document\",\"insert_document\",\"new_document\",\"create\",\"add\"):\n"
        "__IND__                        fn = getattr(_ds, name, None)\n"
        "__IND__                        if callable(fn):\n"
        "__IND__                            try:\n"
        "__IND__                                doc_id = fn(title, body); break\n"
        "__IND__                            except TypeError:\n"
        "__IND__                                try:\n"
        "__IND__                                    doc_id = fn({'title': title, 'body': body}); break\n"
        "__IND__                                except Exception:\n"
        "__IND__                                    pass\n"
        "__IND__                except Exception:\n"
        "__IND__                    pass\n"
        "__IND__            if doc_id is not None:\n"
        "__IND__                created.append(doc_id)\n"
        "__IND__        except Exception:\n"
        "__IND__            continue\n"
        "__IND__    if created:\n"
        "__IND__        last_id = created[-1]\n"
        "__IND__        try:\n"
        "__IND__            messagebox.showinfo(\"Import\", \"Document \" + str(last_id) + \" created\")\n"
        "__IND__        except Exception:\n"
        "__IND__            pass\n"
        "__IND__        try:\n"
        "__IND__            if hasattr(self, \"reload_index\"):\n"
        "__IND__                self.reload_index()\n"
        "__IND__            tree = getattr(self, \"tree\", None)\n"
        "__IND__            if tree:\n"
        "__IND__                for it in tree.get_children(\"\"):\n"
        "__IND__                    vals = tree.item(it, \"values\")\n"
        "__IND__                    if vals and str(vals[0]) == str(last_id):\n"
        "__IND__                        tree.selection_set(it); tree.see(it)\n"
        "__IND__                        if hasattr(self, \"open_doc_by_id\"):\n"
        "__IND__                            self.open_doc_by_id(last_id)\n"
        "__IND__                        break\n"
        "__IND__        except Exception:\n"
        "__IND__            pass\n"
    )

# Append methods (if any) at end of class block (before dedent)
if to_append:
    insert_idx = (demo_cls.end_lineno or demo_cls.lineno) - 1
    block = "\n"
    for meth in to_append:
        block += meth.replace("__IND__", method_indent).rstrip() + "\n\n"
    insert_after_line(insert_idx, block)

# ---------- add shortcuts in __init__ (idempotent) ----------
if init_fn is not None:
    # insert after def line or docstring
    target_idx = init_fn.lineno - 1
    if init_fn.body and isinstance(init_fn.body[0], ast.Expr) and hasattr(init_fn.body[0], "value") and isinstance(init_fn.body[0].value, ast.Constant) and isinstance(init_fn.body[0].value.value, str):
        target_idx = init_fn.body[0].end_lineno - 1
    # body indent = first line after def
    next_line = lines[target_idx + 1] if target_idx + 1 < len(lines) else method_indent + "pass\n"
    body_indent = re.match(r'[ \t]*', next_line).group(0) or method_indent

    cls_text = "".join(lines[demo_cls.lineno-1 : (demo_cls.end_lineno or demo_cls.lineno)])
    if "Control-Shift-I" not in cls_text:
        insert_after_line(target_idx, f'{body_indent}try: self.bind("<Control-Shift-I>", self._on_import_images_clicked)\n{body_indent}except Exception: pass')
        target_idx += 1
    if "Control-Shift-E" not in cls_text:
        insert_after_line(target_idx, f'{body_indent}try: self.bind("<Control-Shift-E>", self._export_current_images_aware)\n{body_indent}except Exception: pass')

# ---------- add File menu entries (best-effort, idempotent) ----------
class_text = "".join(lines[demo_cls.lineno-1 : (demo_cls.end_lineno or demo_cls.lineno)])
if ('Import Images...' not in class_text) or ('Export Image...' not in class_text):
    # find a line like: menubar.add_cascade(label="File", menu=file_menu)
    m = re.search(r'^([ \t]*)([A-Za-z_]\w*)\.add_cascade\(\s*label\s*=\s*["\']File["\']\s*,\s*menu\s*=\s*([A-Za-z_]\w*)\s*\)\s*$', class_text, re.M)
    if m:
        # compute global line index of that match
        rel_offset = m.start()
        acc = 0
        base = demo_cls.lineno - 1
        target_line_idx = None
        for i in range(base, (demo_cls.end_lineno or demo_cls.lineno)):
            acc += len(lines[i])
            if acc > rel_offset:
                target_line_idx = i
                break
        if target_line_idx is not None:
            indent = m.group(1)
            menu_var = m.group(3)
            inj = (
                indent + "try:\n" +
                indent + f"    {menu_var}.add_command(label=\"Import Images...\", command=self._on_import_images_clicked)\n" +
                indent + f"    {menu_var}.add_command(label=\"Export Image...\", command=self._export_current_images_aware)\n" +
                indent + "except Exception:\n" +
                indent + "    pass\n"
            )
            insert_after_line(target_line_idx, inj)

# ---------- write back ----------
new_src = "".join(lines)
io.open(path, "w", encoding="utf-8").write(new_src)
print("✅ Patched DemoKitGUI: Import Images menu + images-aware Export + shortcuts (AST-safe, no .format)")
PY

# syntax check; restore backup on failure
if python3 -m py_compile "$FILE" 2>/dev/null; then
  echo "✅ Patched $FILE (backup at $BACKUP)"
else
  echo "⚠️ Syntax error — restoring backup."
  mv "$BACKUP" "$FILE"
  exit 1
fi

echo "Now run:  python3 main.py"
echo "Use File → Import Images… (or Ctrl+Shift+I) and File → Export Image… (or Ctrl+Shift+E)."

