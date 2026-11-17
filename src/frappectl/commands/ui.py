"""``frappectl ui`` — drive the person's open desk v2 tab.

Each command is one call to ``frappe.desk.ui_relay``, which forwards it to the
tab's ``window.desk``. Output is a short text summary; ``--json`` gives the
whole result. Exit 0 when done, 2 when the call waits for the person, 1 on any
other error, so a script can branch on the code alone.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, NoReturn, Optional

import typer

from .. import ui_text
from ..client import FrappeClient
from ..errors import FrappeError
from ..output import ApplicationContext, fail, get_ctx, print_json
from ..session import get_client

app = typer.Typer(
    no_args_is_help=True,
    help="Drive the person's open desk v2 tab: list tabs and acts, read state, run acts.",
)

DONE, WAITING, ERROR = 0, 2, 1

_TAB = typer.Option(
    None, "--tab", help="Tab id from `fr ui tabs`. Default: the tab focused last."
)
_OFF_TIP = (
    "The person turns this on in My Settings > Profile > Agents "
    '("Let agents drive my open tabs"), then reloads the tab.'
)


def _client(c: ApplicationContext) -> FrappeClient:
    """The profile's client; a setup error exits 1 here, as 2 means waiting."""
    try:
        return get_client(c)
    except typer.Exit as e:
        raise typer.Exit(ERROR if e.exit_code == 2 else e.exit_code)


def _failed(e: FrappeError) -> NoReturn:
    message = e.message
    if e.status_code == 403 and "agents" in message.lower():
        message = f"{message} {_OFF_TIP}"
    raise fail(message, ERROR)


def _code(result: dict[str, Any]) -> int:
    if result.get("ok"):
        return DONE
    code = (result.get("error") or {}).get("code")
    return WAITING if code == "waiting_for_user" else ERROR


def _emit(
    c: ApplicationContext,
    result: Any,
    text: Callable[[Any], str],
) -> None:
    if c.output.json_requested:
        print_json(result)
    else:
        typer.echo(text(result))
    if isinstance(result, dict):
        raise typer.Exit(_code(result))


@app.command("tabs")
def tabs(ctx: typer.Context) -> None:
    """List the open tabs that let agents drive them, the last focused first."""
    c = get_ctx(ctx)
    client = _client(c)
    try:
        rows = client.ui.tabs()
    except FrappeError as e:
        _failed(e)
    _emit(c, rows, ui_text.tabs_text)


@app.command("acts")
def acts(
    ctx: typer.Context,
    surface: Optional[str] = typer.Option(
        None, "--surface", help="Only the acts of one surface, such as `list`."
    ),
    tab: Optional[str] = _TAB,
) -> None:
    """List the acts that can run now in a tab, with what each takes."""
    args = {"surface": surface} if surface else None
    _ask(ctx, "acts", ui_text.acts_text, tab=tab, args=args)


@app.command("state")
def state(
    ctx: typer.Context,
    fields: bool = typer.Option(
        False, "--fields", help="Add the record's field values."
    ),
    tab: Optional[str] = _TAB,
) -> None:
    """Read the tab's page: route, list filters and selection, record status."""
    args = {"fields": True} if fields else None
    _ask(ctx, "state", ui_text.state_text, tab=tab, args=args)


@app.command("dialogs")
def dialogs(ctx: typer.Context, tab: Optional[str] = _TAB) -> None:
    """List the dialogs open in a tab."""
    _ask(ctx, "dialogs", ui_text.dialogs_text, tab=tab)


@app.command("run")
def run(
    ctx: typer.Context,
    act: str = typer.Argument(
        ..., help="Act name from `fr ui acts`, e.g. list.set_filters."
    ),
    value: Optional[str] = typer.Argument(
        None, help='The act\'s value as JSON, e.g. \'{"names":["A"]}\'.'
    ),
    tab: Optional[str] = _TAB,
) -> None:
    """Run an act in a tab. Exit 2 when the person must answer a dialog first."""
    args = _parse_value(value)
    _ask(ctx, "run", lambda r: ui_text.run_text(r, act), tab=tab, act=act, args=args)


@app.command("wait")
def wait(
    ctx: typer.Context,
    call: str = typer.Argument(..., help="The call id from a result that waits."),
    tab: Optional[str] = _TAB,
) -> None:
    """Wait for the person to answer a dialog, then print the act's end result."""
    _ask(ctx, "wait", ui_text.run_text, tab=tab, call_id=call)


def _parse_value(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        raise fail(f"The value is not valid JSON: {e}", ERROR)


def _ask(
    ctx: typer.Context,
    op: str,
    text: Callable[[Any], str],
    **params: Any,
) -> None:
    c = get_ctx(ctx)
    client = _client(c)
    try:
        result = client.ui.call(op, **params)
    except FrappeError as e:
        _failed(e)
    if not isinstance(result, dict):
        raise fail("The relay answered with something unexpected.", ERROR)

    def summary(r: dict[str, Any]) -> str:
        """The op's own summary; a failed call has no data, so it shows the error."""
        return text(r) if r.get("ok") else ui_text.run_text(r)

    _emit(c, result, summary)
