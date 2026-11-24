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
DRIVE_GET_DOCUMENT_ATOM = (
    "jarviscore/integrations/atoms/google_drive/google_drive_get_document.py"
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
DRIVE_CREATE_DOCUMENT_ATOM = (
    "jarviscore/integrations/atoms/google_drive/google_drive_create_document.py"
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


@pytest.mark.parametrize("folder_id, parents", [("", None), ("folder-1", ["folder-1"])])
async def test_a_drive_document_lands_in_my_drive_unless_a_folder_is_named(folder_id, parents):
    with open(DRIVE_CREATE_DOCUMENT_ATOM, encoding="utf-8") as handle:
        source = handle.read()
    contract = read_contract(
        source, system="google_drive", expected_name="google_drive_create_document"
    )
    assert contract.ok, contract.report()
    calls = []

    async def nexus_call(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return {"ok": True, "status_code": 200, "body": "", "headers": {},
                "json": {"id": "doc-1", "name": "Packing list", "webViewLink": "https://d/doc-1"}}

    params = {"title": "Packing list", "content": "Tent"}
    if folder_id:
        params["folder_id"] = folder_id
    namespace = {"nexus_call": nexus_call}
    exec(f"{source}\n\n{invocation(contract.atom, params)}", namespace)
    result = await namespace["main"]()

    assert result["success"] is True
    assert result["web_view_link"] == "https://d/doc-1"
    assert calls[0][2]["json"].get("parents") == parents


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

    async def test_drive_get_document_reads_structural_text(self):
        with open(DRIVE_GET_DOCUMENT_ATOM, encoding="utf-8") as handle:
            source = handle.read()
        atom = read_contract(
            source,
            system="google_drive",
            expected_name="google_drive_get_document",
        ).atom
        calls = []

        async def nexus_call(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return {
                "ok": True,
                "json": {
                    "title": "Acme Pitch",
                    "body": {"content": [
                        {"paragraph": {"elements": [
                            {"textRun": {"content": "Introduction\n"}},
                            {"textRun": {"content": "Problem\n"}},
                        ]}},
                        {"sectionBreak": {}},
                        {"paragraph": {"elements": [
                            {"textRun": {"content": "Solution\n"}},
                        ]}},
                    ]},
                },
                "body": "",
            }

        namespace = {"nexus_call": nexus_call}
        exec(
            f"{source}\n\n{invocation(atom, {'document_id': 'doc-1'})}",
            namespace,
        )
        result = await namespace["main"]()

        assert result == {
            "success": True,
            "document_id": "doc-1",
            "title": "Acme Pitch",
            "text": "Introduction\nProblem\nSolution\n",
            "paragraph_count": 2,
            "content_length": 29,
            "error": None,
        }
        assert calls == [(
            "GET", "https://docs.googleapis.com/v1/documents/doc-1",
            {"provider": "google_drive"},
        )]

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


class TestApolloAtoms:
    """Apollo's documented API: x-api-key header, /api/v1 paths, query parameters."""

    @staticmethod
    def load(name):
        with open(
            f"jarviscore/integrations/atoms/apollo/{name}.py", encoding="utf-8"
        ) as handle:
            source = handle.read()
        result = read_contract(source, system="apollo", expected_name=name)
        assert result.ok, result.report()
        return source, result.atom

    @staticmethod
    async def run(source, atom, arguments, response):
        calls = []

        async def nexus_call(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return {"ok": True, "status_code": 200, "json": response, "body": "",
                    "headers": {}}

        namespace = {"nexus_call": nexus_call}
        exec(f"{source}\n\n{invocation(atom, arguments)}", namespace)
        return await namespace["main"](), calls

    def test_the_key_is_placed_in_the_header_apollo_documents(self):
        from jarviscore.nexus.providers import get_auth_config

        assert get_auth_config("apollo") == {"header_name": "x-api-key"}

    async def test_people_search_uses_the_api_search_endpoint(self):
        source, atom = self.load("apollo_search_people")
        result, calls = await self.run(
            source,
            atom,
            {"job_titles": ["Chief Operating Officer"], "seniorities": ["c_suite"],
             "organization_domains": ["example.co.uk"]},
            {"people": [{"id": "p1", "first_name": "Ada"}], "total_entries": 1},
        )

        assert result == {"success": True, "people": [{"id": "p1", "first_name": "Ada"}],
                          "total_entries": 1, "page": 1}
        method, url, kwargs = calls[0]
        assert (method, url) == ("POST", "https://api.apollo.io/api/v1/mixed_people/api_search")
        assert kwargs["provider"] == "apollo"
        assert kwargs["params"]["person_titles[]"] == ["Chief Operating Officer"]
        assert kwargs["params"]["person_seniorities[]"] == ["c_suite"]
        assert kwargs["params"]["q_organization_domains_list[]"] == ["example.co.uk"]

    async def test_organization_search_filters_by_keyword_tags(self):
        source, atom = self.load("apollo_search_organizations")
        _, calls = await self.run(
            source,
            atom,
            {"locations": ["united kingdom"], "keyword_tags": ["private equity"],
             "employee_count_min": 20, "employee_count_max": 500},
            {"organizations": [], "pagination": {"total_entries": 0}},
        )

        method, url, kwargs = calls[0]
        assert url == "https://api.apollo.io/api/v1/mixed_companies/search"
        assert kwargs["params"]["organization_locations[]"] == ["united kingdom"]
        assert kwargs["params"]["q_organization_keyword_tags[]"] == ["private equity"]
        assert kwargs["params"]["organization_num_employees_ranges[]"] == ["20,500"]

    async def test_person_enrichment_by_name_and_domain_returns_contact_details(self):
        source, atom = self.load("apollo_get_person")
        result, calls = await self.run(
            source,
            atom,
            {"name": "Ada Lovelace", "domain": "example.co.uk"},
            {"person": {"id": "p1", "name": "Ada Lovelace", "title": "COO",
                        "email": "ada@example.co.uk", "email_status": "verified",
                        "linkedin_url": "http://www.linkedin.com/in/ada",
                        "match_confidence": "high",
                        "organization": {"name": "Example", "primary_domain": "example.co.uk"}}},
        )

        assert calls[0][1] == "https://api.apollo.io/api/v1/people/match"
        assert calls[0][2]["params"] == {"name": "Ada Lovelace", "domain": "example.co.uk"}
        assert result["email"] == "ada@example.co.uk"
        assert result["email_status"] == "verified"
        assert result["match_confidence"] == "high"
        assert result["organization_domain"] == "example.co.uk"

    async def test_person_enrichment_needs_an_identifier(self):
        source, atom = self.load("apollo_get_person")
        result, calls = await self.run(source, atom, {}, {})

        assert result["success"] is False
        assert calls == []


CALENDAR_DELETE_ATOM = (
    "jarviscore/integrations/atoms/google_calendar/google_calendar_delete_event.py"
)


class TestCalendarGuestsAreEmailed:
    """Google's Calendar API emails guests only when the request says sendUpdates=all; the
    default is silence, so an invite created through the atom reached guests' calendars
    without the invitation email. Both writes now ask for the email."""

    async def _run(self, path, name, params):
        calls = []

        async def nexus_call(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return {"ok": True, "status_code": 200 if method == "POST" else 204,
                    "json": {"id": "ev1", "htmlLink": "https://calendar/ev1"}, "body": "", "headers": {}}

        source = open(path, encoding="utf-8").read()
        atom = read_contract(source, system="google_calendar", expected_name=name).atom
        namespace = {"nexus_call": nexus_call}
        exec(f"{source}\n\n{invocation(atom, params)}", namespace)
        return await namespace["main"](), calls

    async def test_an_event_with_guests_sends_the_invitation(self):
        result, calls = await self._run(
            CALENDAR_CREATE_ATOM, "google_calendar_create_event",
            {"summary": "Call", "start_datetime": "2026-11-17T19:00:00+03:00",
             "end_datetime": "2026-11-17T20:00:00+03:00", "attendees": ["guest@example.com"]},
        )
        assert result["success"] and result["attendees"] == ["guest@example.com"]
        method, url, kwargs = calls[0]
        assert method == "POST" and url.endswith("/calendars/primary/events")
        assert kwargs["params"] == {"sendUpdates": "all"}
        assert kwargs["json"]["attendees"] == [{"email": "guest@example.com"}]

    async def test_an_event_without_guests_asks_for_no_email(self):
        _, calls = await self._run(
            CALENDAR_CREATE_ATOM, "google_calendar_create_event",
            {"summary": "Thinking time", "start_datetime": "2026-11-17T19:00:00+03:00",
             "end_datetime": "2026-11-17T20:00:00+03:00"},
        )
        assert calls[0][2]["params"] == {}

    async def test_a_video_call_asks_google_for_a_meet_link_and_returns_it(self):
        calls = []

        async def nexus_call(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return {"ok": True, "status_code": 200, "body": "", "headers": {}, "json": {
                "id": "ev1", "htmlLink": "https://calendar/ev1",
                "hangoutLink": "https://meet.google.com/abc-defg-hij"}}

        source = open(CALENDAR_CREATE_ATOM, encoding="utf-8").read()
        atom = read_contract(
            source, system="google_calendar", expected_name="google_calendar_create_event").atom
        params = {"summary": "Call", "start_datetime": "2026-11-24T11:30:00-05:00",
                  "end_datetime": "2026-11-24T12:00:00-05:00",
                  "attendees": ["guest@example.com"], "video_call": True}
        results = []
        for _ in range(2):
            namespace = {"nexus_call": nexus_call}
            exec(f"{source}\n\n{invocation(atom, params)}", namespace)  # noqa: S102
            results.append(await namespace["main"]())
        assert results[0]["meet_link"] == "https://meet.google.com/abc-defg-hij"
        kwargs = calls[0][2]
        assert kwargs["params"] == {"sendUpdates": "all", "conferenceDataVersion": 1}
        request = kwargs["json"]["conferenceData"]["createRequest"]
        assert request["conferenceSolutionKey"] == {"type": "hangoutsMeet"}
        # the same event asks under the same id: a call made again makes no second link
        assert request["requestId"] == calls[1][2]["json"]["conferenceData"]["createRequest"]["requestId"]

    async def test_without_a_video_call_no_conference_is_asked_for(self):
        result, calls = await self._run(
            CALENDAR_CREATE_ATOM, "google_calendar_create_event",
            {"summary": "Call", "start_datetime": "2026-11-17T19:00:00+03:00",
             "end_datetime": "2026-11-17T20:00:00+03:00"},
        )
        assert "conferenceData" not in calls[0][2]["json"] and "meet_link" not in result

    async def test_a_time_with_its_offset_is_not_relabelled_and_a_zone_given_is_used(self):
        _, calls = await self._run(
            CALENDAR_CREATE_ATOM, "google_calendar_create_event",
            {"summary": "Call", "start_datetime": "2026-11-24T11:30:00-05:00",
             "end_datetime": "2026-11-24T12:00:00-05:00"},
        )
        assert calls[0][2]["json"]["start"] == {"dateTime": "2026-11-24T11:30:00-05:00"}
        _, calls = await self._run(
            CALENDAR_CREATE_ATOM, "google_calendar_create_event",
            {"summary": "Call", "start_datetime": "2026-11-24T11:30:00-05:00",
             "end_datetime": "2026-11-24T12:00:00-05:00", "time_zone": "America/New_York"},
        )
        assert calls[0][2]["json"]["end"]["timeZone"] == "America/New_York"
        # a time with no offset is read in the zone given, and in no zone when none is:
        # the atom used to assume Africa/Nairobi, a meeting at the wrong hour for anyone
        # elsewhere
        _, calls = await self._run(
            CALENDAR_CREATE_ATOM, "google_calendar_create_event",
            {"summary": "Call", "start_datetime": "2026-11-24T11:30:00",
             "end_datetime": "2026-11-24T12:00:00", "time_zone": "Europe/London"},
        )
        assert calls[0][2]["json"]["start"] == {
            "dateTime": "2026-11-24T11:30:00", "timeZone": "Europe/London"}
        result, calls = await self._run(
            CALENDAR_CREATE_ATOM, "google_calendar_create_event",
            {"summary": "Call", "start_datetime": "2026-11-24T11:30:00",
             "end_datetime": "2026-11-24T12:00:00"},
        )
        assert not result["success"] and "has no UTC offset" in result["error"]
        assert calls == []
        source = open(CALENDAR_CREATE_ATOM, encoding="utf-8").read()
        assert "Nairobi" not in source

    async def test_an_all_day_event_is_dates_and_ends_the_day_after_its_last(self):
        result, calls = await self._run(
            CALENDAR_CREATE_ATOM, "google_calendar_create_event",
            {"summary": "Offsite", "start_datetime": "2026-11-24", "end_datetime": "2026-11-27"},
        )
        assert result["success"] and result["all_day"] is True
        sent = calls[0][2]["json"]
        assert sent["start"] == {"date": "2026-11-24"} and sent["end"] == {"date": "2026-11-27"}
        for end in ("2026-11-24", "2026-11-24T12:00:00-05:00"):
            result, calls = await self._run(
                CALENDAR_CREATE_ATOM, "google_calendar_create_event",
                {"summary": "Offsite", "start_datetime": "2026-11-24", "end_datetime": end},
            )
            assert not result["success"] and calls == []

    async def test_an_event_that_repeats_carries_its_rule_and_needs_its_zone(self):
        weekly = {"summary": "1:1", "start_datetime": "2026-11-24T10:00:00-05:00",
                  "end_datetime": "2026-11-24T10:30:00-05:00",
                  "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=TU;COUNT=10"]}
        result, calls = await self._run(
            CALENDAR_CREATE_ATOM, "google_calendar_create_event",
            {**weekly, "time_zone": "America/New_York"},
        )
        sent = calls[0][2]["json"]
        assert sent["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TU;COUNT=10"]
        assert sent["start"]["timeZone"] == "America/New_York"
        assert result["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TU;COUNT=10"]
        result, calls = await self._run(
            CALENDAR_CREATE_ATOM, "google_calendar_create_event", weekly)
        assert not result["success"] and "needs time_zone" in result["error"] and calls == []
        result, calls = await self._run(
            CALENDAR_CREATE_ATOM, "google_calendar_create_event",
            {**weekly, "time_zone": "America/New_York", "recurrence": ["every Tuesday"]},
        )
        assert not result["success"] and "not a recurrence rule" in result["error"]

    async def test_reminders_are_set_only_when_asked(self):
        base = {"summary": "Call", "start_datetime": "2026-11-24T11:30:00-05:00",
                "end_datetime": "2026-11-24T12:00:00-05:00"}
        _, calls = await self._run(CALENDAR_CREATE_ATOM, "google_calendar_create_event", base)
        assert "reminders" not in calls[0][2]["json"]
        _, calls = await self._run(
            CALENDAR_CREATE_ATOM, "google_calendar_create_event",
            {**base, "reminder_minutes": [10, 60]})
        assert calls[0][2]["json"]["reminders"] == {"useDefault": False, "overrides": [
            {"method": "popup", "minutes": 10}, {"method": "popup", "minutes": 60}]}
        _, calls = await self._run(
            CALENDAR_CREATE_ATOM, "google_calendar_create_event",
            {**base, "reminder_minutes": []})
        assert calls[0][2]["json"]["reminders"] == {"useDefault": False, "overrides": []}

    def test_a_repeat_is_the_same_event_only_with_the_same_guests_and_link(self):
        """The fields a second call is recognised by. With the guests and the Meet link
        left out, creating the same slot again with a guest added was answered "already
        ran" from the first call, and nobody was invited."""
        source = open(CALENDAR_CREATE_ATOM, encoding="utf-8").read()
        atom = read_contract(
            source, system="google_calendar", expected_name="google_calendar_create_event").atom
        assert {"attendees", "video_call", "recurrence"} <= set(atom.policy.idempotency_fields)
        assert "free slot" not in atom.policy.consequence  # it checks no slot and claims none

    async def test_a_deletion_sends_the_cancellation(self):
        result, calls = await self._run(
            CALENDAR_DELETE_ATOM, "google_calendar_delete_event", {"event_id": "ev1"}
        )
        assert result["deleted"] is True
        method, url, kwargs = calls[0]
        assert method == "DELETE" and url.endswith("/events/ev1")
        assert kwargs["params"] == {"sendUpdates": "all"}

