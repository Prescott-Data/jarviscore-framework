"""Publisher metadata is attributable page data, not independent verification."""

import json

import pytest

from jarviscore.core.egress import Egress
from jarviscore.search.internet_search import InternetSearch


SOURCE_URL = "https://publisher.example/people/analyst"


def _json_ld(value):
    return f'<script type="application/ld+json">{json.dumps(value)}</script>'


async def _capture(html, *, browser_content=None):
    requests = []

    class Response:
        status = 200
        url = SOURCE_URL
        headers = {"Content-Type": "text/html; charset=utf-8"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def text(self):
            return html

    class Session:
        closed = False

        def get(self, url, **kwargs):
            requests.append((url, kwargs))
            return Response()

    search = InternetSearch(
        user_agent="Example Research research@example.org",
        egress=Egress("http://gateway.example:7000"),
    )
    search.session = Session()
    browser_calls = []

    async def browser(url):
        browser_calls.append(url)
        return browser_content or ""

    search._extract_via_browser = browser
    result = await search.extract_content("https://publisher.example/redirect")
    return result, requests, browser_calls


def _values(result):
    return [record["value"] for record in result["publisher_metadata"]]


@pytest.mark.asyncio
async def test_nested_profile_biography_has_provenance_and_is_not_visible_text():
    profile = {
        "@context": "https://schema.org",
        "@type": "ProfilePage",
        "mainEntity": {
            "@type": "Person",
            "name": "Example Analyst",
            "description": "The publisher says this analyst has twenty years of experience.",
            "jobTitle": "Investment Analyst",
            "worksFor": {"@type": "Organization", "name": "Example Company"},
        },
    }
    result, requests, browser_calls = await _capture("<h1>Example Analyst</h1>" + _json_ld(profile))

    person = next(value for value in _values(result) if value.get("@type") == "Person")
    assert person["jobTitle"] == "Investment Analyst"
    assert person["worksFor"]["name"] == "Example Company"
    assert person["description"] == profile["mainEntity"]["description"]
    record = next(item for item in result["publisher_metadata"] if item["value"] == person)
    assert record["source_url"] == SOURCE_URL
    assert record["format"] == "json-ld"
    assert record["json_path"] == "$.mainEntity"
    assert record["independently_verified"] is False
    assert record["provenance"] == "publisher_metadata"
    assert "twenty years" not in result["visible_content"]
    assert "twenty years" in result["content"]
    assert "not independently verified" in result["content"]
    assert "self-reported" in result["content"]
    assert result["main_content"] == result["content"]
    assert result["content_length"] == len(result["content"])
    assert requests[0][1]["headers"]["User-Agent"] == "Example Research research@example.org"
    assert requests[0][1]["proxy"] == "http://gateway.example:7000"
    assert requests[0][1]["allow_redirects"] is True
    assert browser_calls == []


@pytest.mark.asyncio
async def test_official_source_descriptions_remain_publisher_claims():
    result, _, _ = await _capture(
        '<title>Agency register</title><meta name="description" '
        'content="Agency description of its own register.">'
        '<meta property="og:description" content="Open Graph publisher description.">'
        "<main><p>Visible register introduction.</p></main>"
        + _json_ld(
            {
                "@context": "https://schema.org",
                "@type": "GovernmentOrganization",
                "name": "Example Agency",
                "description": "The agency describes its statutory remit.",
            }
        )
    )

    assert result["meta_tags"]["description"] == "Agency description of its own register."
    assert result["visible_content"].endswith("Visible register introduction.")
    assert "Agency description of its own register." in result["content"]
    assert "Open Graph publisher description." in result["content"]
    assert "statutory remit" in result["content"]
    assert all(not record["independently_verified"] for record in result["publisher_metadata"])


@pytest.mark.asyncio
async def test_graph_arrays_and_local_references_preserve_exact_relationships():
    result, _, _ = await _capture(
        "<p>Public profile</p>"
        + _json_ld(
            {
                "@context": "https://schema.org",
                "@graph": [
                    {"@type": "ProfilePage", "mainEntity": [{"@id": "#person"}]},
                    {
                        "@id": "#person",
                        "@type": ["Person", "Thing"],
                        "name": "A Person",
                        "jobTitle": ["Analyst", "Director"],
                        "worksFor": [{"@id": "#org"}, {"@id": "https://other.example/org"}],
                    },
                ],
            }
        )
        + _json_ld(
            [
                {
                    "@context": "https://schema.org",
                    "@id": "#org",
                    "@type": "Organization",
                    "name": "An Organization",
                    "founder": {"@id": "#person"},
                },
            ]
        )
    )

    person = next(value for value in _values(result) if value.get("name") == "A Person")
    assert person["jobTitle"] == ["Analyst", "Director"]
    assert person["worksFor"][0]["name"] == "An Organization"
    assert person["worksFor"][1] == {"@id": "https://other.example/org"}
    assert "invented" not in json.dumps(_values(result))


@pytest.mark.asyncio
async def test_malformed_and_unrelated_scripts_do_not_invent_facts_or_break_capture():
    result, _, _ = await _capture(
        "<main><p>A readable page.</p></main>"
        '<script type="application/ld+json">{broken</script>'
        '<script>window.profile = {"description":"JavaScript is not a biography"};</script>'
        '<script type="application/json">{"description":"Application state is not evidence"}</script>'
        + _json_ld(
            {
                "@context": "https://schema.org",
                "@type": "BreadcrumbList",
                "description": "Navigation is not a biography",
            }
        )
        + _json_ld(
            {
                "@context": "https://unrelated.example",
                "@type": "Person",
                "description": "Not a schema.org Person",
            }
        )
        + _json_ld(
            {
                "@context": "https://schema.org",
                "@type": "Person",
                "name": "A Person",
                "description": {"unrelated": "Not a description"},
            }
        )
    )

    assert "error" not in result
    assert result["visible_content"] == "A readable page."
    assert _values(result) == [{"@type": "Person", "name": "A Person"}]
    assert "not a biography" not in result["content"]
    assert "Not a description" not in result["content"]


@pytest.mark.asyncio
async def test_metadata_does_not_mask_or_replace_existing_browser_fallback():
    result, requests, browser_calls = await _capture(
        "<p>Body</p>"
        + _json_ld(
            {
                "@context": "https://schema.org",
                "@type": "Person",
                "name": "A Person",
                "description": "A long publisher claim. " * 60,
            }
        ),
        browser_content="Rendered visible browser text, with more detail.",
    )

    assert browser_calls == ["https://publisher.example/redirect"]
    assert result["visible_content"] == "Rendered visible browser text, with more detail."
    assert result["content"].startswith(result["visible_content"])
    assert "A long publisher claim." in result["content"]
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_metadata_free_capture_keeps_existing_content_and_links_unchanged():
    result, _, _ = await _capture(
        "<main><h1>A public page</h1><p>Visible <b>text</b>.</p>"
        '<a href="/register">Register</a></main><script>hiddenData()</script>'
    )

    assert result["publisher_metadata"] == []
    assert result["content"] == result["visible_content"] == result["main_content"]
    assert "Visible text." in result["content"]
    assert "hiddenData" not in result["content"]
    assert result["links"] == ["https://publisher.example/register"]


@pytest.mark.asyncio
async def test_schema_context_vocab_prefixes_and_absolute_types():
    result, _, _ = await _capture(
        _json_ld(
            [
                {
                    "@context": {"@vocab": "https://schema.org/"},
                    "@type": "Organization",
                    "name": "Vocab Organization",
                },
                {
                    "@context": {"schema": "https://schema.org/"},
                    "@type": "schema:Person",
                    "name": "Prefixed Person",
                },
                {
                    "@type": "https://schema.org/Organization",
                    "name": "Absolute Type Organization",
                },
            ]
        )
    )

    assert {value["name"] for value in _values(result)} == {
        "Vocab Organization",
        "Prefixed Person",
        "Absolute Type Organization",
    }


@pytest.mark.asyncio
async def test_cyclic_missing_and_invalid_references_do_not_break_capture():
    result, _, _ = await _capture(
        _json_ld(
            {
                "@context": "https://schema.org",
                "@graph": [
                    {"@type": "Person", "@id": "#p", "name": "A Person", "worksFor": {"@id": "#o"}},
                    {
                        "@type": "Organization",
                        "@id": "#o",
                        "name": "A Company",
                        "founder": {"@id": "#p"},
                        "parentOrganization": {"@id": "http://["},
                    },
                    {"@type": "ProfilePage", "mainEntity": {"@id": "#missing"}},
                ],
            }
        )
    )

    person = next(value for value in _values(result) if value.get("name") == "A Person")
    assert person["worksFor"]["founder"] == {"@id": SOURCE_URL + "#p"}
    assert "parentOrganization" not in person["worksFor"]
    page = next(value for value in _values(result) if value.get("@type") == "ProfilePage")
    assert page["mainEntity"] == {"@id": SOURCE_URL + "#missing"}
    assert "error" not in result


@pytest.mark.asyncio
async def test_metadata_resource_limits_and_deep_malformed_values_are_local_failures():
    nested_description = "[" * 200 + '"not a valid description"' + "]" * 200
    result, _, _ = await _capture(
        "<p>Still readable.</p>"
        '<script type="application/ld+json">' + "[" * 1500 + "]" * 1500 + "</script>"
        '<script type="application/ld+json">' + " " * 512_001 + "</script>"
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"Person","name":"A Person",'
        '"description":'
        + nested_description
        + "}</script>"
        + _json_ld(
            {
                "@context": "https://schema.org",
                "@graph": [{"@type": "Person", "name": f"Person {i}"} for i in range(100)],
            }
        )
    )

    assert "error" not in result
    assert result["visible_content"] == "Still readable."
    assert len(result["publisher_metadata"]) <= 32
    assert "not a valid description" not in result["content"]
    assert any(value.get("name") == "A Person" for value in _values(result))


@pytest.mark.asyncio
async def test_duplicate_entities_do_not_create_independent_sources():
    entity = {"@context": "https://schema.org", "@type": "Person", "name": "A Person"}
    result, _, _ = await _capture(_json_ld(entity) + _json_ld(entity))

    assert len(result["publisher_metadata"]) == 1
    assert result["publisher_metadata"][0]["source_url"] == SOURCE_URL
