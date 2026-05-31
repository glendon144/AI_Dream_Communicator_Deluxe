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

# Locate DemoKitGUI class
cls_re = re.compile(r'^\s*class\s+DemoKitGUI\b.*?:\s*$', re.M)
m_cls = cls_re.search(src)
if not m_cls:
    print("❌ Could not find class DemoKitGUI", file=sys.stderr)
    sys.exit(2)

start_cls = m_cls.start()
next_cls = cls_re.search(src, m_cls.end())
end_cls = next_cls.start() if next_cls else len(src)
cls_block = src[start_cls:end_cls]

# Find __init__
init_re = re.compile(r'^(\s*)def\s+__init__\s*\([^)]*\)\s*:\s*$', re.M)
m_init = init_re.search(cls_block)
if not m_init:
    print("❌ Could not find DemoKitGUI.__init__", file=sys.stderr)
    sys.exit(3)

indent = m_init.group(1)
init_start = m_init.start()

# Find end of __init__ block (next def at same indent or end of class)
after = cls_block[m_init.end():]
next_def = re.search(rf'^{indent}def\s+\w+\s*\(', after, re.M)
init_end_in_class = m_init.end() + (next_def.start() if next_def else len(after))
init_block = cls_block[m_init.start():init_end_in_class]

# 1) Force a safe signature
init_block = re.sub(
    rf'^{indent}def\s+__init__\s*\([^)]*\)\s*:\s*$',
    f'{indent}def __init__(self, doc_store=None, processor=None, **kwargs):',
    init_block,
    count=1,
    flags=re.M
)

# 2) Ensure Tk init does not forward positional args
# Replace tk.Tk.__init__(self, *args, **kwargs) and variants → tk.Tk.__init__(self)
init_block = re.sub(
    rf'^{indent}\s*(?:tk\.)?Tk\.__init__\s*\([^)]+\)\s*$',
    f'{indent}tk.Tk.__init__(self)',
    init_block,
    flags=re.M
)
# Replace super(...).__init__(...) → super().__init__()
init_block = re.sub(
    rf'^{indent}\s*super\([^)]*\)\.__init__\s*\([^)]+\)\s*$',
    f'{indent}super().__init__()',
    init_block,
    flags=re.M
)

# 3) If no explicit Tk init remains, inject one after def line
if not re.search(rf'^{indent}(?:tk\.Tk\.__init__|super\(\)\.__init__)\s*\(\s*self?\s*\)\s*$', init_block, re.M):
    lines = init_block.splitlines(True)
    # Insert after def line
    for i, ln in enumerate(lines):
        if i == 0:
            continue
        lines.insert(1, f"{indent}super().__init__()\n")
        break
    init_block = "".join(lines)

# 4) Ensure we store doc_store & processor
if not re.search(rf'^{indent}self\.doc_store\s*=\s*doc_store\b', init_block, re.M):
    init_block = init_block.replace(
        f"{indent}super().__init__()\n",
        f"{indent}super().__init__()\n{indent}self.doc_store = doc_store\n",
        1
    )
if not re.search(rf'^{indent}self\.processor\s*=\s*processor\b', init_block, re.M):
    if re.search(rf'^{indent}self\.doc_store\s*=\s*doc_store\b', init_block, re.M):
        init_block = init_block.replace(
            f"{indent}self.doc_store = doc_store\n",
            f"{indent}self.doc_store = doc_store\n{indent}self.processor = processor\n",
            1
        )
    else:
        init_block = init_block.replace(
            f"{indent}super().__init__()\n",
            f"{indent}super().__init__()\n{indent}self.processor = processor\n",
            1
        )

# 5) Also sanitize any later stray calls to Tk init within __init__ (paranoia)
init_block = re.sub(
    r'\bTk\.__init__\s*\([^)]+\)',
    'Tk.__init__(self)',
    init_block
)
init_block = re.sub(
    r'super\([^)]*\)\.__init__\s*\([^)]+\)',
    'super().__init__()',
    init_block
)

# Reassemble
patched_cls_block = cls_block[:m_init.start()] + init_block + cls_block[init_end_in_class:]
patched = src[:start_cls] + patched_cls_block + src[end_cls:]
io.open(path, "w", encoding="utf-8").write(patched)
print("OK")
PY

# Syntax check; restore on failure
if python3 -m py_compile "$FILE" 2>/dev/null; then
  echo "✅ Patched $FILE (backup at $BACKUP)"
else
  echo "⚠️  Syntax check failed — restoring backup."
  mv "$BACKUP" "$FILE"
  exit 1
fi

echo "Now run: python3 main.py"

