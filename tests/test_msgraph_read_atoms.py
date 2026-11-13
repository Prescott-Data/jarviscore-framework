"""Read-only Microsoft Graph atoms: native contracts, pages and original bytes."""
import base64
import json
from unittest.mock import AsyncMock

import pytest

from jarviscore.execution.atom_contract import SHIPPED_ATOMS_DIR, read_contract, shipped_source
from jarviscore.nexus.hosts import HostNotAllowed, allowed_hosts, ensure_host_allowed

BASE = "https://graph.microsoft.com/v1.0"
OPERATIONS = {
    "msgraph_get_drive_item": ({"item_id": "item"}, "/me/drive/items/item"),
    "msgraph_list_drive_children": ({}, "/me/drive/root/children"),
    "msgraph_list_mail_folders": ({}, "/me/mailFolders"),
    "msgraph_list_messages": ({}, "/me/messages"),
    "msgraph_get_message": ({"message_id": "message"}, "/me/messages/message"),
    "msgraph_list_message_attachments": ({"message_id": "message"}, "/me/messages/message/attachments"),
    "msgraph_get_message_attachment": ({"message_id": "message", "attachment_id": "attachment"}, "/me/messages/message/attachments/attachment"),
    "msgraph_download_message_attachment": ({"message_id": "message", "attachment_id": "attachment"}, "/me/messages/message/attachments/attachment/$value"),
    "msgraph_download_message": ({"message_id": "message"}, "/me/messages/message/$value"),
}
PAGES = [name for name in OPERATIONS if "_list_" in name]
DOWNLOADS = [name for name in OPERATIONS if "_download_" in name]
METADATA = [name for name in OPERATIONS if name not in DOWNLOADS]


def load(name, response):
    source = (SHIPPED_ATOMS_DIR / "msgraph" / f"{name}.py").read_text()
    contract = read_contract(source, system="msgraph", expected_name=name)
    assert contract.ok, contract.problems
    assert contract.atom.policy.effect == "read"
    assert not contract.atom.policy.requires_approval
    assert shipped_source(contract.atom) == source
    call = AsyncMock(return_value=response)
    namespace = {"nexus_call": call}
    exec(source, namespace)
    return namespace[name], call, contract.atom


def response(data=None, content=b"", status=200):
    return {"ok": status == 200, "status_code": status, "json": data,
            "body": "Authorization: Bearer DO-NOT-EXPOSE", "content": content,
            "headers": {"Location": "https://signed.example/?token=DO-NOT-EXPOSE"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", OPERATIONS)
async def test_operations_are_native_read_contracts_and_get_only(name):
    data = {"value": []} if name in PAGES else {"id": "id"}
    atom, call, metadata = load(name, response(data, b"original"))
    result = await atom(**OPERATIONS[name][0])
    assert result["success"], result
    assert result["error"] is None
    assert call.await_count == 1
    assert call.await_args.args == ("GET", BASE + OPERATIONS[name][1])
    assert "Authorization" not in call.await_args.kwargs.get("headers", {})
    assert "follow_redirects" not in call.await_args.kwargs
    if name in PAGES:
        assert "continuation_cursor" in {p.name for p in metadata.parameters}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", PAGES)
async def test_pages_preserve_every_entry_and_replay_complete_opaque_nextlink(name):
    args, path = OPERATIONS[name]
    cursor = BASE + path + "?$skiptoken=a%2Bb%2F%3D&$select=id%2Cname&$top=2"
    rows = [{"id": str(i), "name": str(i)} for i in range(257)]
    atom, call, _ = load(name, response({"value": rows, "@odata.nextLink": cursor}))
    first = await atom(**args, page_size=2)
    assert first["success"]
    assert [item["id"] for item in first["data"]["items"]] == [str(i) for i in range(257)]
    assert first["data"]["continuation_cursor"] == cursor
    assert first["data"]["has_more"] is True
    call.return_value = response({"value": [{"id": "last"}]})
    last = await atom(**args, page_size=2, continuation_cursor=cursor)
    assert call.await_args.args == ("GET", cursor)
    assert not call.await_args.kwargs.get("params")
    assert last["data"]["items"] == [{"id": "last"}]
    assert last["data"]["has_more"] is False
    assert last["data"]["continuation_cursor"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("name", PAGES)
@pytest.mark.parametrize("cursor", [
    "https://evil.example/v1.0/me/messages?$skip=1",
    "http://graph.microsoft.com/v1.0/me/messages?$skip=1",
    "https://user:password@graph.microsoft.com/v1.0/me/messages?$skip=1",
    "https://graph.microsoft.com:444/v1.0/me/messages?$skip=1",
    "https://graph.microsoft.com/v1.0/me/messages#fragment",
    "https://graph.microsoft.com/v1.0/me/sendMail?$skip=1",
])
async def test_invalid_cursor_is_not_called(name, cursor):
    atom, call, _ = load(name, response({"value": []}))
    result = await atom(**OPERATIONS[name][0], continuation_cursor=cursor)
    assert not result["success"]
    assert result["data"] is None
    call.assert_not_awaited()
    assert "password" not in result["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", PAGES)
async def test_provider_nextlink_is_validated_before_exposure(name):
    atom, call, _ = load(name, response({"value": [], "@odata.nextLink": "https://signed.example/?token=DO-NOT-EXPOSE"}))
    result = await atom(**OPERATIONS[name][0])
    assert not result["success"]
    assert "DO-NOT-EXPOSE" not in json.dumps(result)
    assert call.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("name", METADATA)
async def test_metadata_projects_out_download_credentials_and_attachment_content(name):
    item = {"id": "id", "@microsoft.graph.downloadUrl": "DO-NOT-EXPOSE",
            "webUrl": "https://signed.example/?token=DO-NOT-EXPOSE",
            "contentBytes": "DO-NOT-EXPOSE", "sourceUrl": "DO-NOT-EXPOSE",
            "authorization": "DO-NOT-EXPOSE", "access_token": "DO-NOT-EXPOSE",
            "parentReference": {"id": "parent", "driveId": "drive", "@microsoft.graph.downloadUrl": "DO-NOT-EXPOSE"},
            "file": {"mimeType": "application/pdf", "@microsoft.graph.downloadUrl": "DO-NOT-EXPOSE"}}
    data = {"value": [item]} if name in PAGES else item
    atom, _, _ = load(name, response(data))
    result = await atom(**OPERATIONS[name][0])
    assert result["success"]
    assert "DO-NOT-EXPOSE" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", DOWNLOADS)
@pytest.mark.parametrize("original", [b"", b"\x00\xff\xfe\r\n\x80original\x00", b"MIME-Version: 1.0\r\n\r\nraw\r\n"])
async def test_original_bytes_are_lossless_and_json_safe(name, original):
    atom, _, _ = load(name, response(content=original))
    result = await atom(**OPERATIONS[name][0])
    assert result["success"]
    assert base64.b64decode(result["data"]["content_base64"], validate=True) == original
    assert result["data"]["byte_count"] == len(original)
    json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", DOWNLOADS)
@pytest.mark.parametrize("original", [b"", b"\x00\xff\x80\r\n"])
async def test_known_native_rpc_byte_envelope_is_lossless(name, original):
    envelope = {"__bytes__": base64.b64encode(original).decode("ascii")}
    atom, _, _ = load(name, response(content=envelope))
    result = await atom(**OPERATIONS[name][0])
    assert result["success"]
    assert base64.b64decode(result["data"]["content_base64"], validate=True) == original
    assert result["data"]["byte_count"] == len(original)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", DOWNLOADS)
@pytest.mark.parametrize("content", [None, "replacement text", True,
    {"__bytes__": "not base64"}, {"__bytes__": "AA==", "extra": "not the native envelope"}])
async def test_download_requires_original_bytes_not_text_fallback(name, content):
    atom, _, _ = load(name, response(content=content))
    result = await atom(**OPERATIONS[name][0])
    assert not result["success"]
    assert result["data"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("name", OPERATIONS)
@pytest.mark.parametrize("status", [302, 403, 405, 429])
async def test_failure_and_redirect_do_not_leak_provider_body_or_location(name, status):
    atom, call, _ = load(name, response(status=status))
    result = await atom(**OPERATIONS[name][0])
    assert not result["success"]
    assert result["data"] is None
    assert str(status) in result["error"]
    assert "DO-NOT-EXPOSE" not in json.dumps(result)
    assert call.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("name", PAGES)
@pytest.mark.parametrize("data", [None, {}, {"value": "not a collection"}, {"value": [None]}])
async def test_malformed_pages_are_failures_not_empty_success(name, data):
    atom, _, _ = load(name, response(data))
    result = await atom(**OPERATIONS[name][0])
    assert not result["success"]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", PAGES)
@pytest.mark.parametrize("size", [0, -1, 1001, True, "20"])
async def test_invalid_page_size_does_not_call(name, size):
    atom, call, _ = load(name, response({"value": []}))
    assert not (await atom(**OPERATIONS[name][0], page_size=size))["success"]
    call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", OPERATIONS)
async def test_transport_exception_does_not_expose_credentials(name):
    atom, call, _ = load(name, response({"value": []}))
    call.side_effect = RuntimeError("Bearer DO-NOT-EXPOSE")
    result = await atom(**OPERATIONS[name][0])
    assert not result["success"]
    assert "DO-NOT-EXPOSE" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("name,args,path", [
    ("msgraph_get_drive_item", {"item_id": "a/b?x#y", "drive_id": "drive/id"}, "/drives/drive%2Fid/items/a%2Fb%3Fx%23y"),
    ("msgraph_list_drive_children", {"folder_id": "a/b", "drive_id": "drive/id"}, "/drives/drive%2Fid/items/a%2Fb/children"),
    ("msgraph_list_drive_children", {"drive_id": "drive"}, "/drives/drive/root/children"),
    ("msgraph_list_mail_folders", {"parent_folder_id": "a/b"}, "/me/mailFolders/a%2Fb/childFolders"),
    ("msgraph_list_messages", {"folder_id": "a/b"}, "/me/mailFolders/a%2Fb/messages"),
    ("msgraph_get_message", {"message_id": "a/b"}, "/me/messages/a%2Fb"),
    ("msgraph_get_message_attachment", {"message_id": "a/b", "attachment_id": "c/d"}, "/me/messages/a%2Fb/attachments/c%2Fd"),
])
async def test_identifiers_are_single_encoded_path_segments(name, args, path):
    atom, call, _ = load(name, response({"value": []} if name in PAGES else {"id": "id"}))
    assert (await atom(**args))["success"]
    assert call.await_args.args == ("GET", BASE + path)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", OPERATIONS)
async def test_shipped_native_sandbox_preserves_operations_pages_and_bytes(name):
    import shutil
    import uuid
    from pathlib import Path

    from jarviscore.execution.coder_sandbox import create_coder_sandbox

    original = b"\x00\xfforiginal\r\n\x80"
    cursor = BASE + OPERATIONS[name][1] + "?$skiptoken=a%2Bb%3D&$top=100"
    payload = {"value": [{"id": "id"}], "@odata.nextLink": cursor} if name in PAGES else {"id": "id"}
    _, _, metadata = load(name, response(payload, content=original))

    class Proxy:
        def __init__(self):
            self.calls = []

        async def call(self, connection_id, method, url, **kwargs):
            self.calls.append((connection_id, method, url, kwargs))
            if name in PAGES and url == cursor:
                return response({"value": [{"id": "last"}]})
            return response(payload, content=original)

    proxy = Proxy()
    workspace = Path.cwd() / (".msgraph-native-check-" + uuid.uuid4().hex)
    try:
        sandbox = create_coder_sandbox(workspace_dir=workspace, timeout=20, nexus_call_proxy=proxy)
        result = await sandbox.execute_shipped_atom(
            metadata, OPERATIONS[name][0],
            context={"_nexus_connection_id": "graph-test-connection", "_nexus_provider": "msgraph"},
        )
        assert result["status"] == "success", result
        answer = result["data"]
        if name in DOWNLOADS:
            assert base64.b64decode(answer["content_base64"], validate=True) == original
            assert answer["byte_count"] == len(original)
        elif name in PAGES:
            assert answer == {"items": [{"id": "id"}], "continuation_cursor": cursor, "has_more": True}
            last = await sandbox.execute_shipped_atom(
                metadata, {**OPERATIONS[name][0], "continuation_cursor": cursor},
                context={"_nexus_connection_id": "graph-test-connection", "_nexus_provider": "msgraph"},
            )
            assert last["status"] == "success", last
            assert last["data"] == {"items": [{"id": "last"}], "continuation_cursor": None, "has_more": False}
            assert proxy.calls[-1][2] == cursor
            assert proxy.calls[-1][3]["params"] is None
        else:
            assert answer == {"id": "id"}
        assert proxy.calls[0][:3] == ("graph-test-connection", "GET", BASE + OPERATIONS[name][1])
    finally:
        if workspace.exists():
            shutil.rmtree(workspace)


@pytest.mark.asyncio
async def test_message_body_and_recipients_are_not_truncated():
    body = {"contentType": "html", "content": "full message" * 10000}
    sender = {"emailAddress": {"name": "Person", "address": "person@example.com"}}
    atom, call, _ = load("msgraph_get_message", response({"id": "id", "body": body, "from": sender, "toRecipients": [sender]}))
    result = await atom(message_id="id")
    assert result["data"] == {"id": "id", "body": body, "from": sender, "toRecipients": [sender]}
    assert "body" in call.await_args.kwargs["params"]["$select"].split(",")


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["msgraph_get_message", "msgraph_list_messages"])
async def test_nullable_message_sender_is_valid_metadata(name):
    item = {"id": "id", "from": None, "sender": None, "toRecipients": []}
    atom, _, _ = load(name, response({"value": [item]} if name in PAGES else item))
    result = await atom(**OPERATIONS[name][0])
    assert result["success"]
    assert (result["data"]["items"][0] if name in PAGES else result["data"]) == item


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["fileAttachment", "itemAttachment", "referenceAttachment"])
async def test_attachment_metadata_retains_original_type_without_content(kind):
    item = {"id": "id", "name": "original", "size": 42, "@odata.type": "#microsoft.graph." + kind}
    atom, _, _ = load("msgraph_get_message_attachment", response(item))
    assert (await atom(message_id="id", attachment_id="id"))["data"] == item


@pytest.mark.asyncio
async def test_hidden_mail_folders_request_and_nextlink_preserve_parameters():
    atom, call, _ = load("msgraph_list_mail_folders", response({"value": []}))
    assert (await atom(include_hidden=True))["success"]
    params = call.await_args.kwargs["params"]
    assert params["includeHiddenFolders"] == "true"
    assert params["$top"] == 100
    cursor = BASE + "/me/mailFolders?includeHiddenFolders=true&$skip=100&$top=100"
    assert (await atom(include_hidden=True, continuation_cursor=cursor))["success"]
    assert call.await_args.args == ("GET", cursor)
    assert call.await_args.kwargs.get("params") is None


def test_host_derivation_ignores_api_reference_docstrings():
    from scripts.derive_provider_hosts import hosts_in

    source = '''async def msgraph_example():
    """API reference: https://learn.microsoft.com/en-us/graph/api/message-get"""
    url = "https://graph.microsoft.com/v1.0/me/messages"
    return await nexus_call("GET", url)
'''
    assert hosts_in(source, include_docstrings=False) == {"graph.microsoft.com"}


def test_canonical_nexus_identifier_has_only_the_derived_graph_host():
    assert allowed_hosts("microsoft-graph") == ("graph.microsoft.com",)
    assert allowed_hosts("msgraph") == ("graph.microsoft.com",)
    ensure_host_allowed("microsoft-graph", BASE + "/me/messages")
    with pytest.raises(HostNotAllowed):
        ensure_host_allowed("microsoft-graph", "https://signed.example/download")
