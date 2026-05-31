# modules/text_sanitizer.py
import os

_SENTENCE_ENDERS = ".!?…"
_CLOSERS = "\"'”’)]}"

def _looks_complete(text: str) -> bool:
    if not text:
        return True
    t = text.rstrip()
    if not t:
        return True
    last = t[-1]
    second_last = t[-2] if len(t) > 1 else ""
    # already ends with ., !, ?, … (optionally closed by a quote/bracket)
    return (last in _SENTENCE_ENDERS) or (last in _CLOSERS and second_last in _SENTENCE_ENDERS)

def _last_sentence_cut(t: str) -> int:
    # find last ., !, ?, or … ; return index AFTER that ender (include closers)
    idx = max(t.rfind("."), t.rfind("!"), t.rfind("?"), t.rfind("…"))
    if idx < 0:
        return -1
    idx += 1
    # include quotes/brackets immediately after punctuation
    while idx < len(t) and t[idx] in _CLOSERS:
        idx += 1
    return idx

def sanitize_ai_reply(reply, finish_reason: str | None = None) -> str:
    """
    If a reply likely ended mid-sentence (or server reported length stop),
    truncate to the last complete sentence boundary.
    - Skips code blocks (```...```) to avoid mangling code.
    - Controlled by env:
        PIKIT_TRUNCATE_INCOMPLETE (default "1")
        PIKIT_TRUNCATE_MINLEN (default "80")
        PIKIT_DEBUG_TRUNCATE (default "0")
    """
    try:
        text = reply if isinstance(reply, str) else str(reply)
    except Exception:
        return reply

    if os.getenv("PIKIT_TRUNCATE_INCOMPLETE", "1") != "1":
        return text

    if "```" in text:
        return text  # don’t touch code blocks

    t = text.rstrip()
    if not t:
        return text

    try:
        minlen = int(os.getenv("PIKIT_TRUNCATE_MINLEN", "80"))
    except Exception:
        minlen = 80

    # Only truncate if it *looks* incomplete, or server said it hit a length cap
    looks_incomplete = not _looks_complete(t)
    hit_length_cap = (finish_reason or "").lower() in {"length", "max_tokens", "token_limit"}

    if not (looks_incomplete or hit_length_cap):
        return text

    cut = _last_sentence_cut(t)
    if cut >= minlen:
        out = (t[:cut].rstrip() + "\n")
        if os.getenv("PIKIT_DEBUG_TRUNCATE", "0") == "1":
            print(f"[truncate] cut at {cut}/{len(t)} (finish_reason={finish_reason})")
        return out

    # If no sentence boundary late enough, try the last newline (keeps paragraphs intact)
    nl = t.rfind("\n")
    if nl > minlen:
        out = (t[:nl].rstrip() + "\n")
        if os.getenv("PIKIT_DEBUG_TRUNCATE", "0") == "1":
            print(f"[truncate] cut at newline {nl}/{len(t)} (finish_reason={finish_reason})")
        return out

    # Leave as-is if we can’t find a safe boundary
    return text

