# DX Harnesses

These scripts test JarvisCore the way a developer experiences it: by following
the guides end to end. Unit tests prove functions work. These harnesses prove
the developer journey works. Run them before every release and after any change
to the profiles, the kernel, the planner, or the orchestration layer.

## The harnesses

| Script | Journey | Needs an LLM? |
|---|---|---|
| `dx_customagent.py` | CustomAgent: workflows, step identity, `mesh.fanout()` | No |
| `dx_autoagent.py` | AutoAgent: loud pre-start errors, `single_response`, a kernel task | Yes |
| `dx_goalmode.py` | Goal mode: planning with `depends_on`, parallel steps, persistence, resume | Yes |

## Running them

The CustomAgent harness runs offline:

```bash
python3 harnesses/dx_customagent.py
```

The other two need live LLM credentials in the environment (the same variables
the framework reads, for example `AZURE_API_KEY` and `AZURE_ENDPOINT`):

```bash
set -a && source /path/to/your/.env && set +a
python3 harnesses/dx_autoagent.py
python3 harnesses/dx_goalmode.py
```

Each harness prints one line per check and exits non-zero if any check fails.

## Why harnesses and not just tests

Unit tests mock the LLM and the mesh, so they cannot catch a guide that
recommends a method that does not exist, a contract that silently misroutes,
or an envelope that only breaks with real model output. Each of those has
happened. The harnesses caught them because they do exactly what the
documentation tells a developer to do.

When a harness fails, treat it as a release blocker: either the framework
broke the journey or the documentation describes a journey that no longer
exists. Fix whichever one is lying.

## Adding a harness

Write it as a developer story, not a test matrix. Pick one guide, follow it
top to bottom, and check what a reader would expect at each step. Keep checks
observable (status fields, result shapes, timing) and print clearly. If your
harness needs credentials, say so in its docstring and in the table above.
