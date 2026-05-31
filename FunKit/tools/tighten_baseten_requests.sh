#!/usr/bin/env bash
set -euo pipefail

F="modules/baseten_requests.py"
[ -f "$F" ] || { echo "❌ $F not found. Please create modules/baseten_requests.py first."; exit 1; }
cp -f "$F" "$F.bak.$(date +%Y%m%d%H%M%S)"

python3 - <<'PY'
import re, sys
p="modules/baseten_requests.py"
s=open(p,"r",encoding="utf-8").read()

# ensure imports
if "import requests" not in s:
    s = "import requests\n" + s
if "import os" not in s:
    s = "import os\n" + s
if "import json" not in s:
    s = "import json\n" + s
if "import socket" not in s:
    s = "import socket\n" + s

# replace the requests.post(...) call with a Session using trust_env=False and proxies={}
s = re.sub(
    r"r\s*=\s*requests\.post\((.+?)\)",
    "import requests as _rq\n"
    "    _sess = _rq.Session()\n"
    "    _sess.trust_env = False  # IGNORE http_proxy/https_proxy/all_proxy/no_proxy\n"
    "    # force no proxies even if the environment tries:\n"
    "    _sess.proxies = {}\n"
    "    print(f\"[Baseten POST] URL={URL}\", flush=True)\n"
    "    r = _sess.post(\\1, allow_redirects=False)",
    s, flags=re.S
)

# also print response meta for debugging
if "print(f\"[Baseten RESP] status=\"" not in s:
    s = s.replace(
        "ct = r.headers.get(\"Content-Type\", \"\")",
        "ct = r.headers.get(\"Content-Type\", \"\")\n"
        "    try:\n"
        "        print(f\"[Baseten RESP] status={r.status_code} ct={ct} server={r.headers.get('Server','?')} final_url={getattr(r, 'url', '?')}\", flush=True)\n"
        "    except Exception:\n"
        "        pass"
    )

open(p,"w",encoding="utf-8").write(s)
print("✅ Tightened baseten_requests: trust_env=False, proxies={}, and added debug prints.")
PY

echo
echo "Now test with a clean env:"
cat > /tmp/test_b10_clean.py <<'PY'
import os, sys
sys.path.insert(0, '.')
# nuke proxy/env overrides for this process:
for k in list(os.environ):
    if k.lower() in ("http_proxy","https_proxy","all_proxy","no_proxy"):
        os.environ.pop(k, None)
# ensure correct base + key
os.environ["BASETEN_BASE_URL"] = os.environ.get("BASETEN_BASE_URL","https://inference.baseten.co/v1")
assert os.environ.get("BASETEN_API_KEY"), "Set BASETEN_API_KEY"

from modules.provider_registry import registry
from modules.ai_interface import AIInterface

registry.write_selected("baseten")
ai = AIInterface()
print("Reply:", ai.query("Say only: OK", max_tokens=8, temperature=0))
PY

echo "Running:"
PYTHONPATH=. python3 /tmp/test_b10_clean.py

