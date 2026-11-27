import json

import pytest
from typer.testing import CliRunner

from frappectl.cli import app

BASE = "http://localhost"
SKILL_URL = f"{BASE}/api/v2/skill/frappe%2Fprint-formats"
runner = CliRunner()

SKILLS = {
    "skills": [
        {"name": "frappe/print-formats", "description": "Create a print format."}
    ]
}
SKILL = {
    "name": "frappe/print-formats",
    "description": "Create a print format.",
    "instructions": "# Print formats\n\nStart from the standard format.",
}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("FRAPPE_SITE", BASE)
    monkeypatch.setenv("FRAPPE_API_KEY", "k")
    monkeypatch.setenv("FRAPPE_API_SECRET", "s")


def _force_human_output(monkeypatch):
    """CliRunner never presents a TTY, so swap in a Ctx that reports one."""
    from frappectl import cli as cli_mod
    from frappectl.output import Ctx

    def make_ctx(**kwargs):
        kwargs["json_mode"] = False
        c = Ctx(**kwargs)
        c.json = False
        c.is_tty = True
        return c

    monkeypatch.setattr(cli_mod, "Ctx", make_ctx)


def test_skill_list_json_is_the_api_object(httpx2_mock, env):
    httpx2_mock.get(f"{BASE}/api/v2/skill").respond(200, json={"data": SKILLS})
    result = runner.invoke(app, ["--json", "skill", "list"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == SKILLS


def test_skill_list_renders_a_table_on_tty(httpx2_mock, env, monkeypatch):
    _force_human_output(monkeypatch)
    httpx2_mock.get(f"{BASE}/api/v2/skill").respond(200, json={"data": SKILLS})
    result = runner.invoke(app, ["skill", "list"])
    assert result.exit_code == 0, result.output
    assert "frappe/print-formats" in result.stdout
    assert "Create a print format." in result.stdout


def test_skill_list_without_the_api_says_so(httpx2_mock, env):
    httpx2_mock.get(f"{BASE}/api/v2/skill").respond(404)
    result = runner.invoke(app, ["skill", "list"])
    assert result.exit_code == 1
    assert "Skills are not available on this site." in result.stderr


def test_skill_show_prints_the_markdown_on_tty(httpx2_mock, env, monkeypatch):
    _force_human_output(monkeypatch)
    route = httpx2_mock.get(SKILL_URL).respond(200, json={"data": SKILL})
    result = runner.invoke(app, ["skill", "show", "frappe/print-formats"])
    assert result.exit_code == 0, result.output
    assert result.stdout == SKILL["instructions"] + "\n"
    assert "file" not in route.calls.last.request.url.params


def test_skill_show_reads_a_file(httpx2_mock, env, monkeypatch):
    _force_human_output(monkeypatch)
    content = {
        "name": "frappe/print-formats",
        "file": "references/jinja.md",
        "content": "Use Jinja.",
    }
    route = httpx2_mock.get(SKILL_URL).respond(200, json={"data": content})
    result = runner.invoke(
        app,
        ["skill", "show", "frappe/print-formats", "--file", "references/jinja.md"],
    )
    assert result.exit_code == 0, result.output
    assert result.stdout == "Use Jinja.\n"
    assert route.calls.last.request.url.params["file"] == "references/jinja.md"


def test_skill_show_json_is_the_api_object(httpx2_mock, env):
    httpx2_mock.get(SKILL_URL).respond(200, json={"data": SKILL})
    result = runner.invoke(app, ["--json", "skill", "show", "frappe/print-formats"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == SKILL
