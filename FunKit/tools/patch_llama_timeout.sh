#!/usr/bin/env bash
set -euo pipefail

PROVIDERS="storage/providers.json"
AIFILE="modules/ai_interface.py"

# --- 1) Ensure providers.json has a long timeout for local_llama (8081) ---
mkdir -p storage
python3 - <<'PY'
import json, os, sys
p = "storage/providers.json"
if not os.path.exists(p):
    os.makedirs("storage", exist_ok=True)
    data = {"default":"local_llama","providers":[]}
else:
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)

# ensure local_llama exists and set endpoint/timeout
found = False
for pr in data.get("providers", []):
    if pr.get("key") == "local_llama":
        pr.setdefault("label","Local (llama.cpp)")
        pr.setdefault("model","mistral-7b-instruct")
        pr["endpoint"] = "http://127.0.0.1:8081"
        pr.setdefault("extras", {})
        pr["extras"]["timeout"] = 600
        found = True
        break

if not found:
    data.setdefault("providers", []).insert(0, {
        "key":"local_llama",
        "label":"Local (llama.cpp)",
        "model":"mistral-7b-instruct",
        "endpoint":"http://127.0.0.1:8081",
        "env_key": None,
        "extras":{"timeout":600}
    })
    data.setdefault("default","local_llama")

with open(p, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
print("✅ providers.json updated (local_llama timeout=600, endpoint :8081)")
PY

# --- 2) Patch AIInterface to respect extras.timeout and add retries on timeout ---
cp -f "$AIFILE" "$AIFILE.bak.$(date +%Y%m%d%H%M%S)"

python3 - <<'PY'
import io, re, sys, time, os
path = "modules/ai_interface.py"
src = open(path, "r", encoding="utf-8").read()

# ensure _candidate_routes tries /chat/completions first (llama.cpp)
if "def _candidate_routes" in src:
    src = re.sub(
        r"def _candidate_routes\(self\):[\s\S]*?return\s*\[[\s\S]*?\]\n",
        (
            "def _candidate_routes(self):\n"
            "    base = (self.provider.endpoint or '').rstrip('/')\n"
            "    if self.provider.key == 'openai':\n"
            "        return ['https://api.openai.com/v1/chat/completions']\n"
            "    return [\n"
            "        f\"{base}/chat/completions\",      # llama.cpp\n"
            "        f\"{base}/v1/chat/completions\",   # vLLM/LM Studio/Ollama compat\n"
            "        f\"{base}/v1/completions\",        # rare shims\n"
            "    ]\n"
        ),
        src,
        flags=re.M
    )

# add timeout-aware post + retries if not present
if "def _post_json" in src:
    src = re.sub(
        r"def _post_json\(self, url: str, payload: dict, timeout: int\):[\s\S]*?return json.loads\(resp.read\(\).decode\(\"utf-8\"\)\)\n",
        (
            "def _post_json(self, url: str, payload: dict, timeout: int):\n"
            "    import urllib.request, urllib.error, socket\n"
            "    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'),\n"
            "                                 headers=self._headers(), method='POST')\n"
            "    try:\n"
            "        with urllib.request.urlopen(req, timeout=timeout) as resp:\n"
            "            return json.loads(resp.read().decode('utf-8'))\n"
            "    except socket.timeout as e:\n"
            "        raise TimeoutError(str(e))\n"
        ),
        src,
        flags=re.M
    )

# teach chat() to retry on TimeoutError using extras.timeout
if "def chat(" in src and "TimeoutError" not in src:
    src = re.sub(
        r"def chat\(self, messages: List\[Dict\[str, Any\]\], temperature: float = 0\.7, max_tokens: int = 512\) -> str:[\s\S]*?for url in self\._candidate_routes\(\):",
        (
            "def chat(self, messages: List[Dict[str, Any]], temperature: float = 0.7, max_tokens: int = 512) -> str:\n"
            "    payload = {\n"
            "        'model': self.provider.model,\n"
            "        'messages': messages,\n"
            "        'temperature': temperature,\n"
            "        'max_tokens': max_tokens,\n"
            "        'stream': False\n"
            "    }\n"
            "    timeout = int(self.provider.extras.get('timeout', 60))\n"
            "    attempts = 3\n"
            "    last_err = None\n"
            "    for url in self._candidate_routes():\n"
        ),
        src,
        flags=re.M
    )
    # wrap each request with retry
    src = re.sub(
        r"data = self\._post_json\(url, payload, timeout\)[\s\S]*?return data\.",
        (
            "            for attempt in range(1, attempts+1):\n"
            "                try:\n"
            "                    data = self._post_json(url, payload, timeout)\n"
            "                    break\n"
            "                except TimeoutError as e:\n"
            "                    last_err = f'timeout after {timeout}s (attempt {attempt}/{attempts})'\n"
            "                    if attempt < attempts:\n"
            "                        time.sleep(1.5 * attempt)\n"
            "                        continue\n"
            "                    else:\n"
            "                        raise\n"
            "            # try to extract text…\n"
            "            choices = data.get('choices', [])\n"
            "            if choices:\n"
            "                if 'message' in choices[0]:\n"
            "                    return choices[0]['message'].get('content', '') or '[No content returned]'\n"
            "                if 'text' in choices[0]:\n"
            "                    return choices[0].get('text','') or '[No content returned]'\n"
            "            if 'generated_text' in data:\n"
            "                return data.get('generated_text','') or '[No content returned]'\n"
            "            if 'message' in data and 'content' in data['message']:\n"
            "                return data['message']['content'] or '[No content returned]'\n"
            "            return '[No content returned]'\n"
        ),
        src,
        flags=re.M
    )

open(path, "w", encoding="utf-8").write(src)
print("✅ modules/ai_interface.py updated (timeout honored + retries, llama.cpp route order).")
PY

echo "All set. Try: python3 main.py"

