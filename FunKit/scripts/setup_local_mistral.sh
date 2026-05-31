#!/usr/bin/env bash
set -euo pipefail

# --- Config (change if you like) ---
LLAMA_DIR="$HOME/llama.cpp"
MODEL_DIR="$HOME/models/mistral-7b-instruct"
MODEL_FILE="$MODEL_DIR/mistral-7b-instruct.Q4_K_M.gguf"   # place your .gguf here
HOST="0.0.0.0"
PORT="8081"
CTX=4096

echo "==> Installing build prerequisites"
sudo apt-get update -y
sudo apt-get install -y build-essential cmake git

# Optional: BLAS for speed (CPU only). Comment out if you prefer plain build.
sudo apt-get install -y libopenblas-dev

echo "==> Cloning and building llama.cpp"
if [ ! -d "$LLAMA_DIR" ]; then
  git clone https://github.com/ggerganov/llama.cpp.git "$LLAMA_DIR"
fi
cd "$LLAMA_DIR"

# Plain CMake build:
cmake -B build
cmake --build build -j

# (Optional) BLAS build: uncomment these 2 lines instead of CMake if you prefer Make + OpenBLAS
# make clean || true
# make -j LLAMA_BLAS=1 LLAMA_BLAS_VENDOR=OpenBLAS

echo "==> Preparing model folder"
mkdir -p "$MODEL_DIR"

cat <<'TIP'

*********************************************************************
Place a Mistral Instruct GGUF file at:
  $MODEL_FILE

Examples (names vary by source/quant):
  - mistral-7b-instruct.Q4_K_M.gguf
  - Mistral-7B-Instruct-v0.2.Q4_K_M.gguf
  - Mixtral-8x7B-Instruct.Q4_K_M.gguf (needs lots of RAM/VRAM)

Tip: You can use Hugging Face `huggingface-cli download` or your browser,
then move the .gguf into the path above.

Once the file exists, press Enter to continue.
*********************************************************************
TIP
read -r _

if [ ! -f "$MODEL_FILE" ]; then
  echo "ERROR: Model file not found at: $MODEL_FILE"
  echo "Place the .gguf file there and re-run this script."
  exit 1
fi

echo "==> Starting llama.cpp server on :$PORT"
BIN="$LLAMA_DIR/build/bin/server"
if [ ! -x "$BIN" ]; then
  echo "Could not find server binary at $BIN"
  exit 1
fi

# Kill any previous server on that port
if ss -lnt | grep -q ":$PORT"; then
  echo "Port $PORT in use. Attempting to stop old server..."
  pkill -f "$BIN" || true
  sleep 1
fi

nohup "$BIN" \
  -m "$MODEL_FILE" \
  --host "$HOST" \
  --port "$PORT" \
  -c "$CTX" \
  > "$HOME/mistral_server.log" 2>&1 &

sleep 2
echo "==> Health check:"
curl -s "http://localhost:${PORT}/v1/models" | sed 's/"/\\"/g'

echo
echo "==> Done. OpenAI-compatible endpoint is live at:"
echo "    http://localhost:${PORT}/v1/chat/completions"
echo
echo "Log: $HOME/mistral_server.log"

