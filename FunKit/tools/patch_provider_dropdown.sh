#!/usr/bin/env bash
set -euo pipefail
mkdir -p modules storage

backup() {
  local f="$1"
  if [ -f "$f" ]; then cp -f "$f" "$f.bak.$(date +%Y%m%d%H%M%S)"; fi
}

# provider_registry.py
backup modules/provider_registry.py
cat > modules/provider_registry.py <<'PY'
# (paste the full provider_registry.py content from above)
PY

# ai_interface.py
backup modules/ai_interface.py
cat > modules/ai_interface.py <<'PY'
# (paste the full ai_interface.py content from above)
PY

# ensure providers.json exists
if [ ! -f storage/providers.json ]; then
  cat > storage/providers.json <<'JSON'
{
  "default": "openai",
  "providers": [
    { "key":"openai","label":"OpenAI (GPT-4o/5)","model":"gpt-4o-mini","endpoint":null,"env_key":"OPENAI_API_KEY","extras":{} },
    { "key":"baseten","label":"Baseten","model":"YOUR_BASETEN_MODEL","endpoint":"https://app.baseten.co/models","env_key":"BASETEN_API_KEY","extras":{} },
    { "key":"local_llama","label":"Local (llama.cpp)","model":"gguf-q4_k_m","endpoint":"http://127.0.0.1:8080/v1","env_key":null,"extras":{"timeout":120} },
    { "key":"hf_tgi","label":"Hugging Face TGI","model":"meta-llama/Llama-3.1-8B-Instruct","endpoint":"http://127.0.0.1:8081","env_key":"HF_API_TOKEN","extras":{} }
  ]
}
JSON
fi

echo "✅ Provider modules installed. Now wire the Combobox in gui_tkinter.py as shown."

