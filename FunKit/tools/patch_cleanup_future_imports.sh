#!/usr/bin/env bash
set -euo pipefail
ENG="modules/aopml_engine.py"
[ -f "$ENG" ] || { ENG="modules/aopmlengine.py"; }
[ -f "$ENG" ] || { echo "❌ Engine not found"; exit 1; }

cp -p "$ENG" "$ENG.bak.$(date +%Y%m%d-%H%M%S)"

# Keep only the very first "from __future__ import" line, remove others
awk '
/^from __future__ import/ {
  if (seen) next
  seen=1
}
{ print }
' "$ENG" > "$ENG.tmp" && mv "$ENG.tmp" "$ENG"

echo "✅ Cleaned duplicate __future__ imports in $ENG"

