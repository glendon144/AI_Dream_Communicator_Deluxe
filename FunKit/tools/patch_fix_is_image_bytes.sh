#!/usr/bin/env bash
set -euo pipefail

FILE="modules/gui_tkinter.py"
BACKUP="${FILE}.bak.$(date +%Y%m%d-%H%M%S)"

if [[ ! -f "$FILE" ]]; then
  echo "❌ Not found: $FILE"
  exit 1
fi

cp -p "$FILE" "$BACKUP"

python3 - "$FILE" <<'PY'
import io, os, re, sys

path = sys.argv[1]
with io.open(path, "r", encoding="utf-8", errors="surrogatepass") as f:
    lines = f.readlines()

src = "".join(lines)

# 1) Replace any malformed or existing _is_image_bytes def block.
# We look for ANY line beginning with `def _is_image_bytes` (even malformed),
# then replace that whole block until the next def/class at col 0 or a dedent.
pat_header = re.compile(r'^(\s*)def\s+_is_image_bytes\b[^\n]*$', re.M)

def_body = (
    "{indent}def _is_image_bytes(self, b: bytes) -> bool:\n"
    "{indent}    \"\"\"Heuristically detect image bytes by magic signatures (PNG/JPEG/GIF/BMP/WEBP).\"\"\"\n"
    "{indent}    if not isinstance(b, (bytes, bytearray)):\n"
    "{indent}        return False\n"
    "{indent}    hdr = bytes(b[0:12])\n"
    "{indent}    return (\n"
    "{indent}        hdr.startswith(b\"\\x89PNG\\r\\n\\x1a\\n\")            # PNG\n"
    "{indent}        or hdr.startswith(b\"\\xff\\xd8\")                     # JPEG\n"
    "{indent}        or hdr.startswith(b\"GIF87a\") or hdr.startswith(b\"GIF89a\")  # GIF\n"
    "{indent}        or hdr.startswith(b\"BM\")                            # BMP\n"
    "{indent}        or (len(hdr) >= 12 and hdr[0:4] == b\"RIFF\" and hdr[8:12] == b\"WEBP\")  # WEBP\n"
    "{indent}    )\n"
)

m = pat_header.search(src)
replaced = False

if m:
    indent = m.group(1)
    start = m.start()

    # find end of the block: next top-level def/class or EOF
    pat_block_end = re.compile(r'^(def|class)\s+', re.M)
    m2 = pat_block_end.search(src, m.end())
    end = m2.start() if m2 else len(src)

    # If lines after header are indented, we’re safe. If malformed (no colon),
    # we still replace generously up to next def/class.
    new_block = def_body.format(indent=indent)
    src = src[:start] + new_block + src[end:]
    replaced = True

# 2) If the function was not found at all, inject it after the last import line.
if not replaced:
    import_pat = re.compile(r'^(?:from|import)\s.+$', re.M)
    last_import = None
    for im in import_pat.finditer(src):
        last_import = im
    inject_at = last_import.end() if last_import else 0
    insertion = "\n# --- image helpers (injected) ----------------------------------------\n" + def_body.format(indent="")
    src = src[:inject_at] + insertion + src[inject_at:]

with io.open(path, "w", encoding="utf-8") as f:
    f.write(src)

PY

# Syntax check; on failure restore backup
if python3 -m py_compile "$FILE" 2>/dev/null; then
  echo "✅ Patched $FILE (backup at $BACKUP)"
else
  echo "⚠️  Python syntax check failed. Restoring backup."
  mv "$BACKUP" "$FILE"
  exit 1
fi

