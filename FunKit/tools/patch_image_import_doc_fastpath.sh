#!/usr/bin/env bash
set -euo pipefail

FILE="modules/gui_tkinter.py"
BACKUP="${FILE}.bak.$(date +%Y%m%d-%H%M%S)"

[[ -f "$FILE" ]] || { echo "❌ Not found: $FILE"; exit 1; }
cp -p "$FILE" "$BACKUP"

python3 - "$FILE" <<'PY'
import io, re, sys
from pathlib import Path

path = sys.argv[1]
src = io.open(path, "r", encoding="utf-8", errors="surrogatepass").read()

# Find DemoKitGUI class
cls_re = re.compile(r'^\s*class\s+DemoKitGUI\b.*?:\s*$', re.M)
mcls = cls_re.search(src)
if not mcls:
    print("❌ Could not find class DemoKitGUI", file=sys.stderr); sys.exit(2)

start_cls = mcls.start()
next_cls = cls_re.search(src, mcls.end())
end_cls = next_cls.start() if next_cls else len(src)
cls_block = src[start_cls:end_cls]

# Find _import_doc (fallback to a couple of variants)
mdef = re.search(r'^\s*def\s+_import_doc\s*\(', cls_block, re.M)
if not mdef:
    for alt in (r'_import_doc_clicked', r'_on_import_clicked', r'_do_import'):
        mdef = re.search(rf'^\s*def\s+{alt}\s*\(', cls_block, re.M)
        if mdef: break
if not mdef:
    print("❌ Could not find the import method (_import_doc) in DemoKitGUI", file=sys.stderr); sys.exit(3)

# Extract method block
meth_indent = re.match(r'^\s*', cls_block[mdef.start():mdef.end()]).group(0)
after = cls_block[mdef.end():]
mnext = re.search(rf'^{meth_indent}def\s+\w+\s*\(', after, re.M)
end_in = mdef.end() + (mnext.start() if mnext else len(after))
meth_block = cls_block[mdef.start():end_in]

# Find the UTF-8-or-image read block we inserted earlier (or a similar try/except)
anchor_comment = r'# Read as UTF-8 text, or fallback to data:image;base64 for images'
anchor_pos = meth_block.find(anchor_comment)
if anchor_pos == -1:
    # fall back: find the 'except UnicodeDecodeError:' handling in the method
    m_except = re.search(r'^\s*except\s+UnicodeDecodeError\s*:\s*$', meth_block, re.M)
    if not m_except:
        print("❌ Could not find read-text/bytes block to anchor insertion.", file=sys.stderr); sys.exit(4)
    anchor_line_start = m_except.start()
else:
    anchor_line_start = anchor_pos

# Compute where that try/except block ends: scan forward until dedent to meth_indent
lines = meth_block.splitlines(True)
# Determine the line index of the anchor
offset = 0
for i, ln in enumerate(lines):
    if anchor_comment in ln or re.match(r'^\s*except\s+UnicodeDecodeError\s*:\s*$', ln):
        offset = i
        break

# Scan to end of block by indentation
def indent_of(s): 
    import re
    m = re.match(r'^([ \t]*)', s); 
    return m.group(1)

base_indent = indent_of(lines[offset])
# Walk forward until we hit a line whose indent <= meth_indent (method's base indent) and is not empty/comment
end_idx = offset + 1
for j in range(offset+1, len(lines)):
    lj = lines[j]
    if lj.strip() == "" or lj.lstrip().startswith("#"):
        end_idx = j+1
        continue
    if indent_of(lj) <= meth_indent and not lj.lstrip().startswith(('try','except','finally','else')):
        end_idx = j
        break
    end_idx = j+1

insertion_indent = base_indent  # same level as the try/except block
fastpath = (
    f"{insertion_indent}# Fast-path: if we produced a data-URL image, create a doc now and return\n"
    f"{insertion_indent}if isinstance(body, str) and body.startswith('data:image/'):\n"
    f"{insertion_indent}    _doc_id = None\n"
    f"{insertion_indent}    _title = None\n"
    f"{insertion_indent}    try:\n"
    f"{insertion_indent}        from pathlib import Path as _P\n"
    f"{insertion_indent}        _title = _P(path).name\n"
    f"{insertion_indent}    except Exception:\n"
    f"{insertion_indent}        _title = 'image'\n"
    f"{insertion_indent}    # Try GUI helpers first\n"
    f"{insertion_indent}    for _name in ('create_document','new_document','add_document_here'):\n"
    f"{insertion_indent}        _fn = getattr(self, _name, None)\n"
    f"{insertion_indent}        if callable(_fn):\n"
    f"{insertion_indent}            try:\n"
    f"{insertion_indent}                _doc_id = _fn(_title, body)\n"
    f"{insertion_indent}                break\n"
    f"{insertion_indent}            except TypeError:\n"
    f"{insertion_indent}                try:\n"
    f"{insertion_indent}                    _doc_id = _fn({{'title': _title, 'body': body}})\n"
    f"{insertion_indent}                    break\n"
    f"{insertion_indent}                except Exception:\n"
    f"{insertion_indent}                    pass\n"
    f"{insertion_indent}    # Then document_store fallbacks\n"
    f"{insertion_indent}    if _doc_id is None:\n"
    f"{insertion_indent}        try:\n"
    f"{insertion_indent}            from modules import document_store as _ds\n"
    f"{insertion_indent}            for _name in ('create_document','add_document','insert_document','new_document','create','add'):\n"
    f"{insertion_indent}                _fn = getattr(_ds, _name, None)\n"
    f"{insertion_indent}                if callable(_fn):\n"
    f"{insertion_indent}                    try:\n"
    f"{insertion_indent}                        _doc_id = _fn(_title, body)\n"
    f"{insertion_indent}                        break\n"
    f"{insertion_indent}                    except TypeError:\n"
    f"{insertion_indent}                        try:\n"
    f"{insertion_indent}                            _doc_id = _fn({{'title': _title, 'body': body}})\n"
    f"{insertion_indent}                            break\n"
    f"{insertion_indent}                        except Exception:\n"
    f"{insertion_indent}                            pass\n"
    f"{insertion_indent}        except Exception:\n"
    f"{insertion_indent}            pass\n"
    f"{insertion_indent}    if _doc_id is not None:\n"
    f"{insertion_indent}        try:\n"
    f"{insertion_indent}            from tkinter import messagebox as _mb\n"
    f"{insertion_indent}            _mb.showinfo('Import', f'Document {{_doc_id}} created')\n"
    f"{insertion_indent}        except Exception:\n"
    f"{insertion_indent}            pass\n"
    f"{insertion_indent}        try:\n"
    f"{insertion_indent}            if hasattr(self, 'reload_index'): self.reload_index()\n"
    f"{insertion_indent}            _tree = getattr(self, 'tree', None)\n"
    f"{insertion_indent}            if _tree:\n"
    f"{insertion_indent}                for _it in _tree.get_children(''):\n"
    f"{insertion_indent}                    _vals = _tree.item(_it, 'values')\n"
    f"{insertion_indent}                    if _vals and str(_vals[0]) == str(_doc_id):\n"
    f"{insertion_indent}                        _tree.selection_set(_it)\n"
    f"{insertion_indent}                        _tree.see(_it)\n"
    f"{insertion_indent}                        if hasattr(self, 'open_doc_by_id'): self.open_doc_by_id(_doc_id)\n"
    f"{insertion_indent}                        break\n"
    f"{insertion_indent}        except Exception:\n"
    f"{insertion_indent}            pass\n"
    f"{insertion_indent}        return\n"
)

# Avoid duplicating if already present
if "Fast-path: if we produced a data-URL image" not in meth_block:
    meth_block = "".join(lines[:end_idx]) + fastpath + "".join(lines[end_idx:])

# Reassemble class & file
new_cls_block = cls_block[:mdef.start()] + meth_block + cls_block[end_in:]
out = src[:start_cls] + new_cls_block + src[end_cls:]

io.open(path, "w", encoding="utf-8").write(out)
print("✅ Inserted image fast-path into import method")
PY

# Syntax check; restore backup on failure
if python3 -m py_compile "$FILE" 2>/dev/null; then
  echo "✅ Patched $FILE (backup at $BACKUP)"
else
  echo "⚠️ Syntax error — restoring backup."
  mv "$BACKUP" "$FILE"
  exit 1
fi

echo "Now run:  python3 main.py  → File > Import (select a PNG/JPEG)."

