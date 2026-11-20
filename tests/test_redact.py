import json

import httpx
import pytest
from typer.testing import CliRunner

from frappectl.cli import app
from frappectl.redact import PLACEHOLDER, SHOW_SECRETS_ENV, is_secret_name, redact

BASE = "http://localhost"
runner = CliRunner()

SCRIPT = """\
api_key = "a1b2c3d4e5f6g7h"
api_secret = 'z9y8x7w6v5u4t3s'
headers = {"Authorization": "token a1b2c3d4e5f6g7h:z9y8x7w6v5u4t3s"}
settings = frappe.get_single("My Settings")
password = settings.get_password("password")
if status == "Open":
    frappe.msgprint("done")
"""


@pytest.fixture(autouse=True)
def redaction_on(monkeypatch):
    monkeypatch.delenv(SHOW_SECRETS_ENV, raising=False)


def test_redacts_hardcoded_assignments_in_a_script():
    clean, count = redact(SCRIPT)
    assert count == 3
    assert "a1b2c3d4e5f6g7h" not in clean
    assert "z9y8x7w6v5u4t3s" not in clean
    assert f'api_key = "{PLACEHOLDER}"' in clean
    assert f'"Authorization": "{PLACEHOLDER}"' in clean


def test_keeps_code_that_holds_no_literal_secret():
    clean, _ = redact(SCRIPT)
    assert 'password = settings.get_password("password")' in clean
    assert 'if status == "Open":' in clean


@pytest.mark.parametrize(
    "text,secret",
    [
        ("Authorization: token abcd1234efgh:ijkl5678mnop", "abcd1234efgh:ijkl5678mnop"),
        ("Bearer abcdefghijklmnopqrstuvwxyz012345", "abcdefghijklmnopqrstuvwxyz012345"),
        ("key sk_live_" + "a" * 24, "sk_live_" + "a" * 24),
        ("ghp_" + "A" * 36, "ghp_" + "A" * 36),
        ("AKIAABCDEFGHIJKLMNOP", "AKIAABCDEFGHIJKLMNOP"),
        ("eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4", "eyJhbGciOiJIUzI1"),
        ("https://admin:hunter22@example.com/x", "hunter22"),
        (
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----",
            "MIIEow",
        ),
    ],
)
def test_redacts_known_token_shapes_anywhere(text, secret):
    clean, count = redact(text)
    assert count == 1
    assert secret not in clean


def test_redacts_secret_named_keys_in_documents():
    doc = {"name": "S", "api_secret": "z9y8x7w6", "new_password": "*****", "title": "x"}
    clean, count = redact(doc)
    assert count == 1
    assert clean == {**doc, "api_secret": PLACEHOLDER}


def test_redacts_nested_script_fields():
    rows = [{"name": "A", "script": 'token = "abcdef123456"'}]
    clean, count = redact(rows)
    assert count == 1
    assert clean[0]["script"] == f'token = "{PLACEHOLDER}"'


@pytest.mark.parametrize(
    "name,expected",
    [
        ("api_secret", True),
        ("apiKey", True),
        ("client_secret", True),
        ("Authorization", True),
        ("access_key", True),
        ("new_password", True),
        ("token_expires_at", False),
        ("secretary", False),
        ("passport_no", False),
        ("auth", False),
        ("key", False),
    ],
)
def test_is_secret_name(name, expected):
    assert is_secret_name(name) is expected


def test_env_var_turns_redaction_off(monkeypatch):
    monkeypatch.setenv(SHOW_SECRETS_ENV, "1")
    assert redact(SCRIPT) == (SCRIPT, 0)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("FRAPPE_SITE", BASE)
    monkeypatch.setenv("FRAPPE_API_KEY", "k")
    monkeypatch.setenv("FRAPPE_API_SECRET", "s")


def test_doc_get_redacts_a_server_script(httpx2_mock, env):
    doc = {"name": "Sync", "script": SCRIPT}
    httpx2_mock.get(f"{BASE}/api/v2/document/Server Script/Sync/").mock(
        return_value=httpx.Response(200, json={"data": doc})
    )
    result = runner.invoke(app, ["--json", "doc", "get", "Server Script", "Sync"])
    assert result.exit_code == 0
    assert "z9y8x7w6v5u4t3s" not in result.stdout
    assert json.loads(result.stdout)["script"].count(PLACEHOLDER) == 3
    assert f"redacted 3 secrets; set {SHOW_SECRETS_ENV}=1" in result.stderr


def test_doc_update_refuses_to_write_back_a_placeholder(httpx2_mock, env):
    body = json.dumps({"script": f'api_secret = "{PLACEHOLDER}"'})
    result = runner.invoke(
        app, ["--json", "doc", "update", "Server Script", "Sync"], input=body
    )
    assert result.exit_code == 2
    assert "overwrite the real value" in result.stderr
    assert not httpx2_mock.calls


def test_method_call_refuses_a_placeholder_param(httpx2_mock, env):
    result = runner.invoke(
        app, ["method", "call", "x.y", "-f", f"secret={PLACEHOLDER}"]
    )
    assert result.exit_code == 2
    assert not httpx2_mock.calls


def test_api_post_refuses_a_placeholder_body(httpx2_mock, env):
    result = runner.invoke(
        app,
        [
            "api",
            "document/Server Script",
            "-X",
            "POST",
            "-F",
            f"script=token = '{PLACEHOLDER}'",
        ],
    )
    assert result.exit_code == 2
    assert not httpx2_mock.calls


def test_tty_record_is_redacted(capsys):
    from frappectl.output import render_record

    render_record({"name": "S", "script": 'api_secret = "z9y8x7w6v5u4"'})
    assert "z9y8x7w6v5u4" not in capsys.readouterr().out
