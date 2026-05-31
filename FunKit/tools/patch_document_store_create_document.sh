#!/usr/bin/env bash
set -euo pipefail

FILE="modules/document_store.py"
BACKUP="$FILE.bak.$(date +%Y%m%d-%H%M%S)"

if [[ ! -f "$FILE" ]]; then
  echo "❌ $FILE not found. Run this from your project root."
  exit 1
fi

cp "$FILE" "$BACKUP"
echo "📦 Backup: $BACKUP"

python3 - <<'PY'
import io, re, sys, pathlib
p = pathlib.Path("modules/document_store.py")
src = p.read_text(encoding="utf-8")

# quick guards
if "class DocumentStore" not in src:
    print("❌ Could not find class DocumentStore in modules/document_store.py")
    sys.exit(2)

# If create_document already exists, do nothing
if re.search(r"\n\s*def\s+create_document\s*\(", src):
    print("ℹ️  create_document already exists; no changes made.")
    sys.exit(0)

# Find the DocumentStore class block
m = re.search(r"(class\s+DocumentStore\s*\([^)]*\)\s*:\s*\n)", src)
if not m:
    m = re.search(r"(class\s+DocumentStore\s*:\s*\n)", src)
if not m:
    print("❌ Could not find DocumentStore class header.")
    sys.exit(3)

class_start = m.end()

# Determine an insertion point: right after class docstring or first method
after_header = src[class_start:]
docstring_match = re.match(r'\s+("""[\s\S]*?""")\s*\n', after_header)
insert_pos = class_start
if docstring_match:
    insert_pos += docstring_match.end()

shim = r"""
    def create_document(self, content, title=None, metadata=None):
        """
        Legacy compatibility shim.
        Prefer `add_document` or `new_document` internally if present.
        """
        # Prefer modern APIs if available
        if hasattr(self, "add_document"):
            return self.add_document(content, title=title, metadata=metadata)
        if hasattr(self, "new_document"):
            # Some forks accept (content, title=None, metadata=None)
            return self.new_document(content, title=title, metadata=metadata)

        # Fall back to a minimal insert path if present in this fork
        # Common internal names we try carefully (no hard dependency):
        for name in ("_insert_document", "_create_row", "_insert_row"):
            fn = getattr(self, name, None)
            if callable(fn):
                try:
                    return fn(content, title=title, metadata=metadata)
                except TypeError:
                    # Try looser call signature if that method differs
                    try:
                        return fn(content, title)
                    except TypeError:
                        pass

        raise AttributeError(
            "DocumentStore has no add_document/new_document and no known insert helper; "
            "please wire create_document to your insert method in document_store.py"
        )
"""

# keep indentation consistent (class level)
# Ensure newline before/after
if not src[insert_pos-1:insert_pos] == "\n":
    shim = "\n" + shim
new_src = src[:insert_pos] + shim + src[insert_pos:]

p.write_text(new_src, encoding="utf-8")
print("✅ Added legacy create_document shim to DocumentStore.")
PY

echo "🎉 Done."

