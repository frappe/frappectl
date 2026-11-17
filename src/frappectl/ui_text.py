"""Plain-text summaries of ``fr ui`` results.

An agent reads these, so each result is a few short lines: what happened, where
the tab is, which dialogs are open, and the next step. ``--json`` has the rest.
"""

from __future__ import annotations

import json
import re
from typing import Any

RESULT_LIMIT = 600  # characters of a result shown as text
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]+")

# What the person must do, or what to do instead, for each error code.
_NEXT = {
    "tab_not_found": "run `fr ui tabs` and pass a tab with --tab",
    "declined": "the person said no; do not retry unless they ask",
    "interrupted": "the person pressed Stop in the tab; do not call it again until they say so",
    "invalid": "fix the value to fit the act's input; `fr ui acts` shows it",
    "missing": "that act cannot run on this page now; `fr ui acts` lists what can",
    "hidden": "that act cannot run on this page now; `fr ui acts` lists what can",
    "right": "the person's role does not allow it; tell them",
}


def plain(text: Any) -> str:
    """Server text on one line. A record value must not forge a line (``next:``)."""
    return _CONTROL.sub(" ", str(text)).strip()


def compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)


def shape(schema: Any) -> str:
    """A JSON Schema as one short phrase: ``{pane?: string, block?: string}``."""
    if not isinstance(schema, dict):
        return "any"
    if "enum" in schema:
        return "|".join(compact(v) for v in schema["enum"])
    kind = schema.get("type", "any")
    kinds = kind if isinstance(kind, list) else [kind]
    parts = [_shape_of(schema, k) for k in kinds]
    return "|".join(parts)


def _shape_of(schema: dict[str, Any], kind: str) -> str:
    if kind == "object" and schema.get("properties"):
        required = set(schema.get("required") or [])
        props = schema.get("properties") or {}
        inner = ", ".join(
            f"{name}{'' if name in required else '?'}: {shape(sub)}"
            for name, sub in props.items()
        )
        return "{" + inner + "}"
    if kind == "array":
        return f"[{shape(schema['items'])}]" if "items" in schema else "array"
    return str(kind)


def clip(text: str, limit: int = RESULT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return (
        f"{text[:limit]}... ({len(text) - limit} more characters; the act has run, "
        "do not run it again to see them)"
    )


def first_sentence(text: str) -> str:
    head, sep, _ = text.partition(". ")
    return head + sep.strip() if sep else text


def tabs_text(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return (
            "No open tab answered.\n"
            "next: ask the person to open a desk v2 tab and turn on "
            '"Let agents drive my open tabs" in My Settings'
        )
    lines = [
        f"{len(rows)} open tab{'s' if len(rows) != 1 else ''}, last focused first:"
    ]
    for i, row in enumerate(rows):
        mark = "  (default)" if i == 0 else ""
        title = row.get("title") or ""
        lines.append(
            plain(f"{row.get('tab')}  {row.get('route') or ''}  {title}") + mark
        )
    return "\n".join(lines)


def acts_text(result: dict[str, Any]) -> str:
    acts = result.get("data") or []
    head = f"{len(acts)} acts can run now"
    lines = [head + _where(result)]
    for act in acts:
        about = first_sentence(act.get("description") or act.get("label") or "")
        line = f"{act.get('name')}: {about}"
        if act.get("input"):
            line += f" value {shape(act['input'])}."
        if act.get("asks"):
            line += f" asks {','.join(str(a) for a in act['asks'])}."
        lines.append(plain(line))
    lines.extend(_footer(result, show_route=False, show_tab=False))
    return "\n".join(lines)


def state_text(result: dict[str, Any]) -> str:
    facts = dict(result.get("data") or {})
    facts.pop("dialogs", None)
    lines = [f"route: {plain(facts.pop('route', result.get('route')))}"]
    for key, value in facts.items():
        if key == "fields" and isinstance(value, list):
            lines.append("fields:")
            lines.extend(_field_line(field) for field in value)
        elif isinstance(value, dict) and value:
            lines.append(f"{key}:")
            lines.extend(f"  {name}: {_inline(v)}" for name, v in value.items())
        else:
            lines.append(f"{key}: {_inline(value)}")
    lines.extend(_footer(result, show_route=False))
    return "\n".join(lines)


def _field_line(field: Any) -> str:
    if not isinstance(field, dict):
        return f"  {_inline(field)}"
    flags = [field.get("type") or ""]
    flags += ["required"] if field.get("required") else []
    flags += ["read-only"] if field.get("read_only") else []
    value = field.get("value")
    shown = "" if value is None else _inline(value)
    name = plain(field.get("fieldname"))
    return f"  {name} = {shown}  ({', '.join(f for f in flags if f)})"


def dialogs_text(result: dict[str, Any]) -> str:
    dialogs = result.get("data") or []
    lines = [f"{len(dialogs)} open dialogs" + _where(result)]
    lines.extend(_dialog_lines(dialogs))
    lines.extend(_footer(result, show_route=False, show_tab=False, dialogs=False))
    return "\n".join(lines)


def run_text(result: dict[str, Any], act: str | None = None) -> str:
    """The summary of a ``run`` or ``wait`` result."""
    error = result.get("error") or {}
    if result.get("ok"):
        lines = [f"ok: {act}" if act else "ok"]
        if result.get("data") is not None:
            lines.append(f"result: {clip(compact(result['data']))}")
    else:
        lines = [plain(f"error {error.get('code')}: {error.get('message') or ''}")]
    lines.extend(_footer(result, show_route=True, error=error))
    return "\n".join(lines)


def _where(result: dict[str, Any]) -> str:
    return f" in tab {plain(result['tab'])}" if result.get("tab") else ""


def _inline(value: Any) -> str:
    return plain(value) if isinstance(value, str) else compact(value)


def _footer(
    result: dict[str, Any],
    *,
    show_route: bool,
    show_tab: bool = True,
    error: dict[str, Any] | None = None,
    dialogs: bool = True,
) -> list[str]:
    lines = []
    if show_route and result.get("route"):
        lines.append(f"route: {plain(result['route'])}")
    if show_tab and result.get("tab"):
        lines.append(f"tab: {plain(result['tab'])}")
    shown = list(result.get("dialogs") or []) if dialogs else []
    asked = (error or {}).get("dialog")
    if asked and all(d.get("id") != asked.get("id") for d in shown):
        shown.append(asked)
    if shown:
        lines.append(f"dialogs: {len(shown)} open")
        lines.extend(_dialog_lines(shown))
    step = _next_step(result, error or {}, shown)
    if step:
        lines.append(f"next: {step}")
    return lines


def _dialog_lines(dialogs: list[dict[str, Any]]) -> list[str]:
    lines = []
    for d in dialogs:
        text = " ".join(x for x in (d.get("title"), d.get("message")) if x)
        lines.append("  " + plain(f"#{d.get('id')} {d.get('kind')}: {text}"))
        if d.get("buttons"):
            buttons = ", ".join(plain(b) for b in d["buttons"])
            lines.append(f"    buttons: {buttons}")
        if d.get("values"):
            lines.append(f"    values: {compact(d['values'])}")
    return lines


def _next_step(
    result: dict[str, Any], error: dict[str, Any], dialogs: list[dict[str, Any]]
) -> str:
    code = error.get("code")
    if code == "waiting_for_user":
        again = f"run `fr ui wait {plain(error.get('call') or '<call>')}`"
        if not dialogs:
            return f"the tab has not finished; {again} again"
        return (
            "the person must answer the dialog in the tab; never answer it yourself. "
            f"Then {again}"
        )
    if code in _NEXT:
        return _NEXT[code]
    if not error and any(d.get("kind") in ("confirm", "danger") for d in dialogs):
        return "the person must answer the open dialog in the tab; never answer it yourself"
    if not error and dialogs:
        return "a dialog is open; its acts are in `fr ui acts`"
    return ""
