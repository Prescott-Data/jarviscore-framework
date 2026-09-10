"""The capability loop: a migrated atom is offered, called, and run in the sandbox."""

import pytest

from jarviscore.execution.atom_contract import invocation, read_contract

ATOM = "jarviscore/integrations/atoms/hubspot/hubspot_list_contacts.py"
DRIVE_FOLDER_ATOM = (
    "jarviscore/integrations/atoms/google_drive/google_drive_create_folder.py"
)
DRIVE_SEARCH_ATOM = (
    "jarviscore/integrations/atoms/google_drive/google_drive_search_files.py"
)
HUBSPOT_SEARCH_ATOM = (
    "jarviscore/integrations/atoms/hubspot/hubspot_search_contacts.py"
)
CALENDAR_CREATE_ATOM = (
    "jarviscore/integrations/atoms/google_calendar/google_calendar_create_event.py"
)
CALENDAR_LIST_ATOM = (
    "jarviscore/integrations/atoms/google_calendar/google_calendar_list_events.py"
)
DRIVE_EXPORT_ATOM = (
    "jarviscore/integrations/atoms/google_drive/google_drive_export_file.py"
)
HUBSPOT_CONTACT_DEALS_ATOM = (
    "jarviscore/integrations/atoms/hubspot/hubspot_list_contact_deals.py"
)
HUBSPOT_SEARCH_DEALS_ATOM = (
    "jarviscore/integrations/atoms/hubspot/hubspot_search_deals.py"
)
HUBSPOT_ASSOCIATE_DEAL_ATOM = (
    "jarviscore/integrations/atoms/hubspot/hubspot_associate_deal_contact.py"
)
HUBSPOT_CREATE_DEAL_ATOM = (
    "jarviscore/integrations/atoms/hubspot/hubspot_create_deal.py"
)
DRIVE_APPEND_DOCUMENT_ATOM = (
    "jarviscore/integrations/atoms/google_drive/google_drive_append_document_text.py"
)


@pytest.fixture
def atom_source():
    with open(ATOM, encoding="utf-8") as handle:
        return handle.read()


class TestMigratedAtomIsCallable:

    def test_it_satisfies_the_contract(self, atom_source):
        result = read_contract(atom_source, system="hubspot",
                               expected_name="hubspot_list_contacts")
        assert result.ok, result.report()
        assert not result.atom.legacy

    def test_the_credential_is_gone_from_the_signature(self, atom_source):
        atom = read_contract(atom_source, system="hubspot",
                             expected_name="hubspot_list_contacts").atom
        assert [p.name for p in atom.parameters] == ["limit", "after"]
        assert "auth_info" not in atom_source

    async def test_it_runs_against_a_stubbed_nexus(self, atom_source):
        """The atom plus its invocation is exactly what the sandbox executes."""
        calls = []

        async def nexus_call(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return {"ok": True, "status_code": 200,
                    "json": {"results": [{"id": "1"}], "paging": None},
                    "body": "", "headers": {}}

        atom = read_contract(atom_source, system="hubspot",
                             expected_name="hubspot_list_contacts").atom
        namespace = {"nexus_call": nexus_call}
        exec(f"{atom_source}\n\n{invocation(atom, {'limit': 5})}", namespace)
        result = await namespace["main"]()

        assert result["success"] is True
        assert result["contacts"] == [{"id": "1"}]
        method, url, kwargs = calls[0]
        assert method == "GET"
        assert url == "https://api.hubapi.com/crm/v3/objects/contacts"
        assert kwargs["params"]["limit"] == 5

    async def test_a_provider_error_is_returned_not_raised(self, atom_source):
        async def nexus_call(method, url, **kwargs):
            return {"ok": False, "status_code": 401, "json": None,
                    "body": "unauthorised", "headers": {}}

        atom = read_contract(atom_source, system="hubspot",
                             expected_name="hubspot_list_contacts").atom
        namespace = {"nexus_call": nexus_call}
        exec(f"{atom_source}\n\n{invocation(atom, {})}", namespace)
        result = await namespace["main"]()

        assert result == {"success": False, "error": "unauthorised"}


class TestDriveFolderAtom:

    def test_direct_token_retrieval_is_not_a_valid_atom(self):
        source = """
async def google_drive_create_folder(folder_name: str) -> dict:
    token = _get_nexus_token(None)
    return await nexus_call('POST', 'https://example.test', headers={'Authorization': token})
"""
        result = read_contract(
            source, system="google_drive", expected_name="google_drive_create_folder"
        )

        assert result.ok is False
        assert "must not retrieve provider tokens" in result.report()

    async def test_it_uses_nexus_managed_google_drive_authority(self):
        with open(DRIVE_FOLDER_ATOM, encoding="utf-8") as handle:
            source = handle.read()
        atom = read_contract(
            source, system="google_drive", expected_name="google_drive_create_folder"
        ).atom
        calls = []

        async def nexus_call(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return {
                "ok": True,
                "status_code": 200,
                "json": {"id": "folder-1", "name": "Acme Corp"},
                "body": "",
                "headers": {},
            }

        namespace = {"nexus_call": nexus_call}
        exec(
            f"{source}\n\n{invocation(atom, {'folder_name': 'Acme Corp'})}",
            namespace,
        )
        result = await namespace["main"]()

        assert result["success"] is True
        assert calls[0][2]["provider"] == "google_drive"
        assert "Authorization" not in calls[0][2].get("headers", {})
        assert "_get_nexus_token" not in source


class TestProviderSearchAtoms:

    @pytest.mark.parametrize(
        ("path", "system", "name", "params", "expected_url"),
        [
            (
                DRIVE_SEARCH_ATOM,
                "google_drive",
                "google_drive_search_files",
                {"query": "name = 'Acme Corp'"},
                "https://www.googleapis.com/drive/v3/files",
            ),
            (
                HUBSPOT_SEARCH_ATOM,
                "hubspot",
                "hubspot_search_contacts",
                {"query": "Ephy Kizito"},
                "https://api.hubapi.com/crm/v3/objects/contacts/search",
            ),
        ],
    )
    async def test_search_uses_nexus_managed_provider_authority(
        self, path, system, name, params, expected_url
    ):
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        atom = read_contract(source, system=system, expected_name=name).atom
        calls = []

        async def nexus_call(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return {
                "ok": True,
                "status_code": 200,
                "json": {"files": [], "results": [], "total": 0},
                "body": "",
                "headers": {},
            }

        namespace = {"nexus_call": nexus_call}
        exec(f"{source}\n\n{invocation(atom, params)}", namespace)
        result = await namespace["main"]()

        assert result["success"] is True
        method, url, kwargs = calls[0]
        assert url == expected_url
        assert kwargs["provider"] == system
        assert "Authorization" not in kwargs.get("headers", {})
        assert method in {"GET", "POST"}


class TestCalendarCreateAtom:

    async def test_it_returns_submitted_facts_when_provider_omits_them(self):
        with open(CALENDAR_CREATE_ATOM, encoding="utf-8") as handle:
            source = handle.read()
        atom = read_contract(
            source,
            system="google_calendar",
            expected_name="google_calendar_create_event",
        ).atom

        async def nexus_call(method, url, **kwargs):
            return {
                "ok": True,
                "status_code": 200,
                "json": {"id": "event-1"},
                "body": "",
                "headers": {},
            }

        params = {
            "summary": "Discovery Call",
            "start_datetime": "2026-09-11T17:00:00+03:00",
            "end_datetime": "2026-09-11T17:30:00+03:00",
            "attendees": ["ephy@example.com"],
        }
        namespace = {"nexus_call": nexus_call}
        exec(f"{source}\n\n{invocation(atom, params)}", namespace)
        result = await namespace["main"]()

        assert result["event_id"] == "event-1"
        assert result["html_link"] is None
        assert result["starts_at"] == params["start_datetime"]
        assert result["ends_at"] == params["end_datetime"]
        assert result["attendees"] == ["ephy@example.com"]


class TestProviderIdentityAndContentAtoms:

    async def test_calendar_list_preserves_identity_and_status_fields(self):
        with open(CALENDAR_LIST_ATOM, encoding="utf-8") as handle:
            source = handle.read()
        atom = read_contract(
            source,
            system="google_calendar",
            expected_name="google_calendar_list_events",
        ).atom

        async def nexus_call(method, url, **kwargs):
            return {
                "ok": True,
                "json": {"items": [{
                    "id": "event-1",
                    "summary": "Discovery Call",
                    "start": {"dateTime": "2026-09-11T17:00:00+03:00"},
                    "end": {"dateTime": "2026-09-11T17:30:00+03:00"},
                    "attendees": [{
                        "email": "ephy@example.com",
                        "responseStatus": "needsAction",
                    }],
                    "organizer": {"email": "owner@example.com", "self": True},
                    "status": "confirmed",
                    "htmlLink": "https://calendar.test/event-1",
                }]},
                "body": "",
            }

        namespace = {"nexus_call": nexus_call}
        exec(f"{source}\n\n{invocation(atom, {})}", namespace)
        result = await namespace["main"]()

        event = result["events"][0]
        assert event["attendees"][0]["email"] == "ephy@example.com"
        assert event["organizer"]["self"] is True
        assert event["status"] == "confirmed"
        assert event["htmlLink"] == "https://calendar.test/event-1"

    async def test_drive_export_uses_workspace_export_endpoint(self):
        with open(DRIVE_EXPORT_ATOM, encoding="utf-8") as handle:
            source = handle.read()
        atom = read_contract(
            source,
            system="google_drive",
            expected_name="google_drive_export_file",
        ).atom
        calls = []

        async def nexus_call(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return {"ok": True, "content": b"Introduction\nProblem\nSolution"}

        namespace = {"nexus_call": nexus_call}
        exec(
            f"{source}\n\n{invocation(atom, {'file_id': 'doc-1'})}",
            namespace,
        )
        result = await namespace["main"]()

        assert result["content"].startswith("Introduction")
        assert calls[0][1].endswith("/files/doc-1/export")
        assert calls[0][2]["params"] == {"mimeType": "text/plain"}
        assert calls[0][2]["provider"] == "google_drive"

    async def test_drive_export_preserves_binary_content_as_base64(self):
        with open(DRIVE_EXPORT_ATOM, encoding="utf-8") as handle:
            source = handle.read()
        atom = read_contract(
            source,
            system="google_drive",
            expected_name="google_drive_export_file",
        ).atom

        async def nexus_call(method, url, **kwargs):
            return {"ok": True, "content": b"%PDF-\xff"}

        namespace = {"nexus_call": nexus_call}
        exec(
            f"{source}\n\n{invocation(atom, {'file_id': 'doc-1', 'mime_type': 'application/pdf'})}",
            namespace,
        )
        result = await namespace["main"]()

        assert result["content"] is None
        assert result["content_base64"] == "JVBERi3/"
        assert result["encoding"] == "base64"

    async def test_hubspot_contact_deals_reads_association_records(self):
        with open(HUBSPOT_CONTACT_DEALS_ATOM, encoding="utf-8") as handle:
            source = handle.read()
        atom = read_contract(
            source,
            system="hubspot",
            expected_name="hubspot_list_contact_deals",
        ).atom
        calls = []

        async def nexus_call(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return {
                "ok": True,
                "json": {"results": [{"toObjectId": 520580273359}]},
                "body": "",
            }

        namespace = {"nexus_call": nexus_call}
        exec(
            f"{source}\n\n{invocation(atom, {'contact_id': '865110084794'})}",
            namespace,
        )
        result = await namespace["main"]()

        assert result["deals"] == [{"toObjectId": 520580273359}]
        assert calls[0][1].endswith(
            "/contacts/865110084794/associations/deals"
        )
        assert calls[0][2]["provider"] == "hubspot"

    async def test_hubspot_search_deals_uses_provider_search(self):
        with open(HUBSPOT_SEARCH_DEALS_ATOM, encoding="utf-8") as handle:
            source = handle.read()
        atom = read_contract(
            source, system="hubspot", expected_name="hubspot_search_deals"
        ).atom
        calls = []

        async def nexus_call(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return {
                "ok": True,
                "json": {"results": [{"id": "deal-1"}], "total": 1},
                "body": "",
            }

        namespace = {"nexus_call": nexus_call}
        exec(
            f"{source}\n\n{invocation(atom, {'query': 'Acme Corp'})}",
            namespace,
        )
        result = await namespace["main"]()

        assert result["deals"] == [{"id": "deal-1"}]
        assert calls[0][0] == "POST"
        assert calls[0][1].endswith("/crm/v3/objects/deals/search")

    async def test_hubspot_association_is_verified_by_readback(self):
        with open(HUBSPOT_ASSOCIATE_DEAL_ATOM, encoding="utf-8") as handle:
            source = handle.read()
        atom = read_contract(
            source,
            system="hubspot",
            expected_name="hubspot_associate_deal_contact",
        ).atom
        calls = []

        async def nexus_call(method, url, **kwargs):
            calls.append((method, url, kwargs))
            if method == "PUT":
                return {"ok": True, "json": {}, "body": ""}
            return {
                "ok": True,
                "json": {"results": [{"toObjectId": "deal-1"}]},
                "body": "",
            }

        namespace = {"nexus_call": nexus_call}
        exec(
            f"{source}\n\n{invocation(atom, {'deal_id': 'deal-1', 'contact_id': 'contact-1'})}",
            namespace,
        )
        result = await namespace["main"]()

        assert result["association_verified"] is True
        assert [call[0] for call in calls] == ["PUT", "GET"]

    async def test_hubspot_create_can_associate_and_verify_the_contact(self):
        with open(HUBSPOT_CREATE_DEAL_ATOM, encoding="utf-8") as handle:
            source = handle.read()
        atom = read_contract(
            source, system="hubspot", expected_name="hubspot_create_deal"
        ).atom
        calls = []

        async def nexus_call(method, url, **kwargs):
            calls.append((method, url, kwargs))
            if method == "POST":
                return {"ok": True, "json": {"id": "deal-1"}, "body": ""}
            if method == "PUT":
                return {"ok": True, "json": {}, "body": ""}
            return {
                "ok": True,
                "json": {"results": [{"toObjectId": "deal-1"}]},
                "body": "",
            }

        namespace = {"nexus_call": nexus_call}
        exec(
            f"{source}\n\n{invocation(atom, {'deal_name': 'Acme opportunity', 'stage': 'qualified', 'contact_id': 'contact-1'})}",
            namespace,
        )
        result = await namespace["main"]()

        assert result["id"] == "deal-1"
        assert result["contact_id"] == "contact-1"
        assert result["association_verified"] is True
        assert [call[0] for call in calls] == ["POST", "PUT", "GET"]

    async def test_google_docs_append_uses_the_current_document_end(self):
        with open(DRIVE_APPEND_DOCUMENT_ATOM, encoding="utf-8") as handle:
            source = handle.read()
        atom = read_contract(
            source,
            system="google_drive",
            expected_name="google_drive_append_document_text",
        ).atom
        calls = []

        async def nexus_call(method, url, **kwargs):
            calls.append((method, url, kwargs))
            if method == "GET":
                return {
                    "ok": True,
                    "json": {"body": {"content": [{"endIndex": 2}]}},
                    "body": "",
                }
            return {"ok": True, "json": {}, "body": ""}

        namespace = {"nexus_call": nexus_call}
        exec(
            f"{source}\n\n{invocation(atom, {'document_id': 'doc-1', 'content': 'Introduction'})}",
            namespace,
        )
        result = await namespace["main"]()

        assert result["inserted_characters"] == len("Introduction")
        request = calls[1][2]["json"]["requests"][0]["insertText"]
        assert request["location"]["index"] == 1
        assert request["text"] == "Introduction"
