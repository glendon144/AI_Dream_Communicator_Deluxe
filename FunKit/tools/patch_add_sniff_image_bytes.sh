#!/usr/bin/env bash
set -euo pipefail

FILE="modules/gui_tkinter.py"
BACKUP="${FILE}.bak.$(date +%Y%m%d-%H%M%S)"

[[ -f "$FILE" ]] || { echo "❌ Not found: $FILE"; exit 1; }
cp -p "$FILE" "$BACKUP"

python3 - "$FILE" <<'PY'
import io, re, sys

path = sys.argv[1]
src = io.open(path, "r", encoding="utf-8", errors="surrogatepass").read()

# Find DemoKitGUI class block
cls_re = re.compile(r'^\s*class\s+DemoKitGUI\b.*?:\s*$', re.M)
m = cls_re.search(src)
if not m:
    print("❌ Could not find class DemoKitGUI", file=sys.stderr)
    sys.exit(2)

start = m.start()
next_m = cls_re.search(src, m.end())
end = next_m.start() if next_m else len(src)

cls_block = src[start:end]

# If _sniff_image_bytes already exists anywhere, no-op
if re.search(r'^\s*def\s+_sniff_image_bytes\s*\(', cls_block, re.M):
    print("ℹ️ _sniff_image_bytes already present; no changes.")
    sys.exit(0)

# Indentation
class_indent = re.match(r'^\s*', src[m.start():m.end()]).group(0)
method_indent = class_indent + "    "

method_block = (
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

# Append method at end of class block (inside class)
patched_cls = cls_block.rstrip() + "\n\n" + method_block + "\n"
patched = src[:start] + patched_cls + src[end:]

io.open(path, "w", encoding="utf-8").write(patched)
print("✅ Added _sniff_image_bytes to DemoKitGUI")
PY

# Syntax check; restore on failure
if python3 -m py_compile "$FILE" 2>/dev/null; then
  echo "✅ Patched $FILE (backup at $BACKUP)"
else
  echo "⚠️ Syntax error — restoring backup."
  mv "$BACKUP" "$FILE"
  exit 1
fi

echo "Now run:  python3 main.py  → import a PNG/JPEG via your usual Import menu."

