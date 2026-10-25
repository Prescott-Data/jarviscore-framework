"""Acting for your application's users: one way in, from every entry point."""

import pytest

from jarviscore import Mesh, OnBehalfOf, Person, act_for
from jarviscore.auth import principal
from jarviscore.core.mesh import _with_principal
from jarviscore.profiles import CustomAgent

TRIP = {"systems": ["salesforce"], "effects": ["read"]}


def test_a_user_of_a_tenant_is_keyed_uniquely_across_tenants():
    assert OnBehalfOf.of("acme", "u_1").person == "acme/u_1"
    assert OnBehalfOf.of("globex", "u_1").person != OnBehalfOf.of("acme", "u_1").person
    assert OnBehalfOf.of("acme", "u_1", TRIP).mandate == TRIP
    with pytest.raises(ValueError):
        OnBehalfOf.of("acme/evil", "u_1")  # a tenant cannot reach into another's keys
    with pytest.raises(ValueError):
        OnBehalfOf("  ")


def test_whom_work_is_for_can_be_named_three_ways():
    assert principal.on_behalf_of(None) is None
    assert principal.on_behalf_of("acme/u_1") == OnBehalfOf("acme/u_1")
    assert principal.on_behalf_of(Person("acme", "u_1", "Ada")) == OnBehalfOf("acme/u_1")
    named = OnBehalfOf("acme/u_1", TRIP)
    assert principal.on_behalf_of(named) is named
    with pytest.raises(TypeError):
        principal.on_behalf_of(42)


def test_act_for_carries_the_person_and_what_they_delegated():
    with act_for(OnBehalfOf.of("acme", "u_1", TRIP)):
        assert principal.acting_for.get() == "acme/u_1"
        assert principal.mandate.get() == TRIP
    assert principal.acting_for.get() is None and principal.mandate.get() is None
    with act_for(Person("acme", "u_2")):
        assert principal.acting_for.get() == "acme/u_2"
        assert principal.mandate.get() is None
    narrower = {"systems": ["salesforce"], "effects": []}
    with act_for(OnBehalfOf("acme/u_1", TRIP), narrower):
        assert principal.mandate.get() == narrower


def test_a_goal_names_whom_it_is_for_once():
    assert _with_principal(None, None) is None
    merged = _with_principal({"region": "eu"}, OnBehalfOf.of("acme", "u_1", TRIP))
    assert merged == {"region": "eu", "acting_for": "acme/u_1", "mandate": TRIP}
    assert _with_principal({"acting_for": "acme/u_1"}, "acme/u_1") == {"acting_for": "acme/u_1"}
    with pytest.raises(ValueError, match="disagree"):
        _with_principal({"acting_for": "acme/u_2"}, "acme/u_1")
    with pytest.raises(ValueError, match="disagree"):
        _with_principal({"mandate": {"systems": []}}, OnBehalfOf("acme/u_1", TRIP))


class Witness(CustomAgent):
    role = "witness"
    capabilities = ["witness"]

    async def execute_task(self, task):
        return {"status": "success", "output": {
            "acting_for": principal.acting_for.get(), "mandate": principal.mandate.get(),
        }}


@pytest.mark.asyncio
async def test_run_task_and_workflow_work_for_the_person_and_no_longer():
    mesh = Mesh(config={"p2p_enabled": False})
    mesh.add(Witness)
    await mesh.start()
    try:
        single = await mesh.run_task(
            agent="witness", task="who", on_behalf_of=OnBehalfOf.of("acme", "u_1", TRIP),
        )
        steps = await mesh.workflow(
            "wf-obo", [{"agent": "witness", "task": "who"}], on_behalf_of=Person("acme", "u_2"),
        )
        anonymous = await mesh.run_task(agent="witness", task="who")
    finally:
        await mesh.stop()

    assert single["output"] == {"acting_for": "acme/u_1", "mandate": TRIP}
    assert steps[0]["output"] == {"acting_for": "acme/u_2", "mandate": None}
    assert anonymous["output"] == {"acting_for": None, "mandate": None}


class Accounts:
    """Stands in for the authentication manager: records whom each call was for."""

    def __init__(self):
        self.calls = []

    async def begin_authentication(self, provider, scopes=None, return_url=None):
        self.calls.append(("begin", provider, principal.acting_for.get(), return_url))
        return "conn-1", f"https://consent.example/{provider}"

    async def discover(self, provider):
        self.calls.append(("discover", provider, principal.acting_for.get()))
        return "resolved:x" if principal.acting_for.get() == "acme/u_1" else None


@pytest.mark.asyncio
async def test_connecting_a_users_account_is_done_as_that_user():
    mesh = Mesh(config={"p2p_enabled": False})
    with pytest.raises(RuntimeError, match="Nexus gateway"):
        await mesh.connect("salesforce", on_behalf_of="acme/u_1")
    mesh._auth_manager = accounts = Accounts()

    started = await mesh.connect(
        "salesforce", on_behalf_of=OnBehalfOf.of("acme", "u_1"), return_url="https://app/done",
    )
    assert started == {"auth_url": "https://consent.example/salesforce", "connection_id": "conn-1"}
    assert await mesh.connected("salesforce", on_behalf_of="acme/u_1") is True
    assert await mesh.connected("salesforce", on_behalf_of="acme/u_2") is False
    assert accounts.calls == [
        ("begin", "salesforce", "acme/u_1", "https://app/done"),
        ("discover", "salesforce", "acme/u_1"),
        ("discover", "salesforce", "acme/u_2"),
    ]
    assert principal.acting_for.get() is None
    with pytest.raises(ValueError):
        await mesh.connect("salesforce", on_behalf_of=None)


class Kernel:
    def __init__(self):
        self.seen = []

    async def execute(self, task, system_prompt, context, agent_id):
        self.seen.append((principal.acting_for.get(), principal.mandate.get(), dict(context),
                          principal.scopes.get()))
        from types import SimpleNamespace

        return SimpleNamespace(status="success", summary="ok", payload="ok", metadata={})


def _client(kernel, **router):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from jarviscore.integrations.chat import create_chat_router

    app = FastAPI()
    app.include_router(create_chat_router(kernel, **router))
    return TestClient(app)


def test_a_chat_is_for_whom_the_application_authenticated_never_whom_the_client_claims():
    from fastapi import HTTPException

    async def signed_in(request):
        user = request.headers.get("x-test-user")
        if not user:
            raise HTTPException(status_code=401, detail="sign in")
        return OnBehalfOf.of("acme", user, TRIP, scopes=["claims.vet"])

    kernel = Kernel()
    client = _client(kernel, on_behalf_of=signed_in)
    claimed = {"acting_for": "acme/ceo", "mandate": {"systems": ["*"]}, "topic": "q3",
               "scopes": {"payments.approve": {"amount": "*"}}}

    assert client.post("/chat", json={"message": "hi", "context": claimed}).status_code == 401
    assert kernel.seen == []

    reply = client.post("/chat", json={"message": "hi", "context": claimed},
                        headers={"x-test-user": "u_1"})
    assert reply.status_code == 200
    acting, granted, context, held = kernel.seen[0]
    assert (acting, granted, held) == ("acme/u_1", TRIP, {"claims.vet": {}})
    assert "acting_for" not in context and "mandate" not in context and "scopes" not in context
    assert context["topic"] == "q3"


def test_a_chat_without_a_resolver_is_for_no_one_whatever_the_client_claims():
    kernel = Kernel()
    client = _client(kernel, on_behalf_of=lambda request: None)
    reply = client.post("/chat", json={"message": "hi", "context": {"acting_for": "acme/ceo"}})
    assert reply.status_code == 200
    assert kernel.seen[0][:2] == (None, None)
    assert "acting_for" not in kernel.seen[0][2]


def test_whom_work_is_for_is_registered_from_the_runtime_only():
    assert principal.registered() is None
    with act_for(OnBehalfOf.of("acme", "u_1", TRIP)):
        assert principal.registered() == {"acting_for": "acme/u_1", "mandate": TRIP}
    with act_for("acme/u_2"):
        assert principal.registered() == {"acting_for": "acme/u_2"}


@pytest.mark.asyncio
async def test_a_workflows_steps_on_other_nodes_act_for_the_same_person():
    from jarviscore.testing.mocks import MockRedisContextStore

    store = MockRedisContextStore()
    mesh = Mesh(config={"p2p_enabled": False})
    mesh.add(Witness)
    await mesh.start()
    try:
        mesh._workflow_engine.redis_store = store
        await mesh.workflow("wf-remote", [{"id": "s1", "agent": "witness", "task": "who"}],
                            on_behalf_of=OnBehalfOf.of("acme", "u_1", TRIP))
        await mesh.workflow("wf-nobody", [{"id": "s1", "agent": "witness", "task": "who"}])
    finally:
        await mesh.stop()

    # What a node that claims a step reads to decide whom it works for.
    definition = store.get_workflow_definition("wf-remote")
    assert Mesh._acting_for(definition) == "acme/u_1" and Mesh._mandate(definition) == TRIP
    nobody = store.get_workflow_definition("wf-nobody")
    assert Mesh._acting_for(nobody) is None and Mesh._mandate(nobody) is None


@pytest.mark.asyncio
async def test_a_dag_an_agent_builds_while_working_for_someone_stays_theirs():
    from jarviscore.orchestration.workflow_builder import WorkflowBuilder
    from jarviscore.testing.mocks import MockRedisContextStore

    store = MockRedisContextStore()
    with act_for(OnBehalfOf.of("acme", "u_1", TRIP)):
        built = WorkflowBuilder().step("s1", agent="witness", task="who").build()
        identity = await built.register(store)
    definition = store.get_workflow_definition(identity)
    assert Mesh._acting_for(definition) == "acme/u_1" and Mesh._mandate(definition) == TRIP
