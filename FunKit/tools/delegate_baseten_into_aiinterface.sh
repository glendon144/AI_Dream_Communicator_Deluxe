#!/usr/bin/env bash
set -euo pipefail

AI="modules/ai_interface.py"
B10="modules/ai_interface_baseten.py"

[ -f "$AI" ] || { echo "❌ $AI not found"; exit 1; }
[ -f "$B10" ] || { echo "❌ $B10 not found (need your working Baseten client)"; exit 1; }

cp -f "$AI" "$AI.bak.$(date +%Y%m%d%H%M%S)"

python3 - <<'PY'
import re, io, sys, os, textwrap
p="modules/ai_interface.py"
s=open(p,"r",encoding="utf-8").read()

# 1) Ensure imports for registry and your baseten module (idempotent)
if "from .provider_registry import registry" not in s:
    s = s.replace("from __future__ import annotations",
                  "from __future__ import annotations\nfrom .provider_registry import registry")
if "import modules.ai_interface_baseten as b10" not in s and \
   "from modules import ai_interface_baseten as b10" not in s:
    # place near top-level imports
    s = s.replace("from __future__ import annotations",
                  "from __future__ import annotations\nimport modules.ai_interface_baseten as b10")

# 2) Make AIInterface.__init__ default to the selected provider if None (idempotent best-effort)
s = re.sub(
    r"class AIInterface\b.*?def __init__\(self,[^\)]*\):\s*([\s\S]*?)\n\s*def",
    lambda m: (
        m.group(0) if "registry.read_selected()" in m.group(0) else
        m.group(0).replace(
            m.group(1),
            "        # Default to the UI-selected provider when not specified\n"
            "        try:\n"
            "            if provider_key is None:\n"
            "                provider_key = registry.read_selected()\n"
            "        except Exception:\n"
            "            pass\n"
            "        self.provider = registry.get(provider_key)\n\n"
        )
    ),
    s, count=1, flags=re.S
)

# 3) Add a Baseten delegation at the TOP of chat() (before other routes).
#    We assume chat(self, messages, temperature=?, max_tokens=?)
if "def chat(" in s:
    s = re.sub(
        r"def chat\(\s*self\s*,\s*messages[^\)]*\):\s*\n",
        "def chat(self, messages, *, temperature=0.7, max_tokens=512, **kw):\n"
        "        # Baseten (OpenAI-compatible) delegation using your proven client\n"
        "        try:\n"
        "            prov = getattr(self, 'provider', None)\n"
        "            key = getattr(prov, 'key', None)\n"
        "            extras = getattr(prov, 'extras', {}) or {}\n"
        "            if key == 'baseten' or extras.get('api') == 'baseten_openai':\n"
        "                model = getattr(prov, 'model', None) or None\n"
        "                # Your client expects OpenAI-style messages\n"
        "                return b10.chat_once(messages=messages, model=model,\n"
        "                                     temperature=temperature, max_tokens=max_tokens)\n"
        "        except Exception as _b10_err:\n"
        "            # Fall through to existing routes if Baseten delegation fails\n"
        "            pass\n\n",
        s, count=1, flags=re.S
    )

# 4) Ensure legacy query()/complete() wrappers exist for GUI call sites
if "def query(self," not in s:
    s += (
        "\n    # ---- Back-compat wrappers ----\n"
        "    def query(self, prompt: str, *, system: str = 'You are a helpful assistant.', "
        "max_tokens: int = 512, temperature: float = 0.7):\n"
        "        msgs = [\n"
        "            {'role': 'system', 'content': system},\n"
        "            {'role': 'user',   'content': prompt},\n"
        "        ]\n"
        "        return self.chat(msgs, temperature=temperature, max_tokens=max_tokens)\n"
        "\n"
        "    def complete(self, prompt: str, *, max_tokens: int = 512, temperature: float = 0.7):\n"
        "        return self.query(prompt, system='You are a helpful assistant.', "
        "max_tokens=max_tokens, temperature=temperature)\n"
    )

open(p,"w",encoding="utf-8").write(s)
print("✅ Patched AIInterface to delegate to your Baseten client when selected.")
PY

echo
echo "Done. Now run:  python3 - <<'PY'"
echo "from modules.provider_registry import registry"
echo "from modules.ai_interface import AIInterface"
echo "print('Selected:', registry.read_selected())"
echo "print('Providers:', registry.list_labels())"
echo "ai = AIInterface()"
echo "print('Test reply ->', ai.query('Say only: OK', max_tokens=8, temperature=0))"
echo "PY"

