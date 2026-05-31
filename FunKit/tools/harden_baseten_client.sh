#!/usr/bin/env bash
set -euo pipefail

F="modules/ai_interface_baseten.py"
[ -f "$F" ] || { echo "❌ $F not found"; exit 1; }
cp -f "$F" "$F.bak.$(date +%Y%m%d%H%M%S)"

python3 - <<'PY'
import re, io, sys, json
p="modules/ai_interface_baseten.py"
s=open(p,"r",encoding="utf-8").read()

# 1) Ensure we can import requests for fallback
if "import requests" not in s:
    s = s.replace("from openai import OpenAI", "from openai import OpenAI\nimport requests")

# 2) Add a tiny helper to detect CSRF/HTML responses
if "_looks_like_html" not in s:
    s += """

def _looks_like_html(text: str) -> bool:
    if not isinstance(text, str):
        try:
            text = text.decode("utf-8", errors="ignore")
        except Exception:
            return False
    t = text.lstrip().lower()
    return t.startswith("<!doctype html") or t.startswith("<html") or ("csrf verification failed" in t)
"""

# 3) Wrap the SDK call with a fallback direct POST that mimics your successful curl
pat = r"def chat_once\(messages, model=None, temperature=0\.7, max_tokens=512\):\s*(.*?)\s*return resp\.choices\[0\]\.message\.content"
m = re.search(pat, s, flags=re.S)
if m:
    body = m.group(1)
    new = r'''
def chat_once(messages, model=None, temperature=0.7, max_tokens=512):
    # DEBUG breadcrumb: show base_url + model to catch misroutes
    try:
        print(f"[Baseten DEBUG] base_url={_client.base_url} model={model}", flush=True)
    except Exception:
        pass
    model = model or os.getenv("BASETEN_MODEL") or "openai/gpt-oss-120b"
    try:
        resp = _client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        return resp.choices[0].message.content
    except Exception as e:
        # If the SDK hits a redirect/CSRF page on this box, fall back to a direct POST like your curl
        # Try to extract details from OpenAI/httpx exception when available
        status = getattr(getattr(e, "response", None), "status_code", None)
        text = getattr(getattr(e, "response", None), "text", "") or ""
        url  = getattr(getattr(getattr(e, "response", None), "request", None), "url", None)
        print(f"[Baseten WARN] SDK call failed status={status} url={url} — attempting direct POST fallback", flush=True)

        base = os.getenv("BASETEN_BASE_URL", "https://inference.baseten.co/v1").rstrip("/")
        endpoint = f"{base}/chat/completions"

        headers = {
            "Authorization": f"Bearer {os.getenv('BASETEN_API_KEY','')}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        r = requests.post(endpoint, headers=headers, json=payload, timeout=60)
        ct = r.headers.get("Content-Type", "")
        body = r.text
        if r.status_code >= 400:
            # surface useful info
            print(f"[Baseten ERROR] direct POST {endpoint} -> {r.status_code} CT={ct}", flush=True)
            if _looks_like_html(body):
                raise RuntimeError(f"[Baseten] HTML error {r.status_code} from {endpoint}")
            raise RuntimeError(f"[Baseten] HTTP {r.status_code}: {body[:2000]}")
        try:
            data = r.json()
        except Exception:
            if _looks_like_html(body):
                raise RuntimeError("[Baseten] Unexpected HTML received from inference endpoint")
            raise RuntimeError(f"[Baseten] Non-JSON response: {body[:2000]}")
        try:
            return data["choices"][0]["message"]["content"]
        except Exception:
            # fallback: stringify
            return json.dumps(data, ensure_ascii=False)
'''
    s = re.sub(pat, new, s, flags=re.S)
else:
    print("WARN: chat_once signature not found; no patch applied to that function.", file=sys.stderr)

open(p,"w",encoding="utf-8").write(s)
print("✅ Hardened ai_interface_baseten.py with cURL-like fallback when SDK path fails.")
PY

echo
echo "Test it (Baseten selected):"
python3 - <<'PY'
import sys, os
sys.path.insert(0,'.')
from modules.provider_registry import registry
from modules.ai_interface import AIInterface
registry.write_selected("baseten")
ai = AIInterface()
print("Reply:", ai.query("Say only: OK", max_tokens=8, temperature=0))
PY

