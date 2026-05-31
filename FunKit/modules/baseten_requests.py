import socket
import json
import requests
# modules/baseten_requests.py
import os, requests, json

BASE = os.getenv("BASETEN_BASE_URL", "https://inference.baseten.co/v1").rstrip("/")
URL  = f"{BASE}/chat/completions"

def chat_once(messages, model=None, temperature=0.7, max_tokens=512):
    model = model or os.getenv("BASETEN_MODEL") or "openai/gpt-oss-120b"
    key = os.getenv("BASETEN_API_KEY", "")
    if not key:
        raise RuntimeError("BASETEN_API_KEY not set")

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    import requests as _rq
    _sess = _rq.Session()
    _sess.trust_env = False  # IGNORE http_proxy/https_proxy/all_proxy/no_proxy
    # force no proxies even if the environment tries:
    _sess.proxies = {}
    print(f"[Baseten POST] URL={URL}", flush=True)
    r = _sess.post(URL, headers=headers, json=payload, timeout=60, allow_redirects=False)
    ct = r.headers.get("Content-Type", "")
    try:
        print(f"[Baseten RESP] status={r.status_code} ct={ct} server={r.headers.get('Server','?')} final_url={getattr(r, 'url', '?')}", flush=True)
    except Exception:
        pass
    if r.status_code >= 400:
        snippet = (r.text or "")[:800]
        raise RuntimeError(f"[Baseten requests] POST {URL} -> {r.status_code} CT={ct}\n{snippet}")

    try:
        data = r.json()
    except Exception:
        raise RuntimeError(f"[Baseten requests] Non-JSON from {URL} CT={ct}: {(r.text or '')[:400]}")

    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        return json.dumps(data, ensure_ascii=False)

