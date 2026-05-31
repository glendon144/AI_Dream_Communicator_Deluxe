# 1) See what your env currently has
echo "BASETEN_BASE_URL=${BASETEN_BASE_URL}"
echo "BASETEN_API_KEY length: ${#BASETEN_API_KEY}"

# 2) Force the correct base URL (or just unset to use the default)
unset BASETEN_BASE_URL
# or explicitly:
export BASETEN_BASE_URL="https://inference.baseten.co/v1"

# 3) Make sure the key is set in this shell
# (replace with your real key; the OpenAI-compatible endpoint expects this)
export BASETEN_API_KEY="Uf4C1dAO.MLPJZdCRlvuPYXAi4nAhgMTbAUNEVXdD"

# 4) Sanity check the client’s effective settings
python3 - <<'PY'
import sys; sys.path.insert(0,'.')
import modules.ai_interface_baseten as b10
print("Effective base_url:", b10._client.base_url)
print("Has API key:", bool(b10._API_KEY), "len:", len(b10._API_KEY or ""))
PY

# 5) Now test the routed call via AIInterface (uses your baseten client when selected)
python3 - <<'PY'
import sys; sys.path.insert(0,'.')
from modules.provider_registry import registry
from modules.ai_interface import AIInterface

registry.write_selected("baseten")
ai = AIInterface()
print("Provider:", registry.read_selected())
print("Reply:", ai.query("Say only: OK", max_tokens=8, temperature=0))
PY

