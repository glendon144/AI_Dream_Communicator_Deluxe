#!/bin/bash

set -e

echo "🔄 Cleaning old build artifacts..."
rm -rf build dist __pycache__ *.spec

echo "📂 Ensuring required folders exist..."
mkdir -p exported_docs
mkdir -p storage
touch exported_docs/.placeholder
touch storage/.placeholder

echo "🛠️ Building lite version..."
pyinstaller --onefile --name pikit-lite main.py

echo "📦 Size of lite binary:"
du -sh dist/pikit-lite

echo "⚡ Launch timing for lite binary:"
START=$(date +%s.%N)
./dist/pikit-lite --help >/dev/null 2>&1 || true
END=$(date +%s.%N)
echo "⏱️  Lite version launch time: $(echo "$END - $START" | bc) seconds"

echo
echo "✅ Done. Binaries are in: $(realpath dist)"

