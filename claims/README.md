# Claims

Every claim JarvisCore makes about control and evidence lives here, as a file,
next to the tests that back it. A claim is published only once its evidence
exists and passes; `tests/test_claims.py` fails the build when a claim names
evidence that does not exist.

Each file holds:

| Field | Meaning |
|---|---|
| `claim` | The exact wording. Websites and docs quote it, not a paraphrase. |
| `scope` | Where the claim holds: modes, components, paths. |
| `assumptions` | What must be true for it to hold (the threat model). |
| `not_claimed` | What a reader might infer but this does not promise. |
| `evidence` | Tests (`path::name`) that check it on every build. |
| `published` | Where the claim appears publicly, once it does. |

Evidence is conformance evidence within the stated scope and assumptions, not a
proof that no failure exists.
