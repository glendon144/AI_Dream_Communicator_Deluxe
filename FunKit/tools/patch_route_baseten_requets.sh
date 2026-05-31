#!/usr/bin/env bash
set -euo pipefail
AI="modules/ai_interface.py"
AD="modules/baseten_requests.py"

[ -f "$AI" ] || { echo "❌ $AI not found"; exit 1; }
[ -f "$AD" ] || { echo "❌ $AD not found (create modules/baseten_requests.py first)"; exit 1; }

cp -f "$AI" "$AI.bak.$(date +%Y%m%d%H%M%S)"

python3 - <<'PY'
import re, sys
p="modules/ai_interface.py"
s=open(p,"r",encoding="utf-8").read()

# Ensure registry import
if "from .provider_registry import registry" not in s:
    s = s.replace("from __future__ import annotations",
                  "from __future__ import annotations\nfrom .provider_registry import registry")

# Import our requests-based adapter
if "import modules.baseten_requests as b10r" not in s and \
   "from modules import baseten_requests as b10r" not in s:
    s = s.replace("from __future__ import annotations",
                  "from __future__ import annotations\nimport modules.baseten_requests as b10r")

# Make chat() re-read current provider each call and route Baseten via b10r
s = re.sub(
    r"def chat\(\s*self\s*,\s*messages[^\)]*\):\s*\n",
    "def chat(self, messages, *, temperature=0.7, max_tokens=512, **kw):\n"
    "        # Always respect the current dropdown selection\n"
    "        try:\n"
    "            self.provider = registry.get(registry.read_selected())\n"
    "        except Exception:\n"
    "            pass\n"
    "        # Baseten → requests-based adapter hitting https://inference.baseten.co/v1/chat/completions\n"
    "        try:\n"
    "            prov = getattr(self, 'provider', None)\n"
    "            if getattr(prov, 'key', None) == 'baseten':\n"
    "                model = getattr(prov, 'model', None) or None\n"
    "                return b10r.chat_once(messages=messages, model=model,\n"
    "                                      temperature=temperature, max_tokens=max_tokens)\n"
    "        except Exception:\n"
    "            # fall through to other providers\n"
    "            pass\n\n",
    s, count=1, flags=re.S
)

# Ensure query() wrapper exists (some GUI paths use it)
if "def query(self," not in s:
    s += (
        "\n    def query(self, prompt: str, *, system: str = 'You are a helpful assistant.', "
        "max_tokens: int = 512, temperature: float = 0.7):\n"
        "        msgs = [\n"
        "            {'role': 'system', 'content': system},\n"
        "            {'role': 'user',   'content': prompt},\n"
        "        ]\n"
        "        return self.chat(msgs, temperature=temperature, max_tokens=max_tokens)\n"
    )

open(p,"w",encoding="utf-8").write(s)
print("✅ Routed Baseten to requests-based adapter (no SDK, exact URL).")
PY

echo
echo "Test:"
cat > /tmp/test_baseten_requests.py <<'PY'
import sys, os
sys.path.insert(0,'.')
from modules.provider_registry import registry
from modules.ai_interface import AIInterface

# Ensure env like your successful curl:
os.environ['BASETEN_BASE_URL'] = os.environ.get('BASETEN_BASE_URL','https://inference.baseten.co/v1')
assert os.environ.get('BASETEN_API_KEY'), "Set BASETEN_API_KEY"

registry.write_selected('baseten')
ai = AIInterface()
print("Provider:", registry.read_selected())
print("Reply:", ai.query("Say only: OK", max_tokens=8, temperature=0))
PY

PYTHONPATH=. python3 /tmp/test_baseten_requests.py

