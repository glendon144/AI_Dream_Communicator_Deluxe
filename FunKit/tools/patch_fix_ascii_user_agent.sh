#!/usr/bin/env bash
set -euo pipefail

files=(
  "modules/aopml_engine.py"
  "modules/aopmlengine.py"
)

ts=$(date +%Y%m%d-%H%M%S)
for f in "${files[@]}"; do
  [ -f "$f" ] || continue
  cp -p "$f" "$f.bak.$ts"
  # Replace any Unicode arrows in headers/strings with ASCII
  sed -i "s/URL→OPML/URL->OPML/g" "$f"
  sed -i "s/\/URL→OPML/\/URL->OPML/g" "$f"
done

echo "✅ Replaced Unicode arrows with ASCII in possible engine files."

