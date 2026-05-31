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

# Locate class DemoKitGUI and its __init__.
cls_re = re.compile(r'^\s*class\s+DemoKitGUI\b.*?:\s*$', re.M)
m_cls = cls_re.search(src)
if not m_cls:
    print("❌ Could not find class DemoKitGUI", file=sys.stderr)
    sys.exit(2)

start_cls = m_cls.start()
next_cls = cls_re.search(src, m_cls.end())
end_cls = next_cls.start() if next_cls else len(src)

cls_block = src[start_cls:end_cls]

# Find __init__ signature
init_re = re.compile(r'^(\s*)def\s+__init__\s*\(\s*self\s*(?:,\s*[^)]*)?\)\s*:\s*$', re.M)
m_init = init_re.search(cls_block)
if not m_init:
    print("❌ Could not find DemoKitGUI.__init__", file=sys.stderr)
    sys.exit(3)

indent = m_init.group(1)
init_start = m_init.start()

# Get the body of __init__ until next def at same indent or end of class.
after = cls_block[m_init.end():]
next_def = re.search(rf'^{indent}def\s+\w+\s*\(', after, re.M)
init_end_in_class = m_init.end() + (next_def.start() if next_def else len(after))
init_block = cls_block[m_init.start():init_end_in_class]

# 1) Ensure Tk is initialized with no args: replace lines calling tk.Tk.__init__ or super().__init__ with args.
init_block = re.sub(
    rf'^{indent}\s*(tk\.)?Tk\.__init__\s*\([^)]+\)\s*$',
    f'{indent}tk.Tk.__init__(self)',
    init_block,
    flags=re.M
)
init_block = re.sub(
    rf'^{indent}\s*super\(\s*__class__\s*,\s*self\s*\)\.__init__\s*\([^)]+\)\s*$',
    f'{indent}super().__init__()',
    init_block,
    flags=re.M
)
init_block = re.sub(
    rf'^{indent}\s*super\(\s*\)\.__init__\s*\([^)]+\)\s*$',
    f'{indent}super().__init__()',
    init_block,
    flags=re.M
)

# If there is no explicit Tk init at all, add one at top of __init__.
if not re.search(rf'^{indent}(?:tk\.Tk\.__init__|super\(\)\.__init__|super\(__class__,\s*self\)\.__init__)\s*\(\s*self?\s*\)\s*$', init_block, re.M):
    # put right after the def line
    lines = init_block.splitlines(True)
    for i, ln in enumerate(lines):
        if i == 0:  # def line
            continue
        # insert after first real line or docstring line
        insert_at = 1
        break
    else:
        insert_at = 1
    lines.insert(insert_at, f"{indent}super().__init__()\n")
    init_block = "".join(lines)

# 2) Ensure we store doc_store and processor on self.
if not re.search(rf'^{indent}self\.doc_store\s*=\s*doc_store\b', init_block, re.M):
    # add after Tk init
    init_block = re.sub(
        rf'^{indent}(?:tk\.Tk\.__init__\s*\(\s*self\s*\)|super\(\)\.__init__\s*\(\s*\))\s*$',
        lambda m: m.group(0) + f"\n{indent}self.doc_store = doc_store",
        init_block,
        count=1,
        flags=re.M
    )
if not re.search(rf'^{indent}self\.processor\s*=\s*processor\b', init_block, re.M):
    # add after doc_store (or after Tk init if doc_store not present)
    if re.search(rf'^{indent}self\.doc_store\s*=\s*doc_store\b', init_block, re.M):
        init_block = re.sub(
            rf'^{indent}self\.doc_store\s*=\s*doc_store\b\s*$',
            lambda m: m.group(0) + f"\n{indent}self.processor = processor",
            init_block,
            count=1,
            flags=re.M
        )
    else:
        init_block = re.sub(
            rf'^{indent}(?:tk\.Tk\.__init__\s*\(\s*self\s*\)|super\(\)\.__init__\s*\(\s*\))\s*$',
            lambda m: m.group(0) + f"\n{indent}self.processor = processor",
            init_block,
            count=1,
            flags=re.M
        )

# Reassemble class block and file
patched_cls_block = cls_block[:m_init.start()] + init_block + cls_block[init_end_in_class:]
patched = src[:start_cls] + patched_cls_block + src[end_cls:]

io.open(path, "w", encoding="utf-8").write(patched)
print("OK")
PY

# Syntax check
if python3 -m py_compile "$FILE" 2>/dev/null; then
  echo "✅ Patched $FILE (backup at $BACKUP)"
else
  echo "⚠️  Syntax check failed — restoring backup."
  mv "$BACKUP" "$FILE"
  exit 1
fi

echo "Now run:  python3 main.py"

