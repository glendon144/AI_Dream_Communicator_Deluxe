#!/usr/bin/env bash
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "Usage: $0 /path/to/OLD/modules/aopml_engine.py /path/to/NEW/modules/aopml_engine.py"
  echo "Example:"
  echo "  $0 ../../083125/PiKit/modules/aopml_engine.py modules/aopml_engine.py"
  exit 1
fi

OLD="$1"
NEW="$2"

[ -f "$OLD" ] || { echo "❌ Old engine not found at $OLD"; exit 1; }
[ -f "$NEW" ] || { echo "❌ New engine not found at $NEW"; exit 1; }

ts=$(date +%Y%m%d-%H%M%S)
cp -p "$NEW" "$NEW.bak.$ts"

python3 - "$OLD" "$NEW" <<'PY'
import sys, re
old_path, new_path = sys.argv[1], sys.argv[2]
old = open(old_path,encoding='utf-8',errors='ignore').read()
new = open(new_path,encoding='utf-8',errors='ignore').read()

def has_def(src, name):
    return re.search(rf"\bdef\s+{re.escape(name)}\s*\(", src) is not None

def extract_def(src, name):
    pat = re.compile(rf"(^def\s+{re.escape(name)}\s*\(.*?\):[\s\S]*?)(?=^\S|\Z)", re.M)
    m = pat.search(src)
    return m.group(1).rstrip() if m else None

# Helpers we know url→OPML chain can require
NEEDED = [
    "html_to_outline",
    "normalize_links",
    "split_paragraphs",
    "bulletize_lines",
    # bonus: if build_opml_from_text calls these
    "text_to_outline",
]

inserted = []
for fn in NEEDED:
    if not has_def(new, fn):
        body = extract_def(old, fn)
        if body:
            new += f"\n\n# ==== ported from PiKit (2025-08-31) ====\n{body}\n"
            inserted.append(fn)

open(new_path,"w",encoding='utf-8').write(new)
print("Inserted:", inserted if inserted else "(nothing; already present)")
PY

echo "✅ Port complete. Backup at: $NEW.bak.$ts"

