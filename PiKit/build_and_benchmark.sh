#!/bin/bash

# Set paths
FULL_SPEC="pikit-full.spec"
FULL_EXEC="dist/pikit-full"
LITE_EXEC="dist/pikit-lite"

echo "🛠️  Building full version with: $FULL_SPEC"
time pyinstaller "$FULL_SPEC"

echo ""
echo "📦 Size of full binary:"
du -sh "$FULL_EXEC"

echo ""
echo "⚡ Launch timing for full binary:"
START_TIME=$(date +%s.%N)
"$FULL_EXEC" --version >/dev/null 2>&1 &
PID=$!
sleep 2
kill "$PID" >/dev/null 2>&1
END_TIME=$(date +%s.%N)
LAUNCH_TIME=$(echo "$END_TIME - $START_TIME" | bc)
printf "⏱️  Full version launch time: %.2f seconds\n" "$LAUNCH_TIME"

# Optional comparison with pikit-lite
if [ -f "$LITE_EXEC" ]; then
  echo ""
  echo "📦 Size of lite binary:"
  du -sh "$LITE_EXEC"

  echo ""
  echo "⚡ Launch timing for lite binary:"
  START_TIME_LITE=$(date +%s.%N)
  "$LITE_EXEC" --version >/dev/null 2>&1 &
  PID=$!
  sleep 2
  kill "$PID" >/dev/null 2>&1
  END_TIME_LITE=$(date +%s.%N)
  LAUNCH_TIME_LITE=$(echo "$END_TIME_LITE - $START_TIME_LITE" | bc)
  printf "⏱️  Lite version launch time: %.2f seconds\n" "$LAUNCH_TIME_LITE"
fi

echo ""
echo "✅ Done. Binary is located in dist/pikit-full"

