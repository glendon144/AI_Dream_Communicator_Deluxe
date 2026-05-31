# modules/ai_interface.py
from __future__ import annotations

# ---- optional local provider ----
try:
    from modules.local_ai_interface import Local_AI_Interface as _Local
    _local_available = True
except Exception:
    try:
        from modules.local_ai_interface import LocalAIInterface as _Local  # type: ignore
        _local_available = True
    except Exception:
        _local_available = False
        _Local = None  # type: ignore
# ---------------------------------

import os
import json
import time
import logging
import random
import configparser
from pathlib import Path
from typing import Generator, Iterable

import requests

# ---- optional OpenAI SDK ----
try:
    import openai  # type: ignore
    _openai_available = True
except Exception:
    _openai_available = False

# ---- provider-level logger ----
_prov_logger = logging.getLogger("funkit.ai.providers")
if not _prov_logger.handlers:
    _prov_logger.setLevel(logging.INFO)
    try:
        _pfh = logging.FileHandler("ai_query.log", encoding="utf-8")
        _pfh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        _prov_logger.addHandler(_pfh)
    except Exception:
        _psh = logging.StreamHandler()
        _psh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        _prov_logger.addHandler(_psh)

# ---- helpers ----
def _read_settings() -> dict:
    try:
        p = Path("funkit_settings.json")
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _load_user_config() -> tuple[configparser.ConfigParser, Path]:
    """Load ~/.funkit/funkit.conf (create with defaults if missing)."""
    home_cfg_dir = Path.home() / ".funkit"
    cfg_path = home_cfg_dir / "funkit.conf"
    cp = configparser.ConfigParser()
    if not cfg_path.exists():
        home_cfg_dir.mkdir(parents=True, exist_ok=True)
        template = "; FunKit configuration (INI)\n" \
                   "; Location: ~/.funkit/funkit.conf\n" \
                   "; Lines starting with ';' or '#' are comments.\n\n" \
                   "[core]\n" \
                   "; Default provider on startup: openai | baseten | local\n" \
                   "provider = openai\n\n" \
                   "[openai]\n" \
                   "api_key = \n\n" \
                   "[baseten]\n" \
                   "; Baseten OpenAI-compatible inference base URL (recommended)\n" \
                   "url = https://inference.baseten.co/v1\n" \
                   "; Human-readable model NAME for inference gateway (e.g., openai/gpt-oss-120b)\n" \
                   "model = openai/gpt-oss-120b\n" \
                   "; API key for Baseten\n" \
                   "api_key = \n" \
                   "; Transport selection: auto | sdk | http\n" \
                   "transport = auto\n" \
                   "; Endpoint mode for HTTP: base | chat | responses | auto\n" \
                   "endpoint_mode = base\n\n" \
                   "[local]\n" \
                   "; Reserved for local settings (if needed)\n" \
                   "; endpoint = http://localhost:11434/v1\n"
        cfg_path.write_text(template, encoding="utf-8")
    cp.read(cfg_path)
    return cp, cfg_path

class AIInterface:
    def __init__(self, provider: str | None = None):
        cp, _ = _load_user_config()

        # Provider: config -> env -> arg -> default
        prov_cfg = cp.get("core", "provider", fallback="").strip().lower()
        prov_env = os.environ.get("AI_PROVIDER", "").strip().lower()
        self.provider = (prov_cfg or prov_env or (provider or "openai")).lower()

        # OpenAI
        self.openai_key = cp.get("openai", "api_key", fallback="") or os.environ.get("OPENAI_API_KEY", "")

        # Baseten
        self.baseten_key = cp.get("baseten", "api_key", fallback="") or os.environ.get("BASETEN_API_KEY", "")
        self.baseten_url = (
            cp.get("baseten", "url", fallback="").strip()
            or os.environ.get("BASETEN_URL", "").strip()
            or "https://inference.baseten.co/v1"
        )
        self.baseten_transport = (cp.get("baseten", "transport", fallback="auto").strip().lower()
                                  or os.environ.get("BASETEN_TRANSPORT", "auto").strip().lower())
        self.baseten_endpoint_mode = (cp.get("baseten", "endpoint_mode", fallback="base").strip().lower()
                                      or os.environ.get("BASETEN_ENDPOINT_MODE", "base").strip().lower())
        self._baseten_model_cfg = cp.get("baseten", "model", fallback="").strip()

        # Local provider instance holder
        self._local = None

    # -------- Public API --------
    def set_provider(self, provider: str) -> None:
        self.provider = (provider or "openai").lower()
        if self.provider == "baseten" and not (self.baseten_url or "").strip():
            self.baseten_url = "https://inference.baseten.co/v1"

    def get_provider(self) -> str:
        return self.provider

    def query(self, prompt: str, stream: bool = False, **kwargs):
        pid = random.getrandbits(32)
        _prov_logger.info("DISPATCH provider=%s id=%s", self.provider, pid)

        prov = self.provider
        if prov == "openai":
            return self._query_openai(prompt, stream=stream, **kwargs)
        elif prov == "baseten":
            return self._query_baseten(prompt, stream=stream, **kwargs)
        elif prov == "local":
            return self._query_local(prompt, stream=stream, **kwargs)
        else:
            raise ValueError(f"Unknown provider: {prov}")

    # -------- Provider: OpenAI --------
    def _query_openai(self, prompt: str, stream: bool = False, **kwargs):
        _provider = "openai"
        _model = str(kwargs.get("model", "gpt-4o"))
        _endpoint = "https://api.openai.com/v1/chat/completions"
        _t0 = time.perf_counter()
        _prov_logger.info("START provider=%s model=%s endpoint=%s", _provider, _model, _endpoint)

        temperature = kwargs.get("temperature", 0.3)
        system_prompt = kwargs.get("system_prompt", "You are a helpful assistant.")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        if _openai_available:
            try:
                openai.api_key = self.openai_key  # type: ignore[attr-defined]

                if stream:
                    response = openai.ChatCompletion.create(  # type: ignore[attr-defined]
                        model=_model,
                        messages=messages,
                        temperature=temperature,
                        stream=True,
                    )

                    def _gen() -> Generator[str, None, None]:
                        total_len = 0
                        try:
                            for chunk in response:
                                content = chunk["choices"][0].get("delta", {}).get("content")
                                if content:
                                    total_len += len(content)
                                    yield content
                        finally:
                            elapsed_ms = int((time.perf_counter() - _t0) * 1000)
                            _prov_logger.info("END provider=%s model=%s endpoint=%s elapsed_ms=%s resp_len=%s",
                                              _provider, _model, _endpoint, elapsed_ms, total_len)
                    return _gen()

                response = openai.ChatCompletion.create(  # type: ignore[attr-defined]
                    model=_model,
                    messages=messages,
                    temperature=temperature,
                    stream=False,
                )
                text = response["choices"][0]["message"]["content"]
                elapsed_ms = int((time.perf_counter() - _t0) * 1000)
                _prov_logger.info("END provider=%s model=%s endpoint=%s elapsed_ms=%s resp_len=%s",
                                  _provider, _model, _endpoint, elapsed_ms, len(text or ""))
                return text
            except Exception:
                pass

        headers = {"Authorization": f"Bearer {self.openai_key}", "Content-Type": "application/json"}
        data = {"model": _model, "messages": messages, "temperature": temperature, "stream": bool(stream)}
        try:
            if stream:
                with requests.post(_endpoint, headers=headers, json=data, stream=True, timeout=300) as resp:
                    resp.raise_for_status()

                    def _gen_lines(it: Iterable[bytes]) -> Generator[str, None, None]:
                        total_len = 0
                        try:
                            for raw in it:
                                if not raw:
                                    continue
                                line = raw.lstrip(b"data: ").decode("utf-8", "ignore")
                                if not line or line.strip() == "[DONE]":
                                    continue
                                try:
                                    obj = json.loads(line)
                                    delta = (obj.get("choices") and obj["choices"][0]["delta"].get("content")) or None
                                    if delta:
                                        total_len += len(delta)
                                        yield delta
                                except Exception:
                                    continue
                        finally:
                            elapsed_ms = int((time.perf_counter() - _t0) * 1000)
                            _prov_logger.info("END provider=%s model=%s endpoint=%s elapsed_ms=%s resp_len=%s",
                                              _provider, _model, _endpoint, elapsed_ms, total_len)
                    return _gen_lines(resp.iter_lines())
            else:
                resp = requests.post(_endpoint, headers=headers, json=data, timeout=300)
                resp.raise_for_status()
                obj = resp.json()
                text = obj["choices"][0]["message"]["content"]
                elapsed_ms = int((time.perf_counter() - _t0) * 1000)
                _prov_logger.info("END provider=%s model=%s endpoint=%s elapsed_ms=%s resp_len=%s",
                                  _provider, _model, _endpoint, elapsed_ms, len(text or ""))
                return text
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - _t0) * 1000)
            _prov_logger.exception("ERROR provider=%s model=%s endpoint=%s elapsed_ms=%s",
                                   _provider, _model, _endpoint, elapsed_ms)
            raise RuntimeError(f"OpenAI HTTP error: {e}") from e

    # -------- Provider: Baseten --------
    def _resolve_baseten_model(self, kwargs) -> str:
        m = kwargs.get("model")
        if not m:
            m = self._baseten_model_cfg
        if not m:
            m = os.environ.get("BASETEN_MODEL") or os.environ.get("BASETEN_MODEL_NAME")
        if not m:
            cfg = _read_settings()
            m = (cfg.get("baseten") or {}).get("model") or (cfg.get("baseten") or {}).get("name")
        if not m:
            m = kwargs.get("mistral_model")
        if not m:
            raise RuntimeError(
                "Baseten model name is required. Set one of: "
                "kwargs['model'], baseten.model in ~/.funkit/funkit.conf, "
                "BASETEN_MODEL env var, or kwargs['mistral_model']."
            )
        return str(m)

    def _choose_baseten_endpoint(self, base_url: str, mode: str) -> tuple[str, str]:
        base = (base_url or "").rstrip("/")
        if mode == "base":
            return base, "base"
        if mode == "chat":
            return f"{base}/chat/completions", "chat"
        if mode == "responses":
            return f"{base}/responses", "responses"
        if "inference.baseten.co" in base:
            return base, "base"
        if "/model_versions/" in base:
            return base, "legacy"
        if base.endswith("/chat/completions") or base.endswith("/responses"):
            return base, "explicit"
        return f"{base}/chat/completions", "chat-fallback"

    def _query_baseten(self, prompt: str, stream: bool = False, **kwargs):
        _provider = "baseten"
        _model = self._resolve_baseten_model(kwargs)
        url = (self.baseten_url or "").strip()
        transport = (self.baseten_transport or "auto").lower()
        endpoint, endpoint_mode = self._choose_baseten_endpoint(url, (self.baseten_endpoint_mode or "base").lower())
        _t0 = time.perf_counter()
        _prov_logger.info("START provider=%s model=%s endpoint=%s transport=%s mode=%s",
                          _provider, _model, endpoint, transport, endpoint_mode)

        temperature = kwargs.get("temperature", 0.3)
        system_prompt = kwargs.get("system_prompt", "You are a helpful assistant.")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        if ("inference.baseten.co" in url) and (transport in ("auto", "sdk")) and _openai_available:
            try:
                try:
                    openai.api_key = self.baseten_key  # type: ignore[attr-defined]
                    try:
                        openai.api_base = url  # type: ignore[attr-defined]
                    except Exception:
                        pass
                except Exception:
                    pass

                if stream:
                    response = openai.ChatCompletion.create(  # type: ignore[attr-defined]
                        model=_model,
                        messages=messages,
                        temperature=temperature,
                        stream=True,
                    )

                    def _gen() -> Generator[str, None, None]:
                        total_len = 0
                        try:
                            for chunk in response:
                                content = chunk["choices"][0].get("delta", {}).get("content")
                                if content:
                                    total_len += len(content)
                                    yield content
                        finally:
                            elapsed_ms = int((time.perf_counter() - _t0) * 1000)
                            _prov_logger.info("END provider=%s model=%s endpoint=%s elapsed_ms=%s resp_len=%s",
                                              _provider, _model, url, elapsed_ms, total_len)
                    return _gen()

                response = openai.ChatCompletion.create(  # type: ignore[attr-defined]
                    model=_model,
                    messages=messages,
                    temperature=temperature,
                    stream=False,
                )
                text = response["choices"][0]["message"]["content"]
                elapsed_ms = int((time.perf_counter() - _t0) * 1000)
                _prov_logger.info("END provider=%s model=%s endpoint=%s elapsed_ms=%s resp_len=%s",
                                  _provider, _model, url, elapsed_ms, len(text or ""))
                return text
            except Exception as e:
                if transport == "sdk":
                    elapsed_ms = int((time.perf_counter() - _t0) * 1000)
                    _prov_logger.exception("ERROR provider=%s model=%s endpoint=%s elapsed_ms=%s",
                                           _provider, _model, url, elapsed_ms)
                    raise RuntimeError(f"Baseten(OpenAI SDK) error: {e}") from e

        try:
            if "inference.baseten.co" in url:
                headers = {"Authorization": f"Bearer {self.baseten_key}", "Content-Type": "application/json"}
                payload = {"model": _model, "messages": messages, "temperature": temperature, "stream": bool(stream)}
            else:
                headers = {"Authorization": f"Api-Key {self.baseten_key}", "Content-Type": "application/json"}
                payload = {"prompt": prompt, "temperature": temperature, "stream": bool(stream)}

            if stream:
                with requests.post(endpoint, headers=headers, json=payload, stream=True, timeout=300) as resp:
                    try:
                        resp.raise_for_status()
                    except Exception:
                        raise RuntimeError(f"{resp.status_code} {resp.reason}: {endpoint} :: {resp.text[:200]}")

                    if "inference.baseten.co" in url:
                        def _gen_lines(it: Iterable[bytes]) -> Generator[str, None, None]:
                            total_len = 0
                            try:
                                for raw in it:
                                    if not raw:
                                        continue
                                    line = raw.lstrip(b"data: ").decode("utf-8", "ignore")
                                    if not line or line.strip() == "[DONE]":
                                        continue
                                    try:
                                        obj = json.loads(line)
                                        delta = (obj.get("choices") and obj["choices"][0]["delta"].get("content")) or None
                                        if delta:
                                            total_len += len(delta)
                                            yield delta
                                    except Exception:
                                        continue
                            finally:
                                elapsed_ms = int((time.perf_counter() - _t0) * 1000)
                                _prov_logger.info("END provider=%s model=%s endpoint=%s elapsed_ms=%s resp_len=%s",
                                                  _provider, _model, endpoint, elapsed_ms, total_len)
                        return _gen_lines(resp.iter_lines())
                    else:
                        def _gen_legacy(it: Iterable[bytes]) -> Generator[str, None, None]:
                            total_len = 0
                            try:
                                for raw in it:
                                    if not raw:
                                        continue
                                    s = raw.decode("utf-8", "ignore")
                                    if not s.strip():
                                        continue
                                    total_len += len(s)
                                    yield s
                            finally:
                                elapsed_ms = int((time.perf_counter() - _t0) * 1000)
                                _prov_logger.info("END provider=%s model=%s endpoint=%s elapsed_ms=%s resp_len=%s",
                                                  _provider, _model, endpoint, elapsed_ms, total_len)
                        return _gen_legacy(resp.iter_lines())

            resp = requests.post(endpoint, headers=headers, json=payload, timeout=300)
            try:
                resp.raise_for_status()
            except Exception:
                raise RuntimeError(f"{resp.status_code} {resp.reason}: {endpoint} :: {resp.text[:200]}")

            if "inference.baseten.co" in url:
                obj = resp.json()
                text = obj["choices"][0]["message"]["content"]
            else:
                obj = resp.json()
                text = obj.get("text") or obj.get("output") or obj.get("response") or json.dumps(obj)[:2000]

            elapsed_ms = int((time.perf_counter() - _t0) * 1000)
            _prov_logger.info("END provider=%s model=%s endpoint=%s elapsed_ms=%s resp_len=%s",
                              _provider, _model, endpoint, elapsed_ms, len(text or ""))
            return text

        except Exception as e:
            elapsed_ms = int((time.perf_counter() - _t0) * 1000)
            _prov_logger.exception("ERROR provider=%s model=%s endpoint=%s elapsed_ms=%s",
                                   _provider, _model, endpoint, elapsed_ms)
            raise RuntimeError(f"Baseten error: {e}") from e

    # -------- Provider: Local (bridged) --------
    def _query_local(self, prompt: str, stream: bool = False, **kwargs):
        if not _local_available:
            raise RuntimeError("Local provider requested but Local_AI_Interface not available")
        if getattr(self, "_local", None) is None:
            self._local = _Local()
        return self._local.query(prompt, stream=stream, **kwargs)