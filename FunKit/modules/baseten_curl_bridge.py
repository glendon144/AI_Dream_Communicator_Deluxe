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
