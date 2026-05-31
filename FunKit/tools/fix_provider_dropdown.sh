#!/usr/bin/env bash
set -euo pipefail

GUI="gui_tkinter.py"

[ -f "$GUI" ] || { echo "❌ $GUI not found (run from FunKit root)"; exit 1; }

# --- 1) Backup
cp -f "$GUI" "$GUI.bak.$(date +%Y%m%d%H%M%S)"

# --- 2) Remove old provider_switch imports
sed -i '/from modules.provider_switch import/d' "$GUI"

# --- 3) Ensure new imports exist
grep -q "from modules.provider_dropdown import ProviderDropdown" "$GUI" || \
  sed -i '1i from modules.provider_dropdown import ProviderDropdown' "$GUI"
grep -q "from modules.provider_registry import registry" "$GUI" || \
  sed -i '1i from modules.provider_registry import registry' "$GUI"
grep -q "from modules.ai_interface import AIInterface" "$GUI" || \
  sed -i '1i from modules.ai_interface import AIInterface' "$GUI"

# --- 4) Replace any ProviderSwitcher with ProviderDropdown
sed -i 's/ProviderSwitcher(/ProviderDropdown(/g' "$GUI"

echo "✅ Patched $GUI to drop provider_switch and use ProviderDropdown."

# --- 5) Force defaults to Baseten in storage
mkdir -p storage
cat > storage/providers.json <<'JSON'
{
  "default": "baseten",
  "providers": [
    {
      "key": "baseten",
      "label": "Baseten",
      "model": "YOUR_BASETEN_MODEL",
      "endpoint": "https://app.baseten.co/models",
      "env_key": "BASETEN_API_KEY",
      "extras": {}
    },
    {
      "key": "local_llama",
      "label": "Local (llama.cpp)",
      "model": "mistral-7b-instruct",
      "endpoint": "http://127.0.0.1:8081",
      "env_key": null,
      "extras": { "timeout": 600 }
    },
    {
      "key": "openai",
      "label": "OpenAI (GPT-4o)",
      "model": "gpt-4o-mini",
      "endpoint": null,
      "env_key": "OPENAI_API_KEY",
      "extras": {}
    }
  ]
}
JSON

cat > storage/app_state.json <<'JSON'
{ "selected_provider": "baseten" }
JSON

echo "✅ storage/providers.json and app_state.json updated (default=baseten)."
echo
echo "Now run: python3 main.py"
echo "The dropdown should list 'Baseten', 'Local (llama.cpp)', and 'OpenAI (GPT-4o)'."

