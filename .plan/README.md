# `.plan/` — scratch plans (not source of truth)

Plans in this repo are **temporary**. Durable planning lives on **GitHub issues**.

## Pattern

1. **Scratch here** — write drafts under `.plan/` (any filename except this README).
2. **File as an issue** — turn the scratch into a GitHub issue (saga / epic / research / task). Prefer labels like `P3` + `enhancement` for research pins.
3. **Discard** — delete the scratch file (or leave it; it is gitignored). Do **not** commit plan docs to the tree.

## Agent rules

- Do **not** add `PLAN.md`, `docs/plan*`, or other long-lived plan files to the repo.
- Do **not** treat this folder as documentation to ship.
- When the user says “plan it” / “pin it” / “file it”: draft in `.plan/`, `gh issue create` (or comment on an existing issue), then remove the scratch if they want it gone.
- Link related issues from the new issue body; update saga/epic issues when the plan changes the north star.

## What’s tracked

| Path | Git |
|---|---|
| `.plan/README.md` | committed (this pattern) |
| `.plan/*` (everything else) | **gitignored** scratch |

## Examples

```text
.plan/federated-loft-mesh.md   →  gh issue  (research)  →  delete scratch
.plan/wave-3-notes.md          →  comment on saga/#1    →  delete scratch
```
