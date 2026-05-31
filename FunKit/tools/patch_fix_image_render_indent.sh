#!/usr/bin/env bash
set -euo pipefail

FILE="modules/image_render.py"
BACKUP="${FILE}.bak.$(date +%Y%m%d-%H%M%S)"

[[ -f "$FILE" ]] || { echo "❌ Not found: $FILE"; exit 1; }
cp -p "$FILE" "$BACKUP"

python3 - "$FILE" <<'PY'
import io, sys

p = sys.argv[1]
lines = io.open(p, "r", encoding="utf-8", errors="surrogatepass").read().splitlines(True)

# Fix the specific pattern:
# try:
# from PIL import Image, ImageTk # pillow
# except Exception as e:
# raise RuntimeError("Pillow is required: pip install pillow") from e
for i in range(len(lines)-1):
    if lines[i].strip() == "try:" and lines[i+1].lstrip().startswith("from PIL import Image, ImageTk"):
        # indent the import under try
        lines[i+1] = "    " + lines[i+1].lstrip()
        # find the 'except' directly after (skipping blanks/comments)
        j = i+2
        while j < len(lines) and (lines[j].strip() == "" or lines[j].lstrip().startswith("#")):
            j += 1
        if j < len(lines) and lines[j].lstrip().startswith("except"):
            # indent the 'raise' line right after except (skipping blanks/comments)
            k = j+1
            while k < len(lines) and (lines[k].strip() == "" or lines[k].lstrip().startswith("#")):
                k += 1
            if k < len(lines) and lines[k].lstrip().startswith("raise RuntimeError"):
                lines[k] = "    " + lines[k].lstrip()
        break

io.open(p, "w", encoding="utf-8").write("".join(lines))
PY

# Syntax check both files we just touched earlier
python3 -m py_compile modules/image_render.py
python3 -m py_compile modules/gui_tkinter.py 2>/dev/null || true

echo "✅ Fixed indentation in modules/image_render.py (backup at $BACKUP)"
echo "Now try:  python3 main.py"

