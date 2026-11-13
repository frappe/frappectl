import httpx
import pytest

from frappectl import agent
from frappectl.client import FrappeClient

BASE = "http://localhost"


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, None),
        ({"CLAUDECODE": "1"}, "Claude Code"),
        ({"CODEX_SANDBOX": "seatbelt"}, "Codex"),
        ({"GEMINI_CLI": "1"}, "Gemini CLI"),
        ({"AI_AGENT": "claude-code_2-1-3_agent"}, "Claude Code"),
        ({"AI_AGENT": "my-bot_1_agent"}, "my-bot"),
        ({"FRAPPE_AGENT": "Nightly sync", "CLAUDECODE": "1"}, "Nightly sync"),
        ({"FRAPPE_AGENT": "", "CLAUDECODE": "1"}, None),
        ({"FRAPPE_AGENT": "bad\r\nX-Evil: 1"}, "badX-Evil: 1"),
        ({"FRAPPE_AGENT": "x" * 200}, "x" * 140),
    ],
)
def test_detect(env, expected):
    assert agent.detect(env) == expected


@pytest.mark.parametrize(
    ("name", "sent"), [("Claude Code", "Claude Code"), (None, None)]
)
def test_header(httpx2_mock, name, sent):
    route = httpx2_mock.get(f"{BASE}/api/v2/document/ToDo/X/").mock(
        return_value=httpx.Response(200, json={"data": {"name": "X"}})
    )
    FrappeClient(BASE, "k:s", agent=name).get_document("ToDo", "X")
    assert route.calls.last.request.headers.get(agent.HEADER) == sent
