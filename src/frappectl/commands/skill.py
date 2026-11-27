"""``frappectl skill`` — list and read the Flow Skills open to the user.

Backed by Frappe's ``/api/v2/skill`` endpoints. A skill gives instructions for
one kind of task. Skills shipped by an app can also have extra files, such as
references, which ``show --file`` reads.
"""

from __future__ import annotations

from typing import Optional

import typer

from ..errors import FrappeError
from ..output import emit_list, fail, get_ctx, print_json
from ..session import get_client

app = typer.Typer(no_args_is_help=True, help="List and read skills.")

_NOT_AVAILABLE = "Skills are not available on this site."


@app.command("list")
def list_skills(ctx: typer.Context) -> None:
    """List the skills you can read, with a description of when each applies."""
    c = get_ctx(ctx)
    client = get_client(c)
    try:
        result = client.skill_list()
    except FrappeError as e:
        if e.status_code == 404:
            raise fail(_NOT_AVAILABLE)
        raise fail(e.message)

    if c.json:
        print_json(result)
        return
    emit_list(c, result["skills"], ["name", "description"], title="Skills")


@app.command("show")
def show_skill(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Skill name, e.g. 'frappe/print-formats'."),
    file: Optional[str] = typer.Option(
        None,
        "--file",
        help="Read a file of the skill, e.g. references/forms.md. A folder lists its files.",
    ),
) -> None:
    """Print a skill's instructions, or one of its files with --file."""
    c = get_ctx(ctx)
    client = get_client(c)
    try:
        result = client.skill_show(name, file)
    except FrappeError as e:
        raise fail(e.message)

    if c.json:
        print_json(result)
        return
    typer.echo(result["content"] if file else result["instructions"])
