
#!/usr/bin/env bash
set -Eeuo pipefail
# start_localai.sh — spin up LocalAI on :8080 and register a Mistral 7B GGUF

MODELS_DIR="${MODELS_DIR:-$HOME/localai/models}"
PORT="${PORT:-8080}"
IMAGE="quay.io/go-skynet/local-ai:latest"
NAME="localai"

mkdir -p "$MODELS_DIR"
echo "Models dir: $MODELS_DIR"

# Create a sample model YAML if not present
YAML="$MODELS_DIR/mistral-7b-instruct.yaml"
if [[ ! -f "$YAML" ]]; then
  cat > "$YAML" <<'YML'
name: mistral-7b-instruct
backend: ggml
parameters:
  model: /models/mistral-7b-instruct.Q4_K_M.gguf
YML
  echo "Wrote $YAML (edit 'model:' path to your GGUF filename)"
fi

# Run LocalAI
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME"   -p ${PORT}:8080   -v "$MODELS_DIR":/models   -e MODELS_PATH=/models   "$IMAGE"

echo "LocalAI running on http://localhost:${PORT}"
echo "Remember to place your GGUF file at: $MODELS_DIR/mistral-7b-instruct.Q4_K_M.gguf (or update the YAML)"
echo "Env to use in PiKit:"
echo "  export PIKIT_OPENAI_BASE_URL='http://localhost:${PORT}/v1'"
echo "  export PIKIT_OPENAI_API_KEY='sk-local'"
echo "  export PIKIT_MODEL_NAME='mistral-7b-instruct'"
