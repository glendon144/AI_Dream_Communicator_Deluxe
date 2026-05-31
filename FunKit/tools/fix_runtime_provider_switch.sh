#!/usr/bin/env bash
set -euo pipefail

AI="modules/ai_interface.py"

[ -f "$AI" ] || { echo "❌ $AI not found"; exit 1; }
cp -f "$AI" "$AI.bak.$(date +%Y%m%d%H%M%S)"

python3 - <<'PY'
import re
p="modules/ai_interface.py"
s=open(p,"r",encoding="utf-8").read()

# Ensure imports
if "from .provider_registry import registry" not in s:
    s = s.replace("from __future__ import annotations",
                  "from __future__ import annotations\nfrom .provider_registry import registry")
if "import modules.ai_interface_baseten as b10" not in s and \
   "from modules import ai_interface_baseten as b10" not in s:
    s = s.replace("from __future__ import annotations",
                  "from __future__ import annotations\nimport modules.ai_interface_baseten as b10")

# 1) Make chat() re-fetch the current provider EVERY call
#    Insert right at top of chat(): self.provider = registry.get(registry.read_selected())
s = re.sub(
    r"def chat\(\s*self\s*,\s*messages[^\)]*\):\s*\n",
    "def chat(self, messages, *, temperature=0.7, max_tokens=512, **kw):\n"
    "        # Always use the provider currently selected in the dropdown\n"
    "        try:\n"
    "            self.provider = registry.get(registry.read_selected())\n"
    "        except Exception:\n"
    "            pass\n\n",
    s, count=1, flags=re.S
)

# 2) Tighten Baseten delegation so it only triggers when provider.key == 'baseten'
#    and never when 'openai' is selected.
if "b10.chat_once(" not in s:
    # add delegation block immediately after the re-fetch block
    s = s.replace(
        "        try:\n            self.provider = registry.get(registry.read_selected())\n        except Exception:\n            pass\n\n",
        "        try:\n"
        "            self.provider = registry.get(registry.read_selected())\n"
        "        except Exception:\n"
        "            pass\n\n"
        "        # Baseten (OpenAI-compatible) delegation: use your known-good client\n"
        "        try:\n"
        "            prov = getattr(self, 'provider', None)\n"
        "            key = getattr(prov, 'key', None)\n"
        "            if key == 'baseten':\n"
        "                model = getattr(prov, 'model', None) or None\n"
        "                return b10.chat_once(messages=messages, model=model,\n"
        "                                     temperature=temperature, max_tokens=max_tokens)\n"
        "        except Exception:\n"
        "            # fall through to the rest of the implementation\n"
        "            pass\n\n"
    )

# 3) Ensure back-compat wrappers exist
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
print("✅ ai_interface.py patched: runtime provider switch + Baseten delegation only when key=='baseten'.")
PY

echo
echo "Sanity test (should print the provider that will be used right now):"
cat > /tmp/test_provider.py <<'PY'
from modules.provider_registry import registry
from modules.ai_interface import AIInterface
print("Selected:", registry.read_selected())
ai = AIInterface()  # chat() will re-check selection anyway
print("Querying selected provider...")
print(ai.query("Say only: OK", max_tokens=8, temperature=0))
PY
python3 /tmp/test_provider.py || true

