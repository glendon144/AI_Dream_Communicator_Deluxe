from dataclasses import dataclass
from typing import Optional, Dict
import os, json

# Import TriAIInterface from your modules package
from modules.ai_interface import TriAIInterface

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

def run_tri_pipeline(user_input: str, memory: Optional[dict] = None, *, instructions: str = "") -> TriOutput:
    """Run Immediate -> Long -> Synthesis using TriAIInterface.
    - Models are controlled by env vars IMMEDIATE_MODEL, LONG_MODEL, SYNTH_MODEL (with sensible defaults).
    - API key resolution stays inside TriAIInterface (~/openai.key or set_api_key).
    """
    ai = TriAIInterface()

    # Stage 1: Immediate
    immediate_prompt = IMMEDIATE_TMPL.format(user_input=user_input)
    immediate_text = ai.query_immediate(immediate_prompt, temperature=0.2)

    # Stage 2: Long (with memory context, if any)
    memory_json = json.dumps(memory or {}, ensure_ascii=False, indent=2)
    long_prompt = LONG_TMPL.format(user_input=user_input, memory_json=memory_json)
    long_text = ai.query_longterm(long_prompt, temperature=0.2)

    # Stage 3: Synthesis
    synth_prompt = SYNTH_TMPL.format(immediate=immediate_text, long=long_text, instructions=(instructions or ""))
    final_text = ai.query_synthesis(synth_prompt, temperature=0.2)

    return TriOutput(
        immediate=immediate_text,
        long=long_text,
        final=final_text,
        models={
            "immediate": os.getenv("IMMEDIATE_MODEL", "gpt-4o-mini"),
            "long": os.getenv("LONG_MODEL", "gpt-4.1"),
            "synth": os.getenv("SYNTH_MODEL", "gpt-5"),
        },
    )
