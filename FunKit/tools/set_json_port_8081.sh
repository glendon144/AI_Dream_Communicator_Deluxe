mkdir -p storage
cat > storage/providers.json <<'JSON'
{
  "default": "local_llama",
  "providers": [
    {
      "key": "local_llama",
      "label": "Local (llama.cpp)",
      "model": "mistral-7b-instruct",
      "endpoint": "http://127.0.0.1:8081",
      "env_key": null,
      "extras": { "timeout": 120 }
    },
    {
      "key": "openai",
      "label": "OpenAI (GPT-4o/5)",
      "model": "gpt-4o-mini",
      "endpoint": null,
      "env_key": "OPENAI_API_KEY",
      "extras": {}
    },
    {
      "key": "baseten",
      "label": "Baseten",
      "model": "YOUR_BASETEN_MODEL",
      "endpoint": "https://app.baseten.co/models",
      "env_key": "BASETEN_API_KEY",
      "extras": {}
    }
  ]
}
JSON

cat > storage/app_state.json <<'JSON'
{ "selected_provider": "local_llama" }
JSON

