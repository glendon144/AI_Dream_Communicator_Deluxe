#!/usr/bin/env bash
#
# configure_ai_interface.sh
# Interactive configurator for PyKit AI providers + generator for modules/ai_interface.py
# Safe to run multiple times. Stores profiles in storage/ai-profiles.d/*.env
# Requires: bash, sed, mkdir, awk, python3 (for optional self-test), and 'requests' python pkg.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOD_DIR="$ROOT/modules"
STORAGE_DIR="$ROOT/storage"
PROFILE_DIR="$STORAGE_DIR/ai-profiles.d"
USE_SCRIPT="$ROOT/use_ai_profile.sh"
AI_FILE="$MOD_DIR/ai_interface.py"

mkdir -p "$MOD_DIR" "$PROFILE_DIR"

banner() {
  echo "-------------------------------------------------------------------------------"
  echo " PyKit AI Interface Configurator"
  echo "-------------------------------------------------------------------------------"
}

pause() { read -rp "Press Enter to continue..."; }

list_profiles() {
  echo "Available profiles:"
  shopt -s nullglob
  for f in "$PROFILE_DIR"/*.env; do
    b="$(basename "$f")"
    echo "  - ${b%.env}"
  done
  shopt -u nullglob
}

select_profile() {
  list_profiles
  echo
  read -rp "Enter profile name (existing or new): " PROFILE
  PROFILE="${PROFILE// /_}"
  if [[ -z "$PROFILE" ]]; then
    echo "Profile name cannot be empty." >&2
    exit 1
  fi
  PROFILE_PATH="$PROFILE_DIR/$PROFILE.env"
}

ask() {
  # $1=prompt $2=varname $3=default $4=is_secret(yes/no)
  local prompt="$1" var="$2" def="${3:-}" secret="${4:-no}" val=""
  if [[ -n "$def" ]]; then prompt="$prompt [$def]"; fi
  if [[ "$secret" == "yes" ]]; then
    read -rsp "$prompt: " val; echo
  else
    read -rp "$prompt: " val
  fi
  if [[ -z "$val" ]]; then val="$def"; fi
  printf -v "$var" '%s' "$val"
}

create_or_update_profile() {
  select_profile
  local PROVIDER MODEL HF_TOKEN OPENAI_KEY OPENAI_BASE LLAMA_URL TIMEOUT UA
  if [[ -f "$PROFILE_PATH" ]]; then
    echo "Loading existing values from $PROFILE_PATH ..."
    # shellcheck disable=SC1090
    . "$PROFILE_PATH"
  fi

  echo
  echo "Choose provider:"
  echo "  1) huggingface   (default)"
  echo "  2) openai        (or any OpenAI-compatible endpoint)"
  echo "  3) llama         (llama.cpp --api)"
  read -rp "Enter choice [1-3]: " CHOICE
  case "${CHOICE:-1}" in
    1|"") PROVIDER="huggingface" ;;
    2)     PROVIDER="openai" ;;
    3)     PROVIDER="llama" ;;
    *)     echo "Invalid choice"; exit 1 ;;
  esac

  case "$PROVIDER" in
    huggingface)
      ask "HF model ID" MODEL "${PIKIT_MODEL:-meta-llama/Llama-3.1-8B-Instruct}"
      ask "HF token (starts with hf_...)" HF_TOKEN "${PIKIT_HF_TOKEN:-}" yes
      ;;
    openai)
      ask "OpenAI/compat model" MODEL "${PIKIT_MODEL:-gpt-4o-mini}"
      ask "OpenAI API base (optional; default api.openai.com/v1)" OPENAI_BASE "${PIKIT_OPENAI_BASE:-}"
      ask "OpenAI API key (or compat key)" OPENAI_KEY "${PIKIT_OPENAI_API_KEY:-}" yes
      ;;
    llama)
      ask "llama.cpp API base URL" LLAMA_URL "${PIKIT_LLAMA_URL:-http://127.0.0.1:8081/v1}"
      ask "Model name label (llama.cpp often ignores this)" MODEL "${PIKIT_MODEL:-llama}"
      ;;
  esac
  ask "HTTP timeout (seconds)" TIMEOUT "${PIKIT_TIMEOUT:-60}"
  ask "Custom User-Agent (optional)" UA "${PIKIT_USER_AGENT:-PyKit-AIInterface/1.0}"

  {
    echo "# PyKit AI profile: $PROFILE"
    echo "PIKIT_PROVIDER=$PROVIDER"
    echo "PIKIT_MODEL=$MODEL"
    echo "PIKIT_TIMEOUT=$TIMEOUT"
    echo "PIKIT_USER_AGENT=$UA"
    case "$PROVIDER" in
      huggingface)
        echo "PIKIT_HF_TOKEN=$HF_TOKEN"
        ;;
      openai)
        [[ -n "${OPENAI_BASE:-}" ]] && echo "PIKIT_OPENAI_BASE=$OPENAI_BASE"
        echo "PIKIT_OPENAI_API_KEY=$OPENAI_KEY"
        ;;
      llama)
        echo "PIKIT_LLAMA_URL=$LLAMA_URL"
        ;;
    esac
  } > "$PROFILE_PATH"

  echo "Saved profile: $PROFILE_PATH"
}

write_use_script() {
  cat > "$USE_SCRIPT" <<'SH'
#!/usr/bin/env bash
# source this with:  source ./use_ai_profile.sh <profilename>
set -euo pipefail
if [[ $# -lt 1 ]]; then
  echo "Usage: source ./use_ai_profile.sh <profile>" >&2
  return 2 2>/dev/null || exit 2
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="$1"
FILE="$ROOT/storage/ai-profiles.d/${PROFILE}.env"
if [[ ! -f "$FILE" ]]; then
  echo "Profile not found: $FILE" >&2
  return 1 2>/dev/null || exit 1
fi
set -a
# shellcheck disable=SC1090
. "$FILE"
set +a
echo "Loaded AI profile: $PROFILE"
env | grep -E '^PIKIT_(PROVIDER|MODEL|HF_TOKEN|OPENAI|LLAMA|TIMEOUT|USER_AGENT)'
SH
  chmod +x "$USE_SCRIPT"
}

generate_ai_interface_py() {
  echo "Writing $AI_FILE ..."
  cat > "$AI_FILE" <<'PY'
# modules/ai_interface.py
# --------------------------------------------------------------------------------------------------
# PyKit AI Interface (thin-client friendly)
# Default: Hugging Face Inference API; also supports OpenAI-style backends & llama.cpp --api
# No non-stdlib deps except 'requests'. Streaming for OpenAI-style; HF uses non-stream JSON.
#
# Backwards compatibility:
#  - .query(prompt, **kwargs) wrapper calls .chat([...]) and returns a string
#  - Accepts either a single string prompt or a list of {role, content} messages
#
# Env configuration:
#  - PIKIT_PROVIDER: 'huggingface' (default) | 'openai' | 'llama'
#  - PIKIT_MODEL: model name/ID (HF/OpenAI)
#  - PIKIT_HF_TOKEN: Hugging Face token
#  - PIKIT_OPENAI_API_KEY: OpenAI (or compatible) API key
#  - PIKIT_OPENAI_BASE: override base URL (e.g., http://127.0.0.1:8081/v1)
#  - PIKIT_LLAMA_URL: llama.cpp server base (e.g., http://127.0.0.1:8081/v1)
#  - PIKIT_TIMEOUT: HTTP timeout seconds (default 60)
#  - PIKIT_USER_AGENT: custom UA
# --------------------------------------------------------------------------------------------------

from __future__ import annotations
import json
import os
import time
import re
import socket
from typing import Dict, Iterable, Iterator, List, Optional, Tuple, Union
import requests

def _getenv(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.environ.get(name)
    return val if val not in (None, "", "None") else default

def _timeout() -> int:
    try:
        return int(_getenv("PIKIT_TIMEOUT", "60"))
    except Exception:
        return 60

def _ua() -> str:
    return _getenv("PIKIT_USER_AGENT", "PyKit-AIInterface/1.0")

def _is_local_address(url: str) -> bool:
    try:
        host = re.sub(r"^https?://", "", url).split("/")[0].split(":")[0]
        if host in ("localhost",):
            return True
        ip = socket.gethostbyname(host)
        if ip.startswith("127.") or ip.startswith("10.") or ip.startswith("192.168."):
            return True
        if ip.startswith("172."):
            oct2 = int(ip.split(".")[1])
            if 16 <= oct2 <= 31:
                return True
    except Exception:
        pass
    return False

def _merge_kwargs(base: dict, extra: Optional[dict]) -> dict:
    if not extra:
        return dict(base)
    out = dict(base)
    out.update({k:v for k,v in extra.items() if v is not None})
    return out

def _as_chat(messages: Union[str, List[Dict[str, str]]]) -> List[Dict[str, str]]:
    if isinstance(messages, str):
        return [{"role": "user", "content": messages}]
    return messages

def _extract_text(o: dict, default: str = "") -> str:
    try:
        return o["choices"][0]["message"]["content"]
    except Exception:
        return default

def _sse_lines(resp: requests.Response) -> Iterator[str]:
    buff = ""
    for chunk in resp.iter_content(chunk_size=None):
        if not chunk:
            continue
        try:
            buff += chunk.decode("utf-8", errors="ignore")
        except Exception:
            continue
        while "\n" in buff:
            line, buff = buff.split("\n", 1)
            yield line.rstrip("\r")

class ProviderBase:
    name: str = "base"
    def chat(self, messages: Union[str, List[Dict[str, str]]], stream: bool = False, **kwargs) -> Union[str, Iterator[str]]:
        raise NotImplementedError

class HuggingFaceProvider(ProviderBase):
    name = "huggingface"
    def __init__(self, model: Optional[str] = None, token: Optional[str] = None):
        self.model = model or _getenv("PIKIT_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
        self.token = token or _getenv("PIKIT_HF_TOKEN")
        if not self.token:
            raise RuntimeError("Hugging Face token missing: set PIKIT_HF_TOKEN")

    def chat(self, messages: Union[str, List[Dict[str, str]]], stream: bool = False, **kwargs) -> Union[str, Iterator[str]]:
        msgs = _as_chat(messages)
        sys_prompt = "\n".join(m["content"] for m in msgs if m.get("role") == "system")
        user_turns = [m["content"] for m in msgs if m.get("role") != "system"]
        prompt = (("System:\n" + sys_prompt + "\n\n") if sys_prompt else "") + "\n\n".join(user_turns)

        url = f"https://api-inference.huggingface.co/models/{self.model}"
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json", "User-Agent": _ua()}
        params = {
            "max_new_tokens": int(kwargs.get("max_new_tokens", 512)),
            "temperature": float(kwargs.get("temperature", 0.7)),
            "top_p": float(kwargs.get("top_p", 0.95)),
            "return_full_text": False,
        }
        payload = {"inputs": prompt, "parameters": params}
        r = requests.post(url, headers=headers, json=payload, timeout=_timeout())
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and data and "generated_text" in data[0]:
            text = data[0]["generated_text"]
        elif isinstance(data, dict) and "error" in data:
            raise RuntimeError(f"HF error: {data.get('error')}")
        else:
            text = json.dumps(data)
        if not stream:
            return text
        for i in range(0, len(text), 128):
            yield text[i:i+128]
            time.sleep(0.01)

class OpenAIProvider(ProviderBase):
    name = "openai"
    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.model = model or _getenv("PIKIT_MODEL", "gpt-4o-mini")
        self.api_key = api_key or _getenv("PIKIT_OPENAI_API_KEY")
        self.base = base_url or _getenv("PIKIT_OPENAI_BASE", "https://api.openai.com/v1")
        if "openai.com" in self.base and not self.api_key:
            raise RuntimeError("OpenAI key missing: set PIKIT_OPENAI_API_KEY")
        self._auth_required = not _is_local_address(self.base)

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "User-Agent": _ua()}
        if self._auth_required and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def chat(self, messages: Union[str, List[Dict[str, str]]], stream: bool = False, **kwargs) -> Union[str, Iterator[str]]:
        msgs = _as_chat(messages)
        url = f"{self.base.rstrip('/')}/chat/completions"
        body = _merge_kwargs({
            "model": self.model,
            "messages": msgs,
            "temperature": float(kwargs.get("temperature", 0.7)),
            "top_p": float(kwargs.get("top_p", 0.95)),
        }, {"stream": stream})
        if not stream:
            r = requests.post(url, headers=self._headers(), json=body, timeout=_timeout())
            r.raise_for_status()
            data = r.json()
            return _extract_text(data, default=json.dumps(data))
        with requests.post(url, headers=self._headers(), json=body, timeout=_timeout(), stream=True) as resp:
            resp.raise_for_status()
            for line in _sse_lines(resp):
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    o = json.loads(data)
                    delta = o["choices"][0]["delta"].get("content")
                    if delta:
                        yield delta
                except Exception:
                    continue

class LlamaCppProvider(OpenAIProvider):
    name = "llama"
    def __init__(self, model: Optional[str] = None, base_url: Optional[str] = None):
        base = base_url or _getenv("PIKIT_LLAMA_URL", "http://127.0.0.1:8081/v1")
        super().__init__(model or _getenv("PIKIT_MODEL", "llama"), api_key=None, base_url=base)

class AIInterface:
    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None, **provider_kwargs):
        self.provider_name = (provider or _getenv("PIKIT_PROVIDER", "huggingface")).lower()
        if self.provider_name == "huggingface":
            self.provider = HuggingFaceProvider(model=model, token=provider_kwargs.get("hf_token"))
        elif self.provider_name == "openai":
            self.provider = OpenAIProvider(model=model, api_key=provider_kwargs.get("api_key"), base_url=provider_kwargs.get("base_url"))
        elif self.provider_name == "llama":
            self.provider = LlamaCppProvider(model=model, base_url=provider_kwargs.get("base_url") or _getenv("PIKIT_LLAMA_URL"))
        else:
            raise ValueError(f"Unknown provider '{self.provider_name}'")

    def chat(self, messages: Union[str, List[Dict[str, str]]], stream: bool = False, **kwargs) -> Union[str, Iterator[str]]:
        return self.provider.chat(messages, stream=stream, **kwargs)

    def query(self, prompt: str, **kwargs) -> str:
        result = self.chat(prompt, stream=False, **kwargs)
        if isinstance(result, str):
            return result
        return "".join(result)

if __name__ == "__main__":
    print("AIInterface smoke test...")
    try:
        ai = AIInterface()
        out = ai.query("In one sentence, say hello from the default provider.")
        print("OK:", out[:200])
    except Exception as e:
        print("ERROR:", e)
PY
  echo "Wrote $AI_FILE"
}

self_test() {
  echo "Self-test will import AIInterface and run a one-line prompt using the CURRENT SHELL ENV."
  echo "Tip: 'source ./use_ai_profile.sh <profile>' first to load env."
  read -rp "Run self-test now? [y/N] " yn
  if [[ "${yn,,}" != "y" ]]; then return 0; fi
  python3 - <<'PY' || { echo "Python test failed."; exit 1; }
import os, sys
print("Provider:", os.environ.get("PIKIT_PROVIDER"))
try:
    import modules.ai_interface as m
    ai = m.AIInterface()
    print("Querying...")
    out = ai.query("Say: PyKit test OK. (Keep it short.)")
    print("Reply:", out[:500])
    print("SUCCESS")
except Exception as e:
    print("ERROR:", e)
    sys.exit(1)
PY
}

main_menu() {
  while true; do
    banner
    echo "1) Create or update a profile"
    echo "2) List profiles"
    echo "3) Generate/refresh modules/ai_interface.py"
    echo "4) Load a profile into current shell (prints env)"
    echo "5) Self-test current env"
    echo "6) Quit"
    read -rp "Choose: " c
    case "${c:-}" in
      1) create_or_update_profile; pause ;;
      2) list_profiles; pause ;;
      3) generate_ai_interface_py; write_use_script; pause ;;
      4) read -rp "Profile name: " p; . "$USE_SCRIPT" "$p"; pause ;;
      5) self_test; pause ;;
      6) exit 0;;
      *) echo "Invalid choice"; pause ;;
    esac
  done
}

# Non-interactive modes:
if [[ "${1:-}" == "--apply" && -n "${2:-}" ]]; then
  generate_ai_interface_py; write_use_script
  . "$USE_SCRIPT" "$2"
  echo "Applied profile '$2' and wrote ai_interface.py"
  exit 0
fi

main_menu

