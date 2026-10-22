"""A three-agent research team for the Desk: scout, analyst, writer."""
import uuid

from jarviscore import AutoAgent, Mesh


class Scout(AutoAgent):
    role = "scout"
    capabilities = ["web_research"]
    description = "Finds primary sources on the live web and reads them."
    default_kernel_role = "researcher"
    system_prompt = "You find primary sources on the live web, read them, and cite every fact."


class Analyst(AutoAgent):
    role = "analyst"
    capabilities = ["analysis"]
    description = "Compares options on the evidence."
    default_kernel_role = "communicator"
    system_prompt = "You compare options strictly on the evidence and compute any figures with code."


class Writer(AutoAgent):
    role = "writer"
    capabilities = ["writing"]
    description = "Writes short, decisive briefs with sources."
    default_kernel_role = "communicator"
    system_prompt = "You write short, decisive briefs for engineering leads, citing sources."


def build_mesh():
    mesh = Mesh()
    mesh.add(Scout)
    mesh.add(Analyst)
    mesh.add(Writer)
    return mesh


async def submit_task(mesh, message, context):
    results = await mesh.workflow(f"desk-{uuid.uuid4().hex[:8]}", [
        {"agent": "scout",
         "task": f"From official documentation, gather the facts this request turns on: {message} "
                 "Report the facts with their sources; the analyst compares them next."},
        {"agent": "analyst", "depends_on": [0],
         "task": f"Compare the options on the scout's evidence for this request: {message} "
                 "The writer drafts the brief next."},
        {"agent": "writer", "depends_on": [1],
         "task": f"Write a decision brief of at most eight lines that answers: {message} "
                 "Name the pick, when to choose each alternative, and cite sources."},
    ])
    final = results[-1]
    envelope = {
        "status": final.get("status"),
        "result_summary": final.get("result_summary"),
        "error": final.get("error"),
    }
    if final.get("status") == "success" and final.get("result_summary"):
        envelope["artifacts"] = [{
            "schema_version": "1",
            "id": f"brief-{uuid.uuid4().hex[:8]}",
            "artifact_type": "document",
            "title": "Decision brief",
            "description": "Written by the writer from the scout's sources and the analyst's comparison.",
            "metadata": {"Agents": "Scout · Analyst · Writer", "Sources": "Live web"},
            "preview": {"kind": "text", "text": final["result_summary"]},
        }]
    return envelope
