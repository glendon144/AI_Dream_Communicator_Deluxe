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

# 1) Locate DemoKitGUI class block
cls_re = re.compile(r'^\s*class\s+DemoKitGUI\b.*?:\s*$', re.M)
mcls = cls_re.search(src)
if not mcls:
    print("❌ Could not find class DemoKitGUI", file=sys.stderr); sys.exit(2)

start_cls = mcls.start()
next_cls = cls_re.search(src, mcls.end())
end_cls = next_cls.start() if next_cls else len(src)

cls_block = src[start_cls:end_cls]
class_indent = re.match(r'^\s*', src[mcls.start():mcls.end()]).group(0)
method_indent = class_indent + "    "

# 2) Remove any existing _sniff_image_bytes *inside* DemoKitGUI (to avoid duplication)
def_pat = re.compile(rf'^{method_indent}def\s+_sniff_image_bytes\s*\(self[^\)]*\)\s*:\s*$', re.M)
m = def_pat.search(cls_block)
if m:
    # find end of this method: next def at same indent or end of class
    after = cls_block[m.end():]
    mnext = re.search(rf'^{method_indent}def\s+\w+\s*\(', after, re.M)
    end_m = m.end() + (mnext.start() if mnext else len(after))
    cls_block = cls_block[:m.start()] + cls_block[end_m:]

# 3) Append a correct, safely-indented method inside the class
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

if not cls_block.endswith("\n"):
    cls_block += "\n"
cls_block = cls_block + "\n" + method_block + "\n"

# 4) Reassemble file
out = src[:start_cls] + cls_block + src[end_cls:]
io.open(path, "w", encoding="utf-8").write(out)
print("✅ Ensured _sniff_image_bytes is a DemoKitGUI method (properly indented)")
PY

# Syntax check; restore on failure
if python3 -m py_compile "$FILE" 2>/dev/null; then
  echo "✅ Patched $FILE (backup at $BACKUP)"
else
  echo "⚠️ Syntax error — restoring backup."
  mv "$BACKUP" "$FILE"
  exit 1
fi

echo "Now run:  python3 main.py  → File > Import (pick a PNG/JPEG)."

