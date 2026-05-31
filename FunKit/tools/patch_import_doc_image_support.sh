#!/usr/bin/env bash
set -euo pipefail

FILE="modules/gui_tkinter.py"
BACKUP="${FILE}.bak.$(date +%Y%m%d-%H%M%S)"

[[ -f "$FILE" ]] || { echo "❌ Not found: $FILE"; exit 1; }
cp -p "$FILE" "$BACKUP"

python3 - "$FILE" <<'PY'
import io, re, sys, textwrap

path = sys.argv[1]
src = io.open(path, "r", encoding="utf-8", errors="surrogatepass").read()
orig = src

# --- Ensure `import base64` and `import mimetypes` exist (idempotent)
def ensure_import(modname):
    global src
    if re.search(rf'^\s*import\s+{re.escape(modname)}\b', src, re.M) is None:
        # insert after the first import block
        m = re.search(r'^(?:from\s+\S+\s+import\s+.*|import\s+.*)(\r?\n)+', src, re.M)
        pos = m.end() if m else 0
        src = src[:pos] + f"import {modname}\n" + src[pos:]

ensure_import("base64")
ensure_import("mimetypes")

# --- Find class DemoKitGUI
cls_re = re.compile(r'^\s*class\s+DemoKitGUI\b.*?:\s*$', re.M)
mcls = cls_re.search(src)
if not mcls:
    print("❌ Could not find class DemoKitGUI", file=sys.stderr); sys.exit(2)

start_cls = mcls.start()
next_cls = cls_re.search(src, mcls.end())
end_cls = next_cls.start() if next_cls else len(src)
cls_block = src[start_cls:end_cls]

cls_indent = re.match(r'^\s*', src[mcls.start():mcls.end()]).group(0)
method_indent = cls_indent + "    "

# --- Add a tiny image sniffer helper inside DemoKitGUI if missing (idempotent)
if re.search(r'^\s*def\s+_sniff_image_bytes\s*\(self,\s*b:\s*bytes\)\s*:', cls_block, re.M) is None:
    helper = textwrap.dedent(f"""
    {method_indent}def _sniff_image_bytes(self, b: bytes) -> str | None:
    {method_indent}    if b.startswith(b"\\x89PNG\\r\\n\\x1a\\n"): return "image/png"
    {method_indent}    if b.startswith(b"\\xff\\xd8"): return "image/jpeg"
    {method_indent}    if b.startswith(b"GIF87a") or b.startswith(b"GIF89a"): return "image/gif"
    {method_indent}    if b.startswith(b"BM"): return "image/bmp"
    {method_indent}    if len(b) >= 12 and b[0:4] == b"RIFF" and b[8:12] == b"WEBP": return "image/webp"
    {method_indent}    return None
    """).lstrip("\n")
    cls_block = cls_block.rstrip() + "\n\n" + helper

# --- Locate _import_doc method
def_re = re.compile(r'^\s*def\s+_import_doc\s*\(', re.M)
mdef = def_re.search(cls_block)
if not mdef:
    # Some builds might name it _import_doc_clicked or similar; try a few alternates just in case.
    for alt in (r'_import_doc_clicked', r'_on_import_clicked', r'_do_import'):
        mdef = re.search(rf'^\s*def\s+{alt}\s*\(', cls_block, re.M)
        if mdef: break
if not mdef:
    print("❌ Could not find the import method (_import_doc) in DemoKitGUI", file=sys.stderr); sys.exit(3)

# Compute method block range (until next def at same indent)
meth_indent = re.match(r'^\s*', cls_block[mdef.start():mdef.end()]).group(0)
after = cls_block[mdef.end():]
mnext = re.search(rf'^{meth_indent}def\s+\w+\s*\(', after, re.M)
end_in = mdef.end() + (mnext.start() if mnext else len(after))
meth_block = cls_block[mdef.start():end_in]

# --- Replace `body = Path(path).read_text(encoding="utf-8")` with UTF-8-or-image logic
# Find the first assignment to `body` using read_text on Path(path)
pat = re.compile(r'^([ \t]*)body\s*=\s*Path\(\s*path\s*\)\.read_text\(\s*encoding\s*=\s*["\']utf-8["\']\s*\)\s*$', re.M)
mline = pat.search(meth_block)
if not mline:
    # Be a bit more lenient: any read_text with utf-8 on a variable named `path`
    pat = re.compile(r'^([ \t]*)body\s*=\s*Path\(\s*path\s*\)\.read_text\([^\)]*utf-8[^\)]*\)\s*$', re.M)
    mline = pat.search(meth_block)
if not mline:
    print("❌ Could not find the read_text assignment to 'body' inside import method.", file=sys.stderr); sys.exit(4)

base_indent = mline.group(1)
replacement = (
    f"{base_indent}# Read as UTF-8 text, or fallback to data:image;base64 for images\n"
    f"{base_indent}try:\n"
    f"{base_indent}    body = Path(path).read_text(encoding=\"utf-8\")\n"
    f"{base_indent}except UnicodeDecodeError:\n"
    f"{base_indent}    b = Path(path).read_bytes()\n"
    f"{base_indent}    mime = self._sniff_image_bytes(b)\n"
    f"{base_indent}    if mime is None:\n"
    f"{base_indent}        # Secondary guess by extension\n"
    f"{base_indent}        import mimetypes as _mt\n"
    f"{base_indent}        mt, _ = _mt.guess_type(str(path))\n"
    f"{base_indent}        if mt and mt.startswith(\"image/\"): mime = mt\n"
    f"{base_indent}    if mime:\n"
    f"{base_indent}        import base64 as _b64\n"
    f"{base_indent}        body = f\"data:{'{'}mime{'}'};base64,{{_b64.b64encode(b).decode('ascii')}}\"\n"
    f"{base_indent}    else:\n"
    f"{base_indent}        # Non-image binary: re-raise to keep prior behavior/logging\n"
    f"{base_indent}        raise\n"
)

meth_block = meth_block[:mline.start()] + replacement + meth_block[mline.end():]

# Reassemble class and file
new_cls_block = cls_block[:mdef.start()] + meth_block + cls_block[end_in:]
src = src[:start_cls] + new_cls_block + src[end_cls:]

if src != orig:
    io.open(path, "w", encoding="utf-8").write(src)
    print("✅ Patched: importer now reads images as base64 data-URLs")
else:
    print("ℹ️ No changes were necessary (already patched)")
PY

# Syntax check; restore on failure
if python3 -m py_compile "$FILE" 2>/dev/null; then
  echo "✅ Patched $FILE (backup at $BACKUP)"
else
  echo "⚠️ Syntax error — restoring backup."
  mv "$BACKUP" "$FILE"
  exit 1
fi

echo "Now run:  python3 main.py  → then use your usual Import menu."

