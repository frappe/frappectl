"""Name the LLM agent that runs frappectl, for the ``X-Frappe-Agent`` header.

Frappe records this name in Version, so the form timeline shows which changes an
agent made for the user. The server ignores the header on cookie sessions.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

HEADER = "X-Frappe-Agent"

# The server keeps at most this many characters.
_MAX_LENGTH = 140

# Agent harnesses set these variables in the shells they start. The first match
# wins, so put the more specific markers first.
_MARKERS: list[tuple[tuple[str, ...], str]] = [
    (("CLAUDECODE",), "Claude Code"),
    (("CODEX_THREAD_ID", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED"), "Codex"),
    (("GEMINI_CLI",), "Gemini CLI"),
    (("CURSOR_AGENT",), "Cursor"),
    (("OPENCODE", "OPENCODE_CLIENT"), "opencode"),
    (("AUGMENT_AGENT",), "Augment"),
]

# `AI_AGENT` is a shared convention, for example `claude-code_2-1-3_agent`.
# The first segment is the slug; map known slugs to the names people use.
_SLUG_NAMES = {
    "claude-code": "Claude Code",
    "claude": "Claude Code",
    "codex": "Codex",
    "gemini": "Gemini CLI",
    "gemini-cli": "Gemini CLI",
    "cursor": "Cursor",
    "cursor-cli": "Cursor",
    "opencode": "opencode",
    "augment-cli": "Augment",
}


def detect(environ: Mapping[str, str] | None = None) -> str | None:
    """The agent name to send, or None when no agent runs frappectl.

    ``FRAPPE_AGENT`` wins over detection. Set it to an empty value to send no
    name, for example when a person runs a command from an agent's shell.
    """
    env = os.environ if environ is None else environ

    if "FRAPPE_AGENT" in env:
        return _clean(env["FRAPPE_AGENT"])

    for names, agent in _MARKERS:
        if any(env.get(name) for name in names):
            return agent

    if ai_agent := _clean(env.get("AI_AGENT", "")):
        slug = ai_agent.split("_", 1)[0]
        return _SLUG_NAMES.get(slug.lower(), slug)

    return None


def _clean(value: str) -> str | None:
    # A header value must be printable ASCII; a newline would also let the
    # value inject other headers.
    text = "".join(c for c in value if " " <= c <= "~")
    text = " ".join(text.split())[:_MAX_LENGTH].strip()
    return text or None
