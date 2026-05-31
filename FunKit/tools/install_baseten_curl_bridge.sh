#!/usr/bin/env bash
set -euo pipefail

ROOT="$(pwd)"
AI="modules/ai_interface.py"
BR="modules/baseten_curl_bridge.py"
PJ="storage/providers.json"

[ -f "$AI" ] || { echo "❌ $AI not found; run from FunKit root"; exit 1; }
mkdir -p modules storage

# 1) Write the curl bridge (exactly mirrors your successful curl)
cat > "$BR" <<'PY'
# modules/baseten_curl_bridge.py
import os, json, tempfile, subprocess, shlex

def _base() -> str:
    # Your curl succeeded with inference.baseten.co/v1
    return os.getenv("BASETEN_BASE_URL", "https://inference.baseten.co/v1").rstrip("/")

def _key() -> str:
    k = os.getenv("BASETEN_API_KEY", "")
    if not k and os.path.exists(os.path.expanduser("~/baseten.key")):
        try:
            with open(os.path.expanduser("~/baseten.key"), "r", encoding="utf-8") as f:
                k = f.read().strip()
        except Exception:
            pass
    if not k:
        raise RuntimeError("BASETEN_API_KEY not set (and ~/baseten.key not found)")
    return k

def chat_once(messages, model=None, temperature=0.7, max_tokens=512):
    base = _base()               # e.g. https://inference.baseten.co/v1
    key  = _key()
    url  = f"{base}/chat/completions"
    model = model or os.getenv("BASETEN_MODEL") or "openai/gpt-oss-120b"

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }

    # Write JSON to a temp file to avoid shell-escaping headaches
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        json.dump(payload, tf)
        tf.flush()
        tmp = tf.name

    # Use curl because it works reliably in your environment
    # -sS: quiet but show errors
    # --fail-with-body: non-2xx returns body to stderr (curl 7.76+), fallback to --fail if missing
    cmd = [
        "bash", "-lc",
        # Try --fail-with-body first; if unsupported, curl exits 2 ⇒ rerun with --fail
        f'curl -sS --fail-with-body -H {shlex.quote("Authorization: Bearer " + key)} '
        f'-H "Content-Type: application/json" -H "Accept: application/json" '
        f'--connect-timeout 20 --max-time 90 '
        f'-X POST {shlex.quote(url)} -d @{shlex.quote(tmp)} '
        f'|| curl -sS --fail -H {shlex.quote("Authorization: Bearer " + key)} '
        f'-H "Content-Type: application/json" -H "Accept: application/json" '
        f'--connect-timeout 20 --max-time 90 '
        f'-X POST {shlex.quote(url)} -d @{shlex.quote(tmp)}'
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        msg = e.output.decode("utf-8", errors="ignore")
        raise RuntimeError(f"[Baseten curl] HTTP error from {url}:\n{msg[:1500]}") from None
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass

    txt = out.decode("utf-8", errors="ignore")
    try:
        data = json.loads(txt)
    except Exception:
        # If HTML leaked in somehow, surface it plainly
        if txt.lstrip().lower().startswith("<!doctype") or "<html" in txt.lower():
            raise RuntimeError(f"[Baseten curl] Unexpected HTML from {url}:\n{txt[:1500]}")
        raise RuntimeError(f"[Baseten curl] Non-JSON response from {url}:\n{txt[:1500]}")

    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        return json.dumps(data, ensure_ascii=False)
PY
echo "✅ Wrote $BR"

# 2) Patch ai_interface.py to route Baseten to the curl bridge
cp -f "$AI" "$AI.bak.$(date +%Y%m%d%H%M%S)"
python3 - <<'PY'
import re
p="modules/ai_interface.py"
s=open(p,"r",encoding="utf-8").read()

# Ensure registry import
if "from .provider_registry import registry" not in s:
    s = s.replace("from __future__ import annotations",
                  "from __future__ import annotations\nfrom .provider_registry import registry")

# Import curl bridge (idempotent)
if "import modules.baseten_curl_bridge as b10curl" not in s and \
   "from modules import baseten_curl_bridge as b10curl" not in s:
    s = s.replace("from __future__ import annotations",
                  "from __future__ import annotations\nimport modules.baseten_curl_bridge as b10curl")

# Make chat() re-check the selected provider, and route key=='baseten' to curl bridge
s = re.sub(
    r"def chat\(\s*self\s*,\s*messages[^\)]*\):\s*\n",
    "def chat(self, messages, *, temperature=0.7, max_tokens=512, **kw):\n"
    "        # Always read the current dropdown selection\n"
    "        try:\n"
    "            self.provider = registry.get(registry.read_selected())\n"
    "        except Exception:\n"
    "            pass\n"
    "        prov = getattr(self, 'provider', None)\n"
    "        key  = getattr(prov, 'key', None)\n"
    "        model = getattr(prov, 'model', None) or None\n"
    "        endpoint = getattr(prov, 'endpoint', None)\n"
    "        env_key = getattr(prov, 'env_key', None)\n"
    "\n"
    "        # Baseten → use curl bridge (mirrors your working curl)\n"
    "        if key == 'baseten':\n"
    "            return b10curl.chat_once(messages, model=model, temperature=temperature, max_tokens=max_tokens)\n"
    "\n",
    s, count=1, flags=re.S
)

open(p,"w",encoding="utf-8").write(s)
print("✅ Patched ai_interface.py to use curl bridge for Baseten.")
PY

# 3) Seed providers.json if missing (won't overwrite if present)
if [ ! -f "$PJ" ]; then
  cat > "$PJ" <<'JSON'
{
  "default": "baseten",
  "providers": [
    {
      "key": "baseten",
      "label": "Baseten",
      "model": "openai/gpt-oss-120b",
      "endpoint": "https://inference.baseten.co/v1",
      "env_key": "BASETEN_API_KEY",
      "extras": {}
    },
    {
      "key": "openai",
      "label": "OpenAI",
      "model": "gpt-4o-mini",
      "endpoint": "https://api.openai.com",
      "env_key": "OPENAI_API_KEY",
      "extras": {}
    },
    {
      "key": "local_llama",
      "label": "Local (llama.cpp)",
      "model": "mistral-7b-instruct",
      "endpoint": "http://127.0.0.1:8081",
      "env_key": null,
      "extras": { "timeout": 600 }
    }
  ]
}
JSON
  echo "↪️  Created storage/providers.json (edit model if you prefer)."
fi

echo
echo "Now test:"
echo "  export BASETEN_API_KEY=\$(cat ~/baseten.key)"
echo "  export BASETEN_BASE_URL=https://inference.baseten.co/v1"
echo "  PYTHONPATH=. python3 - <<'PY'"
echo "from modules.provider_registry import registry"
echo "from modules.ai_interface import AIInterface"
echo "registry.write_selected('baseten')"
echo "print('Reply:', AIInterface().query('Say only: OK', max_tokens=8, temperature=0))"
echo "PY"

