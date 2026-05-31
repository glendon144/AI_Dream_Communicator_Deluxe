#!/usr/bin/env bash
set -euo pipefail

ENG="modules/aopml_engine.py"
[ -f "$ENG" ] || { ENG="modules/aopmlengine.py"; }
[ -f "$ENG" ] || { echo "❌ Engine not found"; exit 1; }

ts=$(date +%Y%m%d-%H%M%S)
bak="$ENG.bak.$ts"
cp -p "$ENG" "$bak"

tmp="$ENG.tmp.$ts"

python3 - "$ENG" "$tmp" <<'PY'
import re, sys, io
src_path, out_path = sys.argv[1], sys.argv[2]
s = open(src_path, encoding="utf-8", errors="ignore").read()

# 1) Force all __init__ annotations to -> None
s = re.sub(r"(def\s+__init__\s*\([^)]*\)\s*->\s*[^\:]+:)",
           lambda m: re.sub(r"->\s*[^\:]+:", "-> None:", m.group(1)),
           s)

# 2) Remove any `return ...` inside an __init__ body
def strip_returns_in_init(text):
    out = []
    i = 0
    while True:
        m = re.search(r"^def\s+__init__\s*\([^)]*\):", text[i:], flags=re.M)
        if not m:
            out.append(text[i:])
            break
        j = i + m.start()
        k = i + m.end()
        # find end of this block (next def/class at same or less indent)
        # get indent of this def
        line_start = text.rfind("\n", 0, j) + 1
        indent = len(text[line_start:j]) - len(text[line_start:j].lstrip())
        block_pat = re.compile(rf"^(?:(?P<nl>\n)|(?P<line>[^\n]*\n))", re.M)
        pos = k
        while True:
            m2 = re.search(r"^(def\s+|class\s+)", text[pos:], flags=re.M)
            if not m2:
                block_end = len(text)
                break
            cand = pos + m2.start()
            # compute indent of candidate
            ls = text.rfind("\n", 0, cand) + 1
            ind = len(text[ls:cand]) - len(text[ls:cand].lstrip())
            if ind <= indent:
                block_end = cand
                break
            pos = cand + 1
        block = text[k:block_end]
        # remove any "return ..." lines in the block
        block = re.sub(r"^\s*return\b[^\n]*\n", "", block, flags=re.M)
        out.append(text[i:k])
        out.append(block)
        i = block_end
    return "".join(out)

s = strip_returns_in_init(s)

open(out_path, "w", encoding="utf-8").write(s)
PY

# 3) Compile check; revert on failure
if ! python3 -m py_compile "$tmp" 2>/dev/null; then
  echo "❌ Compile failed; keeping original. See backup: $bak"
  rm -f "$tmp"
  exit 1
fi

mv "$tmp" "$ENG"
echo "✅ Fixed __init__ annotations/returns. Backup at: $bak"

