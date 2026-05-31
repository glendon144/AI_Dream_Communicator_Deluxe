# modules/json_sanitizer.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Union
import json

__all__ = [
    "SanitizeOptions",
    "sanitize_json_to_plain",
    "sanitize_raw_json_string",
    "get_funkit_sanitize_options",
    "PIKIT_SANITIZE_OPTS",
]

JSONLike = Union[Mapping[str, Any], list, tuple, str, int, float, bool, None]


# ---------------------------------------------------------------------
# Options dataclass
# ---------------------------------------------------------------------

@dataclass
class SanitizeOptions:
    """
    Options controlling JSON → plain-text rendering.
    """
    # formatting
    indent: int = 2                    # spaces added per nesting level
    bullet: str = "•"                  # bullet for top-level items
    sub_bullet: str = "–"              # bullet for nested items
    kv_sep: str = ": "                 # separator between key and value
    list_inline_threshold: int = 3     # small scalar-only lists stay inline
    width: int = 0                     # soft-wrap width for string values (0 = no wrap)
    show_null: bool = False            # include nulls if True

    # behavior
    max_depth: int = 12                # safety guard
    sort_keys: bool = True             # stable ordering
    redact_keys: Iterable[str] = field(
        default_factory=lambda: {"api_key", "token", "password", "secret"}
    )
    redact_placeholder: str = "[REDACTED]"
    truncate_value_len: int = 0        # 0 = no truncation; else shorten long scalars
    allow_newlines_in_values: bool = True


# ---------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------

def _is_scalar(x: Any) -> bool:
    return isinstance(x, (str, int, float, bool)) or x is None


def _wrap(text: str, width: int, indent_prefix: str) -> str:
    if width <= 0 or "\n" in text:
        return text
    words = text.split()
    if not words:
        return text
    lines, cur = [], words[0]
    for w in words[1:]:
        if len(cur) + 1 + len(w) <= width:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return ("\n" + indent_prefix).join(lines)


def _format_scalar(val: Any, opts: SanitizeOptions, indent_prefix: str) -> str:
    if val is None:
        return "null" if opts.show_null else ""
    if isinstance(val, bool):
        return "true" if val else "false"
    s = str(val)
    if opts.truncate_value_len and len(s) > opts.truncate_value_len:
        s = s[: opts.truncate_value_len] + "…"
    return _wrap(s, opts.width, indent_prefix) if isinstance(val, str) else s


def _join_inline_list(items: list[str]) -> str:
    return ", ".join(items)


def _bullet_for_level(level: int, opts: SanitizeOptions) -> str:
    return opts.bullet if level == 0 else opts.sub_bullet


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------

def sanitize_json_to_plain(
    data: JSONLike, opts: SanitizeOptions = SanitizeOptions(), _level: int = 0
) -> str:
    """
    Convert JSON-like data into readable plain text with bullets and nesting.
    Removes braces/fences so it feels more like notes than code.
    """
    if _level > opts.max_depth:
        return f"{_bullet_for_level(_level, opts)} (max depth reached)"

    prefix = " " * (opts.indent * _level)
    line_prefix = prefix + _bullet_for_level(_level, opts) + " "

    # Mapping (dict-like)
    if isinstance(data, Mapping):
        keys = list(data.keys())
        if opts.sort_keys:
            keys.sort(key=lambda k: str(k).lower())

        redacts = {rk.lower() for rk in opts.redact_keys}
        lines: list[str] = []

        for k in keys:
            v = data[k]
            k_str = str(k)
            k_l = k_str.lower()

            if v is None and not opts.show_null:
                continue

            if k_l in redacts:
                lines.append(f"{line_prefix}{k_str}{opts.kv_sep}{opts.redact_placeholder}")
                continue

            if _is_scalar(v):
                value_text = _format_scalar(
                    v, opts, indent_prefix=(" " * (len(line_prefix) + len(k_str) + len(opts.kv_sep)))
                )
                if value_text == "" and v is None and not opts.show_null:
                    continue
                lines.append(f"{line_prefix}{k_str}{opts.kv_sep}{value_text}")
            else:
                # container → place key as a header then recurse
                lines.append(f"{line_prefix}{k_str}{opts.kv_sep}".rstrip())
                sub = sanitize_json_to_plain(v, opts, _level=_level + 1)
                if sub:
                    lines.append(sub)
        return "\n".join(lines)

    # Sequence (list/tuple)
    if isinstance(data, (list, tuple)):
        if len(data) <= opts.list_inline_threshold and all(_is_scalar(x) for x in data):
            items = [
                _format_scalar(x, opts, indent_prefix="")
                for x in data
                if x is not None or opts.show_null
            ]
            return f"{line_prefix}{_join_inline_list(items)}" if items else ""

        lines = []
        for x in data:
            if _is_scalar(x):
                val = _format_scalar(x, opts, indent_prefix=line_prefix)
                if val == "" and x is None and not opts.show_null:
                    continue
                lines.append(f"{line_prefix}{val}")
            else:
                lines.append(f"{line_prefix}".rstrip())
                lines.append(sanitize_json_to_plain(x, opts, _level=_level + 1))
        return "\n".join(filter(None, lines))

    # Scalar
    val = _format_scalar(data, opts, indent_prefix=line_prefix)
    return f"{line_prefix}{val}" if val != "" else ""


def sanitize_raw_json_string(raw: str, opts: SanitizeOptions = SanitizeOptions()) -> str:
    """
    Take a raw JSON string and return sanitized plain text.
    If parsing fails, returns the original string unchanged.
    """
    try:
        obj = json.loads(raw)
    except Exception:
        return raw
    return sanitize_json_to_plain(obj, opts)


# ---------------------------------------------------------------------
# FunKit opinionated defaults
# ---------------------------------------------------------------------

def get_funkit_sanitize_options() -> SanitizeOptions:
    """
    Defaults tuned for FunKit/DemoKit:
    - Friendly bullets
    - Stable ordering
    - Soft-wrap long strings at 88 chars
    - Truncate very long scalars at 240 chars
    - Redact common secret-like keys
    - Skip null/None by default
    """
    return SanitizeOptions(
        indent=2,
        bullet="•",
        sub_bullet="–",
        kv_sep=": ",
        list_inline_threshold=4,
        width=88,
        show_null=False,
        max_depth=12,
        sort_keys=True,
        redact_keys={
            "api_key", "apikey", "openai_api_key", "anthropic_api_key",
            "hf_token", "token", "password", "secret", "bearer", "authorization",
        },
        redact_placeholder="[REDACTED]",
        truncate_value_len=240,
        allow_newlines_in_values=True,
    )


PIKIT_SANITIZE_OPTS = get_funkit_sanitize_options()

