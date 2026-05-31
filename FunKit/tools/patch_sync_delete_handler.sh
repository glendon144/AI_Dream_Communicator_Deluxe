#!/usr/bin/env bash
set -euo pipefail

SRC="modules/gui_tkinter_61k_works.py"   # known-good source
DST="modules/gui_tkinter.py"             # target in use
BACKUP="${DST}.bak.$(date +%Y%m%d-%H%M%S)"

if [[ ! -f "$SRC" ]]; then
  echo "❌ Missing reference source: $SRC"
  exit 1
fi
if [[ ! -f "$DST" ]]; then
  echo "❌ Missing target file: $DST"
  exit 1
fi

cp -p "$DST" "$BACKUP"

python3 - <<'PY' "$SRC" "$DST"
import io, re, sys
src_path, dst_path = sys.argv[1], sys.argv[2]

def read(p):
    return io.open(p, "r", encoding="utf-8", errors="surrogatepass").read()

def write(p, s):
    io.open(p, "w", encoding="utf-8").write(s)

src = read(src_path)
dst = read(dst_path)

# Extract DemoKitGUI._on_delete_clicked from SRC (exact method, with indentation)
cls_pat = re.compile(r'^\s*class\s+DemoKitGUI\b.*?:\s*$', re.M)
mcls = cls_pat.search(src)
if not mcls:
    print("❌ Could not find class DemoKitGUI in source.", file=sys.stderr)
    sys.exit(2)

# Find class block in SRC (from class line to next top-level class/EOF)
next_cls = cls_pat.search(src, mcls.end())
src_cls_block = src[mcls.start(): next_cls.start() if next_cls else len(src)]

# Find method in the class block (start at its def line; end before next def at same indent)
mdef = re.search(r'^(\s*)def\s+_on_delete_clicked\s*\(self[^\)]*\)\s*:\s*$', src_cls_block, re.M)
if not mdef:
    print("❌ Could not find _on_delete_clicked(self) in source class.", file=sys.stderr)
    sys.exit(3)
indent = mdef.group(1)
# method ends when we hit a line that starts with the same indent followed by 'def ' or end of class block
mnext = re.search(rf'^{indent}def\s+\w+\s*\(', src_cls_block[mdef.end():], re.M)
src_method_block = src_cls_block[mdef.start(): mdef.end() + (mnext.start() if mnext else len(src_cls_block[mdef.end():]))]

# In DST, locate class DemoKitGUI
mdst_cls = cls_pat.search(dst)
if not mdst_cls:
    print("❌ Could not find class DemoKitGUI in target.", file=sys.stderr)
    sys.exit(4)
next_dst_cls = cls_pat.search(dst, mdst_cls.end())
dst_prefix = dst[:mdst_cls.start()]
dst_cls_block = dst[mdst_cls.start(): next_dst_cls.start() if next_dst_cls else len(dst)]
dst_suffix = dst[next_dst_cls.start():] if next_dst_cls else ""

# Remove existing _on_delete_clicked (any variant) in DST class block, if present
mdst_def = re.search(r'^(\s*)def\s+_on_delete_clicked\s*\(self[^\)]*\)\s*:\s*$', dst_cls_block, re.M)
if mdst_def:
    d_indent = mdst_def.group(1)
    mdst_next = re.search(rf'^{d_indent}def\s+\w+\s*\(', dst_cls_block[mdst_def.end():], re.M)
    dst_cls_block = dst_cls_block[:mdst_def.start()] + dst_cls_block[mdst_def.end() + (mdst_next.start() if mdst_next else len(dst_cls_block[mdst_def.end():])):]

# Insert source method right after the class line (or at end of class)
insert_at = dst_cls_block.find('\n', dst_cls_block.find('class DemoKitGUI'))
if insert_at == -1:
    insert_at = len(dst_cls_block)
# Ensure a blank line before insert
insertion = "\n" + src_method_block.strip("\n") + "\n"
dst_cls_block = dst_cls_block[:insert_at+1] + insertion + dst_cls_block[insert_at+1:]

patched = dst_prefix + dst_cls_block + dst_suffix
write(dst_path, patched)
print("OK")
PY

# Verify syntax; restore on failure
if python3 -m py_compile "$DST" 2>/dev/null; then
  echo "✅ Synced _on_delete_clicked from $SRC into $DST (backup at $BACKUP)"
else
  echo "⚠️  Syntax error after patch. Restoring backup."
  mv "$BACKUP" "$DST"
  exit 1
fi

