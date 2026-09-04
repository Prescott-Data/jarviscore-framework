"""
Consolidated runtime data directory.

All runtime artifacts the framework writes relative to the working
directory live under a single gitignore-able root:

    .jarviscore/
        blob_storage/   local blob backend
        hitl_inbox/     HITL review requests
        logs/           execution results + function registry
        output/         coder sandbox write location (under workspace)
        step_outputs/   P2P step result cache
        traces/         execution / kernel traces

Nothing in this module creates directories; components create their
own subdirectory lazily on first write.
"""
import os

RUNTIME_DIR = ".jarviscore"


def runtime_path(*parts: str) -> str:
    """Path under the consolidated runtime dir, e.g. runtime_path('traces')."""
    return os.path.join(RUNTIME_DIR, *parts)
