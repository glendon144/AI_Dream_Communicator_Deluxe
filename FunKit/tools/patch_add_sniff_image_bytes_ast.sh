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

# Parse once, get precise class boundaries (using end_lineno from 3.8+)
tree = ast.parse(src)

demo_cls = None
for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name == "DemoKitGUI":
        demo_cls = node
        break

if demo_cls is None:
    print("❌ Could not find class DemoKitGUI", file=sys.stderr)
    sys.exit(2)

# Check if method already exists (maybe defined but mis-indented earlier)
for node in demo_cls.body:
    if isinstance(node, ast.FunctionDef) and node.name == "_sniff_image_bytes":
        print("ℹ️ _sniff_image_bytes already present inside DemoKitGUI; no changes.")
        sys.exit(0)

# Determine insertion point and indentation
class_header_line = lines[demo_cls.lineno - 1]
class_indent = re.match(r'[ \t]*', class_header_line).group(0)
method_indent = class_indent + ("    " if "\t" not in class_indent else "\t")

insert_line = (demo_cls.end_lineno or demo_cls.lineno) - 1  # 0-based index of last class line
# Ensure we insert *before* the class closing dedent: end_lineno points to last line of class block.

# Build method text with exact indent
method_text = (
    f"{method_indent}def _sniff_image_bytes(self, b):\n"
    f"{method_indent}    \"\"\"Return image MIME type if bytes match a known format, else None.\"\"\"\n"
    f"{method_indent}    if not isinstance(b, (bytes, bytearray)):\n"
    f"{method_indent}        return None\n"
    f"{method_indent}    hdr = bytes(b[:12])\n"
    f"{method_indent}    if hdr.startswith(b\"\\x89PNG\\r\\n\\x1a\\n\"): return \"image/png\"\n"
    f"{method_indent}    if hdr.startswith(b\"\\xff\\xd8\"): return \"image/jpeg\"\n"
    f"{method_indent}    if hdr.startswith(b\"GIF87a\") or hdr.startswith(b\"GIF89a\"): return \"image/gif\"\n"
    f"{method_indent}    if hdr.startswith(b\"BM\"): return \"image/bmp\"\n"
    f"{method_indent}    if len(hdr) >= 12 and hdr[0:4] == b\"RIFF\" and hdr[8:12] == b\"WEBP\": return \"image/webp\"\n"
    f"{method_indent}    return None\n"
)

# Insert a blank line before method if last class line isn't already blank/indented content
prepend = "" if lines[insert_line].strip() == "" else "\n"
lines.insert(insert_line + 1, prepend + method_text + "\n")

# Ensure imports exist (idempotent): base64/mimetypes are used elsewhere in your image path
text = "".join(lines)
if re.search(r'^\s*import\s+base64\b', text, re.M) is None:
    # insert after first import-like line
    m = re.search(r'^(?:from\s+\S+\s+import\s+.*|import\s+.*)$', text, re.M)
    pos = m.end() if m else 0
    text = text[:pos] + "\nimport base64\n" + text[pos:]
if re.search(r'^\s*import\s+mimetypes\b', text, re.M) is None:
    m = re.search(r'^(?:from\s+\S+\s+import\s+.*|import\s+.*)$', text, re.M)
    pos = m.end() if m else 0
    text = text[:pos] + "\nimport mimetypes\n" + text[pos:]

io.open(path, "w", encoding="utf-8").write(text)
print("✅ Inserted _sniff_image_bytes inside DemoKitGUI (AST-based)")
PY

# Syntax check; restore on failure
if python3 -m py_compile "$FILE" 2>/dev/null; then
  echo "✅ Patched $FILE (backup at $BACKUP)"
else
  echo "⚠️ Syntax error — restoring backup."
  mv "$BACKUP" "$FILE"
  exit 1
fi

echo "Now run: python3 main.py → File > Import (PNG/JPEG)."

