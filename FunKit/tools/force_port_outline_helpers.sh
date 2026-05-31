#!/usr/bin/env bash
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "Usage: $0 /path/to/OLD/aopml_engine.py /path/to/NEW/aopml_engine.py"
  echo "Example:"
  echo "  $0 ../../083125/PiKit/modules/aopml_engine.py modules/aopml_engine.py"
  exit 1
fi

OLD="$1"
NEW="$2"
[ -f "$OLD" ] || { echo "❌ Old engine not found: $OLD"; exit 1; }
[ -f "$NEW" ] || { echo "❌ New engine not found: $NEW"; exit 1; }

ts=$(date +%Y%m%d-%H%M%S)
cp -p "$NEW" "$NEW.bak.$ts"

python3 - "$OLD" "$NEW" <<'PY'
import sys, re
old_path, new_path = sys.argv[1], sys.argv[2]
old = open(old_path,encoding='utf-8',errors='ignore').read()
new = open(new_path,encoding='utf-8',errors='ignore').read()

def grab_def(src, name):
    pat = re.compile(rf"(^def\s+{re.escape(name)}\s*\(.*?\):\s*[\s\S]*?)(?=^\S|^# ====|^@dataclass|^class\s|\Z)", re.M)
    m = pat.search(src);  return m.group(1).rstrip() if m else None

def replace_def(dst, name, body):
    pat = re.compile(rf"(^def\s+{re.escape(name)}\s*\(.*?\):\s*[\s\S]*?)(?=^\S|^# ====|^@dataclass|^class\s|\Z)", re.M)
    if pat.search(dst):
        dst = pat.sub(body+"\n", dst, count=1)
    else:
        dst += "\n\n# ==== ported from PiKit 2025-08-31 ====\n" + body + "\n"
    return dst

NEEDED = [
  "html_to_outline",
  "normalize_links",
  "split_paragraphs",
  "bulletize_lines",
  "text_to_outline",
]

missing = []
for fn in NEEDED:
    body = grab_def(old, fn)
    if not body:
        missing.append(fn); continue
    new = replace_def(new, fn, "# ---- PORTED: "+fn+"\n"+body)

# Add an alias just in case build_opml_from_html calls a variant:
if "def html_to_outline(" not in new:
    # try to alias to any variant we just copied
    for alt in ("html_to_outline_v2","html_to_outline2","_html_to_outline"):
        if re.search(rf"\bdef\s+{alt}\s*\(", new):
            new += f"\n\ndef html_to_outline(*a, **k):\n    return {alt}(*a, **k)\n"
            break

# Ensure no Unicode arrow in headers (from earlier)
new = new.replace("URL→OPML", "URL->OPML")

open(new_path,"w",encoding='utf-8').write(new)
print("Replaced/ensured helpers. Missing in OLD (if any):", missing)
PY

echo "✅ Forced helper port complete. Backup at: $NEW.bak.$ts"

