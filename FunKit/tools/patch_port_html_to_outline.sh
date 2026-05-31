#!/usr/bin/env bash
set -euo pipefail

OLD="3125/PiKit/modules/aopml_engine.py"   # path to your 8/31 PiKit engine
NEW="modules/aopml_engine.py"              # FunKit engine

[ -f "$OLD" ] || { echo "❌ Old engine not found at $OLD"; exit 1; }
[ -f "$NEW" ] || { echo "❌ New engine not found at $NEW"; exit 1; }

ts=$(date +%Y%m%d-%H%M%S)
cp -p "$NEW" "$NEW.bak.$ts"

python3 - "$OLD" "$NEW" <<'PY'
import sys, re
old_path, new_path = sys.argv[1], sys.argv[2]
old = open(old_path,encoding='utf-8').read()
new = open(new_path,encoding='utf-8').read()

def extract_def(src, name):
    pat = re.compile(rf"(^def\s+{name}\s*\(.*?\):[\s\S]*?)(?=^\S|\Z)", re.M)
    m = pat.search(src)
    return m.group(1).rstrip() if m else None

needed = ["html_to_outline","normalize_links","split_paragraphs","bulletize_lines"]

inserted = []
for fn in needed:
    if fn not in new:
        body = extract_def(old, fn)
        if body:
            new += f"\n\n# ==== ported from PiKit 2025-08-31 ====\n{body}\n"
            inserted.append(fn)

open(new_path,"w",encoding="utf-8").write(new)
print("Inserted:", inserted if inserted else "(all already present)")
PY

