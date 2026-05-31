from dataclasses import dataclass
from typing import Optional, Dict
import os, json

# Prefer the modern OpenAI SDK; fall back to legacy
try:
    from openai import OpenAI
    _NEW = True
except Exception:
    import openai
    OpenAI = None
    _NEW = False

DEFAULT_IMMEDIATE = os.getenv("IMMEDIATE_MODEL", "gpt-4o-mini")
DEFAULT_LONG      = os.getenv("LONG_MODEL", "o3-mini")
DEFAULT_SYNTH     = os.getenv("SYNTH_MODEL", "gpt-5")  # change to gpt-4.1 if gpt-5 not enabled

def _get_client():
    if _NEW:
        return OpenAI()
    openai.api_key = os.getenv("OPENAI_API_KEY")
    return openai

def _extract_text(resp):
    text = getattr(resp, "output_text", None)
    if text:
        return text.strip()
    try:
        return resp.choices[0].message["content"].strip()
    except Exception:
        return str(resp)

def call_model(model: str, prompt: str, max_tokens: int = 800, reasoning_effort: Optional[str] = None):
    client = _get_client()
    if _NEW:
        try:
            kwargs = {"model": model, "input": prompt, "max_output_tokens": max_tokens}
            if reasoning_effort:
                kwargs["reasoning"] = {"effort": reasoning_effort}
            resp = client.responses.create(**kwargs)
            return _extract_text(resp)
        except Exception:
            # Safe fallback for unavailable models
            resp = client.responses.create(model="gpt-4.1", input=prompt, max_output_tokens=max_tokens)
            return _extract_text(resp)

    # Legacy Chat Completions fallback
    try:
        resp = client.ChatCompletion.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=max_tokens,
        )
        return _extract_text(resp)
    except Exception:
        resp = client.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=max_tokens,
        )
        return _extract_text(resp)

IMMEDIATE_TMPL = """You are ImmediateContext: return a VERY SHORT take (<= 60 words) that captures the user's key intent and next steps. Use bullets only; no fluff.

USER INPUT:
{user_input}
"""

LONG_TMPL = """You are LongContext: write a thoughtful, well-structured analysis (200–500 words).
- Connect to any relevant PRIOR MEMORY if present.
- Identify trade-offs, risks, open questions.
- Propose a short action plan (3–7 steps).

PRIOR MEMORY (JSON, may be empty):
{memory_json}

USER INPUT:
{user_input}
"""

SYNTH_TMPL = """You are Synthesis: merge the IMMEDIATE and LONG results into one crisp output.
Sections:
1) TL;DR (<=3 bullets)
2) Plan (numbered steps)
3) Notes & Risks (bullets)
4) (Optional) Tiny example or template

IMMEDIATE RESULT:
{immediate}

LONG RESULT:
{long}

USER INSTRUCTIONS (optional):
{instructions}
"""

@dataclass
class TriOutput:
    immediate: str
    long: str
    final: str
    models: Dict[str, str]

def run_tri_pipeline(
    user_input: str,
    memory: Optional[dict] = None,
    *,
    instructions: str = "",
    immediate_model: str = DEFAULT_IMMEDIATE,
    long_model: str = DEFAULT_LONG,
    synth_model: str = DEFAULT_SYNTH
) -> TriOutput:
    immediate = call_model(
        immediate_model,
        IMMEDIATE_TMPL.format(user_input=user_input),
        max_tokens=300
    )
    long = call_model(
        long_model,
        LONG_TMPL.format(
            user_input=user_input,
            memory_json=json.dumps(memory or {}, ensure_ascii=False, indent=2)
        ),
        max_tokens=1200,
        reasoning_effort="medium"
    )
    final = call_model(
        synth_model,
        SYNTH_TMPL.format(immediate=immediate, long=long, instructions=instructions),
        max_tokens=1600,
        reasoning_effort="high"
    )
    return TriOutput(
        immediate=immediate,
        long=long,
        final=final,
        models={"immediate": immediate_model, "long": long_model, "synth": synth_model}
    )
