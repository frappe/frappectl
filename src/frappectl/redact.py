"""Hide secrets before output reaches a terminal or an agent.

Server and client scripts often carry a hardcoded API key or password. An agent
that reads a script would otherwise copy that secret into its context. This is a
best-effort pattern match, not a guarantee: the real fix is to keep secrets out
of script source.

Set ``FRAPPECTL_SHOW_SECRETS=1`` to turn redaction off. There is deliberately no
flag, so the choice to show secrets stays visible in the command's environment.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

PLACEHOLDER = "«redacted»"
SHOW_SECRETS_ENV = "FRAPPECTL_SHOW_SECRETS"

_SECRET_WORDS = {
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "credentials",
    "authorization",
    "apikey",
}
_SECRET_PAIRS = {
    ("api", "key"),
    ("access", "key"),
    ("private", "key"),
    ("secret", "key"),
}

# A secret-named value: each pattern holds the name in `name` and the value in `s`.
_NAMED_PATTERNS = [
    # name = "v", "name": "v", headers["name"] = "v", name: str = "v", name == "v"
    # Possessive quantifiers: a long run of spaces must not backtrack.
    re.compile(
        r"""(?<![\w-])(?P<name>[A-Za-z_][\w-]*+)["'`]?(?:\s*+\])?\s*+"""
        r"""(?::\s*+[\w.\[\]]++(?:[ \t]*+\|[ \t]*+[\w.\[\]]++)*+\s*+=|[=!]=|=|:)\s*+"""
        r"""(?P<q>["'`])(?P<s>(?:\\.|(?!(?P=q))[^\n\\])*+)(?P=q)"""
    ),
    # https://host/path?api_key=v&...
    re.compile(r"[?&](?P<name>[A-Za-z_][\w.-]*)=(?P<s>[^&\s\"'`#]+)"),
    # API_SECRET=v on its own line, as in .env files. Upper case only, so a Python
    # line such as `api_key=settings.key` stays readable.
    re.compile(
        r"(?m)^[ \t]*(?:export[ \t]+)?(?P<name>[A-Z][A-Z0-9_]*)=(?P<s>[^\s\"'`#]+)"
    ),
]

# Each pattern marks the secret part with the group `s`; the rest stays.
_TOKEN_PATTERNS = [
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?P<s>[\s\S]*?)-----END [A-Z ]*PRIVATE KEY-----"
    ),
    re.compile(r"\btoken\s+(?P<s>[A-Za-z0-9]{8,}:[A-Za-z0-9]{8,})"),
    re.compile(r"\b(?:Bearer|Basic)\s+(?P<s>[A-Za-z0-9\-._~+/]{16,}=*)"),
    re.compile(r"(?P<s>\beyJ[\w-]{10,}\.eyJ[\w-]{10,}\.[\w-]{10,})"),
    re.compile(r"(?P<s>\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,})"),
    re.compile(r"(?P<s>\bsk-[\w-]{20,})"),
    re.compile(r"(?P<s>\bgh[pousr]_[A-Za-z0-9]{36,}|\bgithub_pat_\w{22,})"),
    re.compile(r"(?P<s>\bxox[abprs]-[A-Za-z0-9-]{10,})"),
    re.compile(r"(?P<s>\bAKIA[0-9A-Z]{16}\b)"),
    re.compile(r"(?P<s>\bAIza[\w-]{35})"),
    re.compile(r"://[^/\s:@]+:(?P<s>[^/\s@]+)@"),
]


def redact(value: Any) -> tuple[Any, int]:
    """Return ``value`` with secrets replaced, and how many were replaced."""
    if os.environ.get(SHOW_SECRETS_ENV) == "1":
        return value, 0
    redactor = _Redactor()
    return redactor.value(value), redactor.count


def contains_placeholder(value: Any) -> bool:
    """Tell whether ``value`` still holds a redaction placeholder.

    Writing it back would replace the real secret on the site.
    """
    return PLACEHOLDER in json.dumps(value, default=str, ensure_ascii=False)


def is_secret_name(name: str) -> bool:
    """Match names that end in a secret word: ``api_secret``, not ``token_expires_at``."""
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()
    parts = [p for p in re.split(r"[^a-z0-9]+", snake) if p]
    if not parts:
        return False
    return parts[-1] in _SECRET_WORDS or tuple(parts[-2:]) in _SECRET_PAIRS


class _Redactor:
    def __init__(self) -> None:
        self.count = 0

    def value(self, value: Any, key: str | None = None, hidden: bool = False) -> Any:
        """Redact ``value``. Every string under a secret-named key is a secret."""
        hidden = hidden or (key is not None and is_secret_name(key))
        if isinstance(value, dict):
            return {k: self.value(v, str(k), hidden) for k, v in value.items()}
        if isinstance(value, list):
            return [self.value(v, hidden=hidden) for v in value]
        if not isinstance(value, str):
            return value
        if hidden and _is_real_secret(value):
            self.count += 1
            return PLACEHOLDER
        return self.text(value)

    def text(self, text: str) -> str:
        for pattern in _NAMED_PATTERNS:
            text = pattern.sub(self._replace_named, text)
        for pattern in _TOKEN_PATTERNS:
            text = pattern.sub(self._replace_group, text)
        return text

    def _replace_named(self, match: re.Match[str]) -> str:
        if not is_secret_name(match["name"]) or not _is_real_secret(match["s"]):
            return match[0]
        return self._replace_group(match)

    def _replace_group(self, match: re.Match[str]) -> str:
        if match["s"] == PLACEHOLDER:
            return match[0]
        self.count += 1
        start, end = match.start("s") - match.start(), match.end("s") - match.start()
        return match[0][:start] + PLACEHOLDER + match[0][end:]


def _is_real_secret(value: str) -> bool:
    """Skip empty values and the masks Frappe already puts on Password fields."""
    stripped = value.strip()
    return len(stripped) >= 4 and set(stripped) != {"*"} and stripped != PLACEHOLDER
