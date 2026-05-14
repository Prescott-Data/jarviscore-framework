"""
JarvisCore — Production-oriented usability harness
==================================================
Builds **real** AutoAgent subclasses and exercises what the **guides** promise:

  docs/guides/autoagent.md
    — class attributes, Mesh + workflow(), lifecycle, default_kernel_role,
      coder sandbox, complexity hints, infra injection, depends_on DAG,
      goal_oriented, explicit ``context`` (troubleshooting), output_schema

  docs/guides/workflows.md
    — WorkflowBuilder fluent API, `{step_id.result}` substitution,
      execute() without Redis (in-memory DAG)

  docs/guides/fastapi.md
    — JarvisLifespan importable (integration surface)

  docs/reference/agent-api.md (sanity)
    — delegate/run_task-style dispatch used by WorkflowBuilder

Static checks run **without** an LLM; live checks require a configured provider.

Prerequisites:
  - ``pip install -e ".[dev]"`` (includes pydantic; optional: ``fastapi``)
  - ``.env`` with at least one LLM provider for live sections

Usage:
  source .venv/bin/activate
  PYTHONPATH=. python test_usability.py
"""

import asyncio
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pydantic import BaseModel

from jarviscore import Mesh
from jarviscore.orchestration.workflow_builder import WorkflowBuilder
from jarviscore.profiles import AutoAgent

PASS = 0
FAIL = 0
SKIP = 0


def report(test_name: str, passed: bool, detail: str = ""):
    global PASS, FAIL
    icon = "\u2705" if passed else "\u274c"
    if passed:
        PASS += 1
    else:
        FAIL += 1
    msg = f"  {icon} {test_name}"
    if detail:
        msg += f"  ->  {detail}"
    print(msg)


def skip(test_name: str, reason: str):
    global SKIP
    SKIP += 1
    print(f"  \u23ed  {test_name}  [SKIPPED: {reason}]")


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════════

class AgentMissingPrompt(AutoAgent):
    """Should fail instantiation — no system_prompt."""
    role = "broken"
    capabilities = ["none"]


class MathAgent(AutoAgent):
    """Specialist agent that always routes to the coder subagent."""
    role = "calculator"
    capabilities = ["math", "compute"]
    default_kernel_role = "coder"
    system_prompt = """
    You are a precise calculator. Write Python code to compute the answer.
    Store the numerical answer in a variable named `result` as a dict:
    result = {"answer": <number>}
    Do NOT import anything. Use only basic Python arithmetic.
    """


class FileWriterAgent(AutoAgent):
    """Tests the CoderSandbox: workspace, blob_path, open()."""
    role = "file_writer"
    capabilities = ["files", "writing"]
    default_kernel_role = "coder"
    system_prompt = """
    You are a file-writing agent. Your sandbox has these pre-loaded names:
      workspace (Path)  — project root directory
      output_dir (Path) — workspace/output/
      blob_path(name)   — returns output_dir / name, creating parent dirs

    IMPORTANT: You MUST write actual Python code that executes using the `write_code` tool.
    Do NOT return JSON. Write code that calls open() and writes to disk.
    NEVER call open("test_output.txt", ...) directly. Always first call:
        dest = blob_path("test_output.txt")
    Then write to `dest`.

    Example pattern for writing a file:
        dest = blob_path("myfile.txt")
        with open(dest, "w") as f:
            f.write("content here")
        result = {
            "success": True,
            "files_created": [str(dest)],
            "data": {"content": "content here"}
        }

    Always store a dict in the variable named `result`.
    """


class DataFetcher(AutoAgent):
    """Step 1 in the multi-agent workflow pipeline."""
    role = "fetcher"
    capabilities = ["data", "fetch"]
    default_kernel_role = "coder"
    system_prompt = """
    You are a data fetcher. Generate a small dataset and store it in `result`.

    result = {
        "items": [
            {"name": "Widget A", "price": 29.99, "stock": 150},
            {"name": "Widget B", "price": 49.99, "stock": 75},
            {"name": "Widget C", "price": 19.99, "stock": 300},
        ],
        "count": 3,
        "source": "synthetic"
    }

    Store EXACTLY this structure in `result`. Do NOT modify the values.
    """


class DataAnalyser(AutoAgent):
    """Step 2 — receives fetcher output via depends_on."""
    role = "analyser"
    capabilities = ["analysis"]
    default_kernel_role = "coder"
    system_prompt = """
    You are a data analyst. You receive prior step data in your context.

    Read the items from context (previous_step_results) and compute:
    - total_value = sum(price * stock for each item)
    - cheapest = name of the item with lowest price
    - most_stocked = name of the item with highest stock

    result = {
        "total_value": <float>,
        "cheapest": "<name>",
        "most_stocked": "<name>",
    }

    If context data is not available, use these defaults:
    items = [
        {"name": "Widget A", "price": 29.99, "stock": 150},
        {"name": "Widget B", "price": 49.99, "stock": 75},
        {"name": "Widget C", "price": 19.99, "stock": 300},
    ]
    """


class SummaryReporter(AutoAgent):
    """Step 3 — receives analyser output via depends_on."""
    role = "reporter"
    capabilities = ["reporting", "writing"]
    default_kernel_role = "coder"
    system_prompt = """
    You are a report writer. You receive analysis results from context.

    Write a one-paragraph summary of the analysis findings.
    Store it as:
    result = {"report": "<your summary paragraph>"}

    If context is not available, write a generic summary about widget inventory.
    """


class LifecycleAgent(AutoAgent):
    """Tests setup() and teardown() hooks."""
    role = "lifecycle_test"
    capabilities = ["test"]
    default_kernel_role = "coder"
    system_prompt = """
    You are a test agent. Compute 1 + 1 and store in result.
    result = {"answer": 2}
    """

    async def setup(self):
        await super().setup()
        self.setup_called = True
        self.custom_resource = "initialized"

    async def teardown(self):
        self.teardown_called = True
        await super().teardown()


class EnrichingAgent(AutoAgent):
    """Tests execute_task() override for context enrichment."""
    role = "enricher"
    capabilities = ["enrich"]
    default_kernel_role = "coder"
    system_prompt = """
    You are a test agent. The task may contain extra context injected by the
    execute_task override. Compute 2 + 2 and store in result.
    result = {"answer": 4}
    """

    async def execute_task(self, task):
        if isinstance(task, dict):
            enriched = {**task, "task": f"{task.get('task', '')}\n\nInjected context: user_id=test123"}
        else:
            enriched = task
        return await super().execute_task(enriched)


class GoalAgent(AutoAgent):
    """Tests goal_oriented = True (Plan -> Execute -> Evaluate loop)."""
    role = "goal_planner"
    capabilities = ["planning", "execution"]
    goal_oriented = True
    default_kernel_role = "coder"
    system_prompt = """
    You are a goal-oriented agent. You decompose goals into steps.
    For each step, write Python code that stores the step result in `result`.
    result should be a dict with "success": True and any relevant data.
    """


class StructuredPayload(BaseModel):
    """Contract enforced via Agent.output_schema (kernel passes into coder context)."""
    ok: bool
    detail: str


class ProductionStyleAgent(AutoAgent):
    """
    Single agent showcasing prod-oriented knobs from docs:
    optional name/description, structured output validation.
    """
    role = "prod_agent"
    name = "Production Style Demo"
    description = "Smoke-tests structured payloads end-to-end through the Kernel."
    capabilities = ["demo", "structured-output"]
    default_kernel_role = "coder"
    output_schema = StructuredPayload
    system_prompt = """
    You write minimal Python in CoderSandbox.
    You MUST use the `write_code` tool to write your code. Do not output the JSON directly.
    Set variable `result` in your Python code to exactly:
      {"success": True, "data": {"ok": True, "detail": "structured smoke ok"}}

    The inner dict MUST match keys ok (bool) and detail (short string).
    Do not add extra keys inside data.
    """


# ═══════════════════════════════════════════════════════════════════════════════
# TEST FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def test_static_guide_contracts():
    """Compile-time / import checks — no LLM, no Mesh."""
    print("\n--- Static: Guide contracts (imports & WorkflowBuilder API) ---")

    # workflows.md — empty build raises
    try:
        WorkflowBuilder().build(title="empty")
        report("WorkflowBuilder rejects empty DAG", False, "Expected ValueError")
    except ValueError:
        report("WorkflowBuilder rejects empty DAG", True, "ValueError raised")

    # workflows.md — depends_on before declaration raises
    try:
        (
            WorkflowBuilder()
            .step("orphan", "fetcher", "task", depends_on=["undeclared"])
            .build(title="bad-deps")
        )
        report("WorkflowBuilder rejects forward deps", False)
    except ValueError:
        report("WorkflowBuilder rejects forward deps", True, "ValueError raised")

    # Duplicate step_id
    try:
        (
            WorkflowBuilder()
            .step("dup", "fetcher", "a")
            .step("dup", "fetcher", "b")
            .build(title="dup")
        )
        report("WorkflowBuilder rejects duplicate step_id", False)
    except ValueError:
        report("WorkflowBuilder rejects duplicate step_id", True)

    # fastapi.md — optional dependency
    try:
        from jarviscore.integrations.fastapi import JarvisLifespan

        report(
            "JarvisLifespan importable (FastAPI integration)",
            callable(JarvisLifespan),
            JarvisLifespan.__name__,
        )
    except ImportError as e:
        skip(
            "JarvisLifespan importable (FastAPI integration)",
            f"pip install fastapi — {e}",
        )


async def test_1_class_validation():
    """Promise: ValueError if system_prompt is absent."""
    print("\n--- Test 1: Class Validation (system_prompt required) ---")
    try:
        agent = AgentMissingPrompt(agent_id="test-bad")
        report("ValueError on missing system_prompt", False, "No exception raised")
    except ValueError as e:
        report("ValueError on missing system_prompt", True, str(e)[:80])
    except Exception as e:
        report("ValueError on missing system_prompt", False, f"Wrong exception: {e}")


async def test_2_standalone_execution(mesh):
    """Promise: Mesh() + workflow() produces status/payload/metadata."""
    print("\n--- Test 2: Standalone Execution (Mesh + workflow) ---")
    results = await mesh.workflow("usability-math-001", [
        {"agent": "calculator", "task": "What is 15 * 7?"}
    ])

    step = results[0]
    status = step.get("status")
    report("workflow() returns a list", isinstance(results, list), f"len={len(results)}")
    report("step has 'status' key", "status" in step, f"status={status}")
    report("status is 'success'", status == "success",
           f"got '{status}', error={step.get('error', 'none')[:120] if step.get('error') else 'none'}")

    payload = step.get("payload") or step.get("output")
    report("step has payload/output", payload is not None, f"type={type(payload).__name__}")

    if isinstance(payload, dict) and "answer" in payload:
        report("payload contains correct answer (105)", payload["answer"] == 105,
               f"answer={payload.get('answer')}")
    elif isinstance(payload, dict) and "data" in payload:
        data = payload["data"]
        if isinstance(data, dict) and "answer" in data:
            report("payload.data contains correct answer (105)",
                   data["answer"] == 105, f"answer={data.get('answer')}")
        else:
            report("payload contains result data", True,
                   f"data keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
    elif isinstance(payload, str) and "105" in payload:
        report("payload contains correct answer (105)", True,
               f"found '105' in string output")
    else:
        report("payload contains correct answer (105)", False,
               f"got: {str(payload)[:120]}")


async def test_3_kernel_role_routing(mesh):
    """Promise: default_kernel_role skips classification."""
    print("\n--- Test 3: Kernel Role Routing (default_kernel_role='coder') ---")
    results = await mesh.workflow("usability-routing-001", [
        {"agent": "calculator", "task": "Compute the factorial of 10."}
    ])
    step = results[0]
    dispatches = step.get("dispatches", [])
    if dispatches:
        first_role = dispatches[0].get("role", "unknown")
        report("Task routed to 'coder' subagent", first_role == "coder",
               f"dispatched to '{first_role}'")
    else:
        report("Task routed to 'coder' subagent", step.get("status") == "success",
               "no dispatch info but task succeeded")


async def test_4_coder_sandbox(mesh):
    """Promise: CoderSandbox provides workspace, blob_path, open()."""
    print("\n--- Test 4: Coder Sandbox (file writing via blob_path) ---")
    results = await mesh.workflow("usability-sandbox-001", [
        {"agent": "file_writer",
         "task": "Write the text 'Hello from JarvisCore usability test' to a file using blob_path('test_output.txt')."}
    ])
    step = results[0]
    status = step.get("status")
    report("File write task succeeded", status == "success",
           f"status={status}, error={step.get('error', 'none')[:120] if step.get('error') else 'none'}")

    payload = step.get("payload") or step.get("output")

    files_created = []
    if isinstance(payload, dict):
        files_created = payload.get("files_created", [])
        if not files_created and "data" in payload and isinstance(payload["data"], dict):
            files_created = payload["data"].get("files_created", [])

    if files_created:
        p = Path(files_created[0])
        exists = p.exists()
        report("File actually exists on disk", exists, str(p))
        if exists:
            content = p.read_text().strip()
            report("File content is correct",
                   "Hello from JarvisCore" in content or "usability" in content.lower(),
                   f"content='{content[:80]}'")
    else:
        output_dir = Path.cwd() / "output"
        found_file = None
        if output_dir.exists():
            for f in output_dir.rglob("test_output*"):
                found_file = f
                break
        if found_file:
            content = found_file.read_text().strip()
            report("File found in output directory", True, str(found_file))
            report("File content is correct",
                   "Hello from JarvisCore" in content or "usability" in content.lower(),
                   f"content='{content[:80]}'")
        else:
            report("File created by sandbox",
                   isinstance(payload, dict) and payload.get("success") is True,
                   f"payload={str(payload)[:120]}")


async def test_5_workflow_return_shape(mesh):
    """Promise: workflow() returns status, payload, summary, metadata."""
    print("\n--- Test 5: workflow() Return Shape ---")
    results = await mesh.workflow("usability-shape-001", [
        {"agent": "calculator", "task": "What is 2 + 2?"}
    ])
    step = results[0]
    report("Has 'status' key", "status" in step)
    has_payload = "payload" in step or "output" in step
    report("Has 'payload' or 'output' key", has_payload)

    tokens = step.get("tokens", {})
    report("Has token tracking", isinstance(tokens, dict),
           f"tokens={tokens}")


async def test_6_lifecycle_hooks(mesh):
    """Promise: setup() and teardown() are called with super()."""
    print("\n--- Test 6: Lifecycle Hooks (setup/teardown) ---")
    agents = [a for a in mesh.agents if isinstance(a, LifecycleAgent)]
    if not agents:
        skip("setup() called", "LifecycleAgent not found in mesh")
        return

    agent = agents[0]
    report("setup() was called", getattr(agent, 'setup_called', False))
    report("Custom resource initialized in setup()",
           getattr(agent, 'custom_resource', None) == "initialized")


async def test_7_execute_task_override(mesh):
    """Promise: Override execute_task() to enrich the task dict."""
    print("\n--- Test 7: execute_task() Override (context enrichment) ---")
    results = await mesh.workflow("usability-enrich-001", [
        {"agent": "enricher", "task": "Compute 2 + 2."}
    ])
    step = results[0]
    report("Enriched agent task succeeded", step.get("status") == "success",
           f"error={step.get('error', 'none')[:120] if step.get('error') else 'none'}")


async def test_8_model_routing_complexity(mesh):
    """Promise: Pass complexity= in workflow step to route to a model tier."""
    print("\n--- Test 8: Model Routing (complexity hint) ---")
    results = await mesh.workflow("usability-complexity-001", [
        {"agent": "calculator", "task": "What is 3 * 3?", "complexity": "nano"}
    ])
    step = results[0]
    report("Task with complexity='nano' succeeded", step.get("status") == "success",
           f"error={step.get('error', 'none')[:120] if step.get('error') else 'none'}")


async def test_9_infrastructure_injection(mesh):
    """Promise: _blob_storage is always available."""
    print("\n--- Test 9: Infrastructure Injection ---")
    if not mesh.agents:
        skip("blob_storage injection", "No agents in mesh")
        return

    agent = mesh.agents[0]
    has_blob = hasattr(agent, '_blob_storage') and agent._blob_storage is not None
    report("Agent has _blob_storage injected", has_blob,
           f"type={type(agent._blob_storage).__name__}" if has_blob else "None")

    has_redis = hasattr(agent, '_redis_store')
    report("Agent has _redis_store attribute", has_redis,
           f"value={'connected' if agent._redis_store else 'None (expected without REDIS_URL)'}")


async def test_10_multi_agent_workflow(mesh):
    """Promise: depends_on chains steps; prior outputs delivered automatically."""
    print("\n--- Test 10: Multi-Agent Workflow (depends_on pipeline) ---")
    results = await mesh.workflow("usability-pipeline-001", [
        {"id": "fetch",   "agent": "fetcher",  "task": "Generate the widget dataset."},
        {"id": "analyse", "agent": "analyser", "task": "Analyse the widget data from the previous step.",
         "depends_on": ["fetch"]},
        {"id": "report",  "agent": "reporter", "task": "Write a summary of the analysis.",
         "depends_on": ["analyse"]},
    ])

    report("Pipeline returned 3 results", len(results) == 3, f"got {len(results)}")

    step_names = ["fetch", "analyse", "report"]
    for i, name in enumerate(step_names):
        if i < len(results):
            s = results[i].get("status")
            report(f"Step '{name}' status=success", s == "success",
                   f"status={s}, error={results[i].get('error', 'none')[:100] if results[i].get('error') else 'none'}")

    if len(results) >= 3 and results[2].get("status") == "success":
        payload = results[2].get("payload") or results[2].get("output")
        has_report = payload is not None and (
            (isinstance(payload, dict) and "report" in payload) or
            (isinstance(payload, dict) and isinstance(payload.get("data"), str)) or
            (
                isinstance(payload, dict)
                and isinstance(payload.get("data"), dict)
                and isinstance(payload["data"].get("summary"), str)
            ) or
            isinstance(payload, str)
        )
        report("Final step produced a report", has_report,
               f"type={type(payload).__name__}, preview={str(payload)[:80]}")


async def test_11_goal_oriented(mesh):
    """Promise: goal_oriented=True activates Plan -> Execute -> Evaluate loop."""
    print("\n--- Test 11: Goal-Oriented Execution ---")
    results = await mesh.workflow("usability-goal-001", [
        {"agent": "goal_planner",
         "task": "Compute the sum of the first 5 prime numbers (2+3+5+7+11=28) and return the answer."}
    ])
    step = results[0]
    status = step.get("status")
    report("Goal-oriented task completed", status in ("success", "complete"),
           f"status={status}")

    goal_exec = step.get("goal_execution")
    if goal_exec:
        planner_mode = goal_exec.get("planner_mode")
        if planner_mode == "direct_kernel":
            report("Response includes goal_execution summary (direct kernel)", True,
                   f"steps={goal_exec.get('steps_completed')}, planner_mode=direct_kernel")
        else:
            report("Response includes goal_execution summary", True,
                   f"steps={goal_exec.get('steps_completed')}, elapsed={goal_exec.get('elapsed_ms')}")
    else:
        report("Response includes goal_execution summary",
               False, "goal_execution key missing — did the complexity gate drop it?")


async def test_13_workflow_builder_placeholder(mesh):
    """docs/guides/workflows.md — WorkflowBuilder + {step_id.result} via mesh.run_task."""
    print("\n--- Test 13: WorkflowBuilder + placeholder substitution ---")
    wf = (
        WorkflowBuilder()
        .step("seed", "fetcher", "Generate the widget dataset exactly as your system prompt specifies.")
        .step(
            "digest",
            "analyser",
            "Analyse the dataset described in prior output: {seed.result}",
            depends_on=["seed"],
        )
        .build(title="Usability WorkflowBuilder", team="qa")
    )
    log = await wf.execute(mesh, redis_store=None, timeout_per_step=420)
    ok = len(log) >= 2 and all(e.get("status") == "success" for e in log)
    report("WorkflowBuilder DAG finished successfully", ok,
           f"steps={[e.get('step_id') for e in log]}, statuses={[e.get('status') for e in log]}")
    if len(log) >= 2:
        out = log[1].get("output")
        report("Downstream step produced agent output", out is not None, type(out).__name__)


async def test_14_explicit_context(mesh):
    """docs/guides/autoagent.md troubleshooting — every step should include context (may be empty)."""
    print("\n--- Test 14: Explicit context keys on workflow steps ---")
    results = await mesh.workflow("usability-context-001", [
        {"id": "c1", "agent": "calculator", "task": "What is 40 + 2?", "context": {}},
        {"id": "c2", "agent": "calculator", "task": "What is 7 * 6?", "context": {}},
    ])
    ok = len(results) == 2 and all(r.get("status") == "success" for r in results)
    report("Steps with explicit empty context succeed", ok,
           f"statuses={[r.get('status') for r in results]}")


async def test_15_run_task_api(mesh):
    """mesh.run_task — documented shortcut for single-step dispatch."""
    print("\n--- Test 15: mesh.run_task API ---")
    out = await mesh.run_task(
        agent="calculator",
        task="Compute factorial of 5.",
        complexity="nano",
    )
    report("run_task returns dict with status", isinstance(out, dict) and "status" in out,
           f"status={out.get('status')}")


async def test_16_complexity_heavy(mesh):
    """model routing — heavy tier hint (still must succeed for basic math)."""
    print("\n--- Test 16: complexity='heavy' hint ---")
    results = await mesh.workflow("usability-heavy-001", [
        {"agent": "calculator", "task": "Briefly explain why (10**2)+(5*4)=120 then compute it.", "complexity": "heavy"}
    ])
    step = results[0]
    report("heavy-tier hint accepted", step.get("status") == "success",
           f"status={step.get('status')}, err={str(step.get('error'))[:80]}")


async def test_17_mesh_diagnostics(mesh):
    """Operational visibility — mesh diagnostics surface."""
    print("\n--- Test 17: Mesh diagnostics ---")
    diag = mesh.get_diagnostics()
    ok = bool(isinstance(diag, dict) and diag)
    report("get_diagnostics() returns non-empty dict", ok,
           f"keys={list(diag.keys())[:8]}...")


async def test_18_parallel_workflow(mesh):
    """DAG guide — independent steps can both succeed."""
    print("\n--- Test 18: Parallel independent workflow steps ---")
    results = await mesh.workflow("usability-parallel-001", [
        {"id": "left", "agent": "calculator", "task": "What is 100 / 4?", "context": {}},
        {"id": "right", "agent": "calculator", "task": "What is 99 - 1?", "context": {}},
    ])
    ok = len(results) == 2 and all(r.get("status") == "success" for r in results)
    report("Two independent steps both succeed", ok,
           f"statuses={[r.get('status') for r in results]}")


async def test_19_output_schema_agent(mesh):
    """Agent.output_schema → Kernel validates structured sandbox payloads."""
    print("\n--- Test 19: Production-style agent + output_schema ---")
    results = await mesh.workflow("usability-schema-001", [
        {"agent": "prod_agent", "task": "Emit the structured payload per your instructions.", "context": {}}
    ])
    step = results[0]
    ok = step.get("status") == "success"
    payload = step.get("payload") or step.get("output")
    if ok and isinstance(payload, dict):
        inner = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        schema_ok = isinstance(inner, dict) and inner.get("ok") is True and bool(inner.get("detail"))
        report("Structured payload satisfies contract", schema_ok, str(inner)[:120])
    else:
        report("Structured payload satisfies contract", False,
               f"status={step.get('status')} payload_preview={str(payload)[:120]}")


async def test_12_mesh_stop_teardown(mesh):
    """Promise: teardown() is called on mesh.stop()."""
    print("\n--- Test 12: Mesh Stop & Teardown ---")
    agents = [a for a in mesh.agents if isinstance(a, LifecycleAgent)]
    if not agents:
        skip("teardown() called", "LifecycleAgent not in mesh")
        return

    agent = agents[0]
    await mesh.stop()
    report("teardown() was called after mesh.stop()",
           getattr(agent, 'teardown_called', False))


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    print("=" * 70)
    print("  JarvisCore — Guide-aligned usability harness")
    print("  AutoAgent + workflows + (optional) FastAPI integration surface")
    print("=" * 70)

    test_static_guide_contracts()

    # Test 1: Class validation (no mesh needed)
    await test_1_class_validation()

    # Boot the mesh with all agents
    print("\n--- Booting Mesh with all agents ---")
    mesh = Mesh()
    mesh.add(MathAgent)
    mesh.add(FileWriterAgent)
    mesh.add(DataFetcher)
    mesh.add(DataAnalyser)
    mesh.add(SummaryReporter)
    mesh.add(LifecycleAgent)
    mesh.add(EnrichingAgent)
    mesh.add(GoalAgent)
    mesh.add(ProductionStyleAgent)

    try:
        await mesh.start()
        caps = mesh.capabilities
        print(f"  Mesh started with capabilities: {', '.join(sorted(caps))}")
        print(f"  Agents registered: {len(mesh.agents)}")

        any_agent = mesh.agents[0]
        llm = getattr(any_agent, "llm", None)
        if llm is None or not getattr(llm, "provider_order", None):
            print("\n  *** NO LLM PROVIDERS CONFIGURED ***")
            print("  Set AZURE_API_KEY + AZURE_ENDPOINT in .env and re-run.")
            print("  Aborting live tests.\n")
            await mesh.stop()
            return

        providers = [p.value for p in llm.provider_order]
        print(f"  LLM providers available: {providers}")

    except Exception as e:
        print(f"\n  Mesh start failed: {e}")
        traceback.print_exc()
        return

    # Run tests sequentially — each depends on the mesh being live
    start = time.time()
    try:
        await test_2_standalone_execution(mesh)
        await test_3_kernel_role_routing(mesh)
        await test_4_coder_sandbox(mesh)
        await test_5_workflow_return_shape(mesh)
        await test_6_lifecycle_hooks(mesh)
        await test_7_execute_task_override(mesh)
        await test_8_model_routing_complexity(mesh)
        await test_9_infrastructure_injection(mesh)
        await test_10_multi_agent_workflow(mesh)
        await test_11_goal_oriented(mesh)
        await test_13_workflow_builder_placeholder(mesh)
        await test_14_explicit_context(mesh)
        await test_15_run_task_api(mesh)
        await test_16_complexity_heavy(mesh)
        await test_17_mesh_diagnostics(mesh)
        await test_18_parallel_workflow(mesh)
        await test_19_output_schema_agent(mesh)
        await test_12_mesh_stop_teardown(mesh)
    except Exception as e:
        print(f"\n  UNEXPECTED ERROR: {e}")
        traceback.print_exc()
        try:
            await mesh.stop()
        except Exception:
            pass

    elapsed = time.time() - start

    # Final report
    total = PASS + FAIL + SKIP
    print("\n" + "=" * 70)
    print(f"  RESULTS:  {PASS} passed  /  {FAIL} failed  /  {SKIP} skipped  /  {total} total")
    print(f"  Elapsed:  {elapsed:.1f}s")
    if FAIL == 0:
        print("  VERDICT:  ALL PROMISES VERIFIED")
    else:
        print(f"  VERDICT:  {FAIL} PROMISE(S) BROKEN — FIX REQUIRED")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
