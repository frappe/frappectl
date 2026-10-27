import json

import httpx
import pytest

from frappectl.client import FrappeClient
from frappectl.errors import FrappeError

BASE = "http://localhost"


def client():
    return FrappeClient(BASE, "k:s")


def test_list_documents(httpx2_mock):
    httpx2_mock.get(f"{BASE}/api/v2/document/ToDo").mock(
        return_value=httpx.Response(
            200, json={"data": [{"name": "a"}, {"name": "b"}], "has_next_page": True}
        )
    )
    rows, has_next = client().list_documents("ToDo", fields=["name"], limit=2)
    assert rows == [{"name": "a"}, {"name": "b"}]
    assert has_next is True


def test_get_document_unwraps_data(httpx2_mock):
    httpx2_mock.get(f"{BASE}/api/v2/document/ToDo/X/").mock(
        return_value=httpx.Response(200, json={"data": {"name": "X", "status": "Open"}})
    )
    assert client().get_document("ToDo", "X") == {"name": "X", "status": "Open"}


def test_create_document(httpx2_mock):
    route = httpx2_mock.post(f"{BASE}/api/v2/document/ToDo").mock(
        return_value=httpx.Response(200, json={"data": {"name": "new1"}})
    )
    out = client().create_document("ToDo", {"description": "hi"})
    assert out["name"] == "new1"
    assert route.calls.last.request.content


def test_error_extracted_and_raised(httpx2_mock):
    httpx2_mock.get(f"{BASE}/api/v2/document/ToDo/Z/").mock(
        return_value=httpx.Response(
            404, json={"errors": [{"message": "ToDo Z not found"}]}
        )
    )
    with pytest.raises(FrappeError) as ei:
        client().get_document("ToDo", "Z")
    assert ei.value.message == "ToDo Z not found"
    assert ei.value.status_code == 404


def test_401_message(httpx2_mock):
    httpx2_mock.get(f"{BASE}/api/v2/document/ToDo/Z/").mock(
        return_value=httpx.Response(401, json={"errors": [{"message": "nope"}]})
    )
    with pytest.raises(FrappeError) as ei:
        client().get_document("ToDo", "Z")
    assert ei.value.status_code == 401
    assert "Authentication failed" in ei.value.message


def test_call_method_get(httpx2_mock):
    httpx2_mock.get(f"{BASE}/api/v2/method/frappe.client.get_count").mock(
        return_value=httpx.Response(200, json={"data": 42})
    )
    assert (
        client().call_method(
            "frappe.client.get_count", params={"doctype": "User"}, http_method="GET"
        )
        == 42
    )


def test_redirect_is_followed(httpx2_mock):
    httpx2_mock.get(f"{BASE}/api/v2/document/ToDo/X").mock(
        return_value=httpx.Response(
            301, headers={"location": f"{BASE}/api/v2/document/ToDo/X/"}
        )
    )
    httpx2_mock.get(f"{BASE}/api/v2/document/ToDo/X/").mock(
        return_value=httpx.Response(200, json={"data": {"name": "X"}})
    )
    assert client().request("GET", "/api/v2/document/ToDo/X") == {"name": "X"}


def test_post_redirect_replays_body_on_308(httpx2_mock):
    httpx2_mock.post(f"{BASE}/api/v2/document/ToDo").mock(
        return_value=httpx.Response(
            308, headers={"location": f"{BASE}/api/v2/document/ToDo/"}
        )
    )
    landing = httpx2_mock.post(f"{BASE}/api/v2/document/ToDo/").mock(
        return_value=httpx.Response(200, json={"data": {"name": "new1"}})
    )
    out = client().create_document("ToDo", {"description": "hi"})
    assert out["name"] == "new1"
    assert landing.calls.last.request.content


def test_stream_download_follows_redirects_and_chunks(httpx2_mock):
    httpx2_mock.get(f"{BASE}/private/files/x.bin").mock(
        return_value=httpx.Response(302, headers={"location": f"{BASE}/cdn/x.bin"})
    )
    httpx2_mock.get(f"{BASE}/cdn/x.bin").mock(
        return_value=httpx.Response(200, content=b"payload")
    )
    chunks: list[bytes] = []
    total = client().stream_download("/private/files/x.bin", chunks.append)
    assert b"".join(chunks) == b"payload"
    assert total == len(b"payload")


def test_stream_download_raises_on_error(httpx2_mock):
    httpx2_mock.get(f"{BASE}/private/files/missing.bin").mock(
        return_value=httpx.Response(404, json={"errors": [{"message": "gone"}]})
    )
    with pytest.raises(FrappeError) as ei:
        client().stream_download("/private/files/missing.bin", lambda _b: None)
    assert ei.value.status_code == 404


def test_count(httpx2_mock):
    httpx2_mock.get(f"{BASE}/api/v2/doctype/ToDo/count").mock(
        return_value=httpx.Response(200, json={"data": 7})
    )
    assert client().get_count("ToDo") == 7


def test_cross_host_redirect_does_not_forward_credential(httpx2_mock):
    evil = "https://evil.test"
    httpx2_mock.get(f"{BASE}/api/v2/document/ToDo/X/").mock(
        return_value=httpx.Response(302, headers={"Location": f"{evil}/steal"})
    )
    landing = httpx2_mock.get(f"{evil}/steal").mock(
        return_value=httpx.Response(200, json={"data": {"name": "X"}})
    )
    client().get_document("ToDo", "X")
    assert "authorization" not in landing.calls.last.request.headers


def test_debug_requests_sql_and_emits_server_debug(httpx2_mock, capsys):
    route = httpx2_mock.get(f"{BASE}/api/v2/document/ToDo").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [{"name": "a"}],
                "has_next_page": False,
                "debug": [
                    {"message": "SELECT `name` FROM `tabToDo` LIMIT 1"},
                    {"message": "Execution time: 0.2 ms"},
                ],
            },
        )
    )
    FrappeClient(BASE, "k:s", debug=True).list_documents("ToDo", fields=["name"])
    assert route.calls.last.request.url.params["debug"] == "true"
    err = capsys.readouterr().err
    assert "→ GET" in err
    assert "authorization: token ***" in err
    assert "[server] SELECT `name` FROM `tabToDo` LIMIT 1" in err


def test_debug_emits_server_traceback_on_error(httpx2_mock, capsys):
    httpx2_mock.get(
        f"{BASE}/api/v2/method/suite.mail.api.mail.get_all_inbox_threads"
    ).mock(
        return_value=httpx.Response(
            500,
            json={
                "errors": [
                    {
                        "type": "KeyError",
                        "message": "'thread_id'",
                        "exception": (
                            "Traceback (most recent call last):\n"
                            '  File "mail.py", line 42, in get_all_inbox_threads\n'
                            "    return threads['thread_id']\n"
                            "KeyError: 'thread_id'"
                        ),
                    }
                ]
            },
        )
    )
    with pytest.raises(FrappeError):
        FrappeClient(BASE, "k:s", debug=True).call_method(
            "suite.mail.api.mail.get_all_inbox_threads", http_method="GET"
        )
    err = capsys.readouterr().err
    assert "[server traceback]" in err
    assert "Traceback (most recent call last):" in err
    assert "KeyError: 'thread_id'" in err


def test_no_server_traceback_without_debug(httpx2_mock, capsys):
    httpx2_mock.get(f"{BASE}/api/v2/method/x.y").mock(
        return_value=httpx.Response(
            500,
            json={"errors": [{"exception": "Traceback...\nKeyError: 'z'"}]},
        )
    )
    with pytest.raises(FrappeError) as excinfo:
        client().call_method("x.y", http_method="GET")
    err = capsys.readouterr().err
    assert "traceback" not in err.lower()
    assert excinfo.value.has_server_exception is True


def test_server_exception_not_flagged_under_debug(httpx2_mock):
    httpx2_mock.get(f"{BASE}/api/v2/method/x.y").mock(
        return_value=httpx.Response(
            500,
            json={"errors": [{"exception": "Traceback...\nKeyError: 'z'"}]},
        )
    )
    with pytest.raises(FrappeError) as excinfo:
        FrappeClient(BASE, "k:s", debug=True).call_method("x.y", http_method="GET")
    assert excinfo.value.has_server_exception is False


def test_error_without_traceback_not_flagged(httpx2_mock):
    httpx2_mock.get(f"{BASE}/api/v2/document/ToDo/X/").mock(
        return_value=httpx.Response(
            404,
            json={
                "errors": [{"type": "DoesNotExistError", "message": "ToDo X not found"}]
            },
        )
    )
    with pytest.raises(FrappeError) as excinfo:
        client().get_document("ToDo", "X")
    assert excinfo.value.has_server_exception is False


def test_no_debug_param_or_output_by_default(httpx2_mock, capsys):
    route = httpx2_mock.get(f"{BASE}/api/v2/document/ToDo").mock(
        return_value=httpx.Response(200, json={"data": [], "has_next_page": False})
    )
    client().list_documents("ToDo", fields=["name"])
    assert "debug" not in route.calls.last.request.url.params
    assert capsys.readouterr().err == ""


def test_refuses_plain_http_for_remote_host():
    with pytest.raises(FrappeError) as ei:
        FrappeClient("http://erp.example.com", "k:s")
    assert "cleartext" in ei.value.message.lower()


def test_allows_plain_http_on_localhost():
    for site in ("http://localhost:8000", "http://127.0.0.1", "http://dev.localhost"):
        FrappeClient(site, "k:s").close()


def ro_client():
    return FrappeClient(BASE, "k:s", read_only=True)


def test_read_only_allows_get(httpx2_mock):
    httpx2_mock.get(f"{BASE}/api/v2/document/ToDo/X/").mock(
        return_value=httpx.Response(200, json={"data": {"name": "X"}})
    )
    assert ro_client().get_document("ToDo", "X") == {"name": "X"}


@pytest.mark.parametrize(
    "call",
    [
        lambda c: c.create_document("ToDo", {"description": "hi"}),
        lambda c: c.update_document("ToDo", "X", {"description": "hi"}),
        lambda c: c.delete_document("ToDo", "X"),
        lambda c: c.run_doc_method("ToDo", "X", "some_method"),
        lambda c: c.call_method("frappe.client.set_value", params={"a": 1}),
    ],
)
@pytest.mark.httpx2(assert_all_called=False)
def test_read_only_refuses_writes(httpx2_mock, call):
    # A catch-all route ensures the guard, not the network, is what stops us:
    # if any request escaped it would 500 here rather than raise our message.
    httpx2_mock.route().respond(500)
    with pytest.raises(FrappeError) as ei:
        call(ro_client())
    assert "read-only" in ei.value.message.lower()


def test_read_only_get_method_call_allowed(httpx2_mock):
    route = httpx2_mock.get(f"{BASE}/api/v2/method/frappe.client.get_count").mock(
        return_value=httpx.Response(200, json={"data": 3})
    )
    assert ro_client().call_method("frappe.client.get_count", http_method="GET") == 3
    assert route.called


def test_bearer_header_is_sent(httpx2_mock):
    route = httpx2_mock.get(f"{BASE}/api/v2/document/ToDo/X/").mock(
        return_value=httpx.Response(200, json={"data": {"name": "X"}})
    )
    FrappeClient(BASE, "ACCESS", token_type="bearer").get_document("ToDo", "X")
    assert route.calls.last.request.headers["authorization"] == "Bearer ACCESS"


def test_401_triggers_one_refresh_and_replays(httpx2_mock):
    httpx2_mock.get(f"{BASE}/api/v2/document/ToDo/X/").mock(
        side_effect=[
            httpx.Response(401, json={"errors": [{"message": "expired"}]}),
            httpx.Response(200, json={"data": {"name": "X"}}),
        ]
    )
    calls = {"n": 0}

    def on_unauthorized():
        calls["n"] += 1
        return "ACCESS2"

    client = FrappeClient(
        BASE, "ACCESS1", token_type="bearer", on_unauthorized=on_unauthorized
    )
    assert client.get_document("ToDo", "X") == {"name": "X"}
    assert calls["n"] == 1
    route = httpx2_mock.get(f"{BASE}/api/v2/document/ToDo/X/")
    assert route.calls[-1].request.headers["authorization"] == "Bearer ACCESS2"


def test_401_surfaces_when_refresh_fails(httpx2_mock):
    httpx2_mock.get(f"{BASE}/api/v2/document/ToDo/X/").mock(
        return_value=httpx.Response(401, json={"errors": [{"message": "nope"}]})
    )

    def on_unauthorized():
        return None

    client = FrappeClient(
        BASE, "ACCESS1", token_type="bearer", on_unauthorized=on_unauthorized
    )
    with pytest.raises(FrappeError) as ei:
        client.get_document("ToDo", "X")
    assert ei.value.status_code == 401


def test_no_refresh_callback_does_not_retry(httpx2_mock):
    route = httpx2_mock.get(f"{BASE}/api/v2/document/ToDo/X/").mock(
        return_value=httpx.Response(401, json={"errors": [{"message": "nope"}]})
    )
    with pytest.raises(FrappeError):
        FrappeClient(BASE, "ACCESS", token_type="bearer").get_document("ToDo", "X")
    assert len(route.calls) == 1


def test_debug_redacts_bearer_scheme(httpx2_mock, capsys):
    httpx2_mock.get(f"{BASE}/api/v2/document/ToDo/X/").mock(
        return_value=httpx.Response(200, json={"data": {"name": "X"}})
    )
    FrappeClient(BASE, "ACCESS", token_type="bearer", debug=True).get_document(
        "ToDo", "X"
    )
    err = capsys.readouterr().err
    assert "authorization: Bearer ***" in err
    assert "ACCESS" not in err


def test_list_doctypes_uses_link_search(httpx2_mock):
    route = httpx2_mock.get(
        f"{BASE}/api/v2/method/frappe.desk.search.search_link"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"value": "ToDo", "description": "Desk"},
                    {"value": "Note", "description": "Desk"},
                ]
            },
        )
    )
    names = client().list_doctypes({"module": "Desk"}, 50)
    assert names == ["Note", "ToDo"]
    params = route.calls.last.request.url.params
    assert params["doctype"] == "DocType"
    assert params["page_length"] == "50"
    assert json.loads(params["filters"]) == {"module": "Desk"}
