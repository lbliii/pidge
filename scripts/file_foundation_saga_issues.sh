#!/usr/bin/env bash
# File Foundation / S-grade loft saga > epics > tasks (child of saga #1).
# Scratch companion: .plan/foundation-sgrade-loft.md
set -euo pipefail
REPO=lbliii/pidge

issue_id() {
  local n=$1
  gh api graphql -f query="query { repository(owner:\"lbliii\", name:\"pidge\") { issue(number:$n) { id } } }" --jq '.data.repository.issue.id'
}

link_sub() {
  local parent=$1 child=$2
  local pid cid
  pid=$(issue_id "$parent")
  cid=$(issue_id "$child")
  gh api graphql -f query='mutation($pid:ID!, $cid:ID!) {
    addSubIssue(input: {issueId: $pid, subIssueId: $cid, replaceParent: true}) {
      issue { number }
      subIssue { number }
    }
  }' -f pid="$pid" -f cid="$cid" --jq '{parent: .data.addSubIssue.issue.number, child: .data.addSubIssue.subIssue.number}'
}

num() { echo "$1" | sed -n 's|.*/issues/\([0-9]*\).*|\1|p'; }

echo "Creating saga…"
SAGA_URL=$(gh issue create --repo "$REPO" --title "[Saga] Foundation for an S-grade loft" --label "saga,P1" --body "$(cat <<'EOF'
## North star

Saga [#1](https://github.com/lbliii/pidge/issues/1) got the desk real. Closed saga [#54](https://github.com/lbliii/pidge/issues/54) raised object craft. This successor makes the **codebase and product surfaces strong enough that the next features (stamps, trust polish, eventual federation) don’t fight the architecture**.

**One sentence:** A single loft on `pidge.lol` where architecture, errors, and residue feel as intentional as Mail/People — so extensions plug in instead of sprawling `web.py` / dual-store further.

## Provenance

- Readiness conversation (Aug 2026)
- Experience contract: [`design/experience-system.md`](https://github.com/lbliii/pidge/blob/main/design/experience-system.md)
- Parent / prior: [#1](https://github.com/lbliii/pidge/issues/1), [#54](https://github.com/lbliii/pidge/issues/54)

## Sequencing (locked)

Foundation-first, then finish surfaces, then trust productization.

1. Honesty & errors
2. Architecture spine
3. Store confidence
4. Residue & rituals
5. Loft trust productization

Delight (stamps [#75](https://github.com/lbliii/pidge/issues/75)) and federation ([#22](https://github.com/lbliii/pidge/issues/22)) stay linked Later — they consume this foundation; they don’t block it.

## Grade targets

| Category | From | To | Owned by |
| --- | --- | --- | --- |
| Error messaging / handling | B | A+ | Epic 1 |
| Encapsulation | C+ | A | Epic 2 |
| DRY / decomposability | C | A | Epics 2–3 |
| Composability (code) | B | A+ | Epic 2 |
| Residue UX (Calendar/Wall/Agents) | C | A | Epic 4 |
| Auth / loft trust product | A- | A+ | Epic 5 |
| Core loop / discovery | A- / A | hold | already shipped |

## Workstreams (epics)

Tracked as native GitHub sub-issues:

1. Honesty and errors
2. Architecture spine
3. Store confidence
4. Residue and rituals
5. Loft trust productization

## Constraints

- No UI free-compose textarea as the write path
- Agent credential ≠ browser session
- Seal irreversible; Autopilot MCP seal remains opt-in with acknowledge
- Discovery public; credentials human-minted
- Design mocks lead for residue/stamps; production follows
- Do not invent federation in this saga

## Explicitly Later (linked, not blocking)

| Issue | Why |
| --- | --- |
| [#75](https://github.com/lbliii/pidge/issues/75) stamps (+ [#78](https://github.com/lbliii/pidge/issues/78)/[#79](https://github.com/lbliii/pidge/issues/79)) | Delight after residue; consumes architecture epic |
| [#22](https://github.com/lbliii/pidge/issues/22) federation | Research; needs honest Beyond + architecture first |
| [#44](https://github.com/lbliii/pidge/issues/44) recipient coerce | Chirp dependency |
| [#30](https://github.com/lbliii/pidge/issues/30) trust ladder follow-ons | Consumes loft-trust epic; do not re-scope here |

## Success signal

Someone can extend Calendar or Stamps without touching MCP wiring or inventing a third origin resolver; failed pin/act never looks like success; Postgres path is tested; invite-only loft exists; Calendar/Wall/Agents feel first-class.
EOF
)")
SAGA=$(num "$SAGA_URL")
echo "SAGA=#$SAGA $SAGA_URL"
link_sub 1 "$SAGA" || true

###############################################################################
# Epic 1 — Honesty and errors
###############################################################################
E1_URL=$(gh issue create --repo "$REPO" --title "Epic: Honesty and errors — kill silent failure" --label "epic,P1" --body "$(cat <<EOF
## Intent

Kill silent failure; make UI + MCP errors trustworthy (grade B → A+).

## Parent

Sub-issue of #$SAGA.

## Exit

No mutating path swallows errors; dogfood still green.
EOF
)")
E1=$(num "$E1_URL")
echo "E1=#$E1"
link_sub "$SAGA" "$E1"

T11=$(num "$(gh issue create --repo "$REPO" --title "Ban contextlib.suppress on mutating POSTs; surface real errors" --label "enhancement,P1" --body "$(cat <<EOF
## Parent

Sub-issue of #$E1 (Honesty and errors).

## Work

- Audit \`src/pidge/web.py\` mutating POSTs (wall pin, people actions, etc.)
- Remove \`contextlib.suppress\` that hides PermissionError/LookupError/ValueError
- Re-render with \`.alert\` or redirect with honest error — never look like success on failure

## Exit

Failed pin/connect/accept shows a message; tests cover at least one failure path.
EOF
)")")
link_sub "$E1" "$T11"

T12=$(num "$(gh issue create --repo "$REPO" --title "Standardize route error mapping (validation / authz / 404)" --label "enhancement,P1" --body "$(cat <<EOF
## Parent

Sub-issue of #$E1 (Honesty and errors).

## Work

- Validation → field/alert with service ValueError text
- Authz → clear message or honest 403 for the actor
- Missing → 404
- Stop folding PermissionError into generic \"Not found\" where it hides useful truth for the signed-in actor

## Exit

Documented convention in code comments or a short module docstring; thread/delivery/compose follow it.
EOF
)")")
link_sub "$E1" "$T12"

T13=$(num "$(gh issue create --repo "$REPO" --title "MCP error message prefixes agents can parse" --label "enhancement,P1,mcp" --body "$(cat <<EOF
## Parent

Sub-issue of #$E1 (Honesty and errors).

## Work

Thin convention on raised PermissionError / ValueError / LookupError from MCP tools:

- \`missing_scope: …\`
- \`not_found: …\`
- \`invalid: …\`
- \`forbidden: …\` (authz)

Keep human-readable remainder. Update tools + tests.

## Exit

Agent can branch on prefix; existing auth-edge tests still pass (update assertions as needed).
EOF
)")")
link_sub "$E1" "$T13"

T14=$(num "$(gh issue create --repo "$REPO" --title "Beyond-the-loft copy: address book ≠ delivery" --label "enhancement,P1,design" --body "$(cat <<EOF
## Parent

Sub-issue of #$E1 (Honesty and errors).

## Work

Honest copy on People (Beyond), \`/connect\`, and \`llms.txt\` / \`llms-full.txt\`: external handles are addressable locally; they are **not** cross-loft delivery until federation (#22).

## Exit

No implication that Beyond contacts receive sealed packets on another loft.
EOF
)")")
link_sub "$E1" "$T14"

# Backfill epic task table
gh issue edit "$E1" --repo "$REPO" --body "$(cat <<EOF
## Intent

Kill silent failure; make UI + MCP errors trustworthy (grade B → A+).

## Parent

Sub-issue of #$SAGA.

## Tasks

| Issue | Work |
| --- | --- |
| #$T11 | Ban suppress on mutating POSTs |
| #$T12 | Standardize route error mapping |
| #$T13 | MCP error message prefixes |
| #$T14 | Beyond-the-loft copy honesty |

## Exit

No mutating path swallows errors; dogfood still green.
EOF
)"

###############################################################################
# Epic 2 — Architecture spine
###############################################################################
E2_URL=$(gh issue create --repo "$REPO" --title "Epic: Architecture spine — decompose gods so features compose" --label "epic,P1" --body "$(cat <<EOF
## Intent

Decompose \`web.py\` / leaky store access so features compose (encapsulation C+ → A; DRY/composability → A / A+).

## Parent

Sub-issue of #$SAGA.

## Exit

New residue feature touches one routes module + service methods; public origin cannot diverge.
EOF
)")
E2=$(num "$E2_URL")
echo "E2=#$E2"
link_sub "$SAGA" "$E2"

T21=$(num "$(gh issue create --repo "$REPO" --title "Split web.py into http / mcp / views modules" --label "enhancement,P1" --body "$(cat <<EOF
## Parent

Sub-issue of #$E2 (Architecture spine).

## Work

Split \`src/pidge/web.py\` (~1.5k) into modules, e.g.:

- \`create_app\` stays thin
- HTTP routes
- MCP \`@app.tool\` registrations
- View helpers (desk / mail / delivery context)

Preserve behavior; full pytest green.

## Exit

No single file owns routing + MCP + presentation helpers.
EOF
)")")
link_sub "$E2" "$T21"

T22=$(num "$(gh issue create --repo "$REPO" --title "Service boundary: HTTP/MCP call PidgeService only" --label "enhancement,P1" --body "$(cat <<EOF
## Parent

Sub-issue of #$E2 (Architecture spine).

## Work

- Ban \`service.store.*\` from routes and MCP tools
- Add list/query methods on \`PidgeService\` as needed
- Keep authz rules in the service layer

## Exit

Grep for \`service.store\` under route/tool code returns nothing (tests may still use store fixtures).
EOF
)")")
link_sub "$E2" "$T22"

T23=$(num "$(gh issue create --repo "$REPO" --title "Unify public origin resolution (discovery + seal challenge)" --label "enhancement,P1" --body "$(cat <<EOF
## Parent

Sub-issue of #$E2 (Architecture spine).

## Work

One helper for loft origin (build on \`discovery.resolve_public_origin\`); seal challenge URLs and MCP snippet URLs share it. Remove divergent fallbacks in \`PidgeService._resolve_public_origin\`.

## Exit

Single code path; tests cover config origin + request fallback.
EOF
)")")
link_sub "$E2" "$T23"

T24=$(num "$(gh issue create --repo "$REPO" --title "Shared tests/conftest.py helpers (_csrf, _cookie, _setup_owner)" --label "enhancement,P1" --body "$(cat <<EOF
## Parent

Sub-issue of #$E2 (Architecture spine).

## Work

- Add \`tests/conftest.py\` with shared cookie/CSRF/setup helpers
- Delete duplicated copies across \`tests/test_*.py\`
- Keep dogfood script helpers separate unless trivial to share

## Exit

One definition of setup-owner; all async tests import it.
EOF
)")")
link_sub "$E2" "$T24"

T25=$(num "$(gh issue create --repo "$REPO" --title "Guardrail: MCP_TOOLS catalog matches registered @app.tool names" --label "enhancement,P1,mcp" --body "$(cat <<EOF
## Parent

Sub-issue of #$E2 (Architecture spine).

## Work

Test that \`discovery.MCP_TOOLS\` names equal the set of tools registered on the Chirp app (or exported registry). Fail CI on drift.

## Exit

Renaming a tool without updating the discovery catalog breaks CI.
EOF
)")")
link_sub "$E2" "$T25"

gh issue edit "$E2" --repo "$REPO" --body "$(cat <<EOF
## Intent

Decompose \`web.py\` / leaky store access so features compose (encapsulation C+ → A; DRY/composability → A / A+).

## Parent

Sub-issue of #$SAGA.

## Tasks

| Issue | Work |
| --- | --- |
| #$T21 | Split web.py into http / mcp / views |
| #$T22 | Service boundary (no store from routes/tools) |
| #$T23 | Unify public origin |
| #$T24 | Shared test conftest helpers |
| #$T25 | MCP_TOOLS sync guardrail |

## Exit

New residue feature touches one routes module + service methods; public origin cannot diverge.
EOF
)"

###############################################################################
# Epic 3 — Store confidence
###############################################################################
E3_URL=$(gh issue create --repo "$REPO" --title "Epic: Store confidence — end Memory/Postgres drift fear" --label "epic,P1" --body "$(cat <<EOF
## Intent

End MemoryStore vs PostgresStore drift fear (DRY / tech debt → A).

## Parent

Sub-issue of #$SAGA.

## Exit

Production store path covered; dual-impl risk consciously reduced.
EOF
)")
E3=$(num "$E3_URL")
echo "E3=#$E3"
link_sub "$SAGA" "$E3"

T31=$(num "$(gh issue create --repo "$REPO" --title "Extract shared store helpers (reduce Memory/Postgres duplication)" --label "enhancement,P1" --body "$(cat <<EOF
## Parent

Sub-issue of #$E3 (Store confidence).

## Work

Extract shared query/helpers used by both MemoryStore and PostgresStore in \`src/pidge/store.py\` (or thin adapter over one SQL-shaped core for the hot path). Prefer reducing copy-paste over a big-bang rewrite.

## Exit

Measurable LOC reduction in duplicated seal/list/token paths; behavior unchanged.
EOF
)")")
link_sub "$E3" "$T31"

T32=$(num "$(gh issue create --repo "$REPO" --title "Postgres integration tests (setup, seal, challenge, token revoke)" --label "enhancement,P1" --body "$(cat <<EOF
## Parent

Sub-issue of #$E3 (Store confidence).

## Work

Marked suite or CI job against real \`DATABASE_URL\` / Testcontainers covering at least:

- loft setup
- draft → enrich → seal
- seal challenge consume-once
- agent token revoke kills MCP

## Exit

Postgres path fails CI when Memory-only assumptions break.
EOF
)")")
link_sub "$E3" "$T32"

T33=$(num "$(gh issue create --repo "$REPO" --title "SCHEMA_SQL single source documented; drift fails CI" --label "enhancement,P1" --body "$(cat <<EOF
## Parent

Sub-issue of #$E3 (Store confidence).

## Work

- Document \`SCHEMA_SQL\` as the schema source of truth
- Add a guard (test or check) so migrations/docs cannot silently diverge from what stores expect

## Exit

Contributor knows where schema lives; CI catches obvious drift.
EOF
)")")
link_sub "$E3" "$T33"

gh issue edit "$E3" --repo "$REPO" --body "$(cat <<EOF
## Intent

End MemoryStore vs PostgresStore drift fear (DRY / tech debt → A).

## Parent

Sub-issue of #$SAGA.

## Tasks

| Issue | Work |
| --- | --- |
| #$T31 | Shared store helpers |
| #$T32 | Postgres integration tests |
| #$T33 | SCHEMA_SQL single source + CI |

## Exit

Production store path covered; dual-impl risk consciously reduced.
EOF
)"

###############################################################################
# Epic 4 — Residue and rituals
###############################################################################
E4_URL=$(gh issue create --repo "$REPO" --title "Epic: Residue and rituals — Calendar, Wall, Agents first-class" --label "epic,P2,design,calendar" --body "$(cat <<EOF
## Intent

Calendar, Wall, and Agents feel first-class (residue UX C → A). Experience waves 4–5.

## Parent

Sub-issue of #$SAGA.

## Depends on

Epic Honesty (#$E1); prefers Architecture (#$E2).

## Exit

Experience-system residue/rituals no longer thin lists.
EOF
)")
E4=$(num "$E4_URL")
echo "E4=#$E4"
link_sub "$SAGA" "$E4"

T41=$(num "$(gh issue create --repo "$REPO" --title "Calendar page: holds as commitments (desk-peek parity)" --label "enhancement,P2,calendar,design" --body "$(cat <<EOF
## Parent

Sub-issue of #$E4 (Residue and rituals).

## Work

- Calendar list as commitments (states, confirm affordance if \`confirm_hold\` is unused)
- Align with desk hold peeks
- Design mock if production would otherwise invent UI

## Exit

Calendar feels like residue of seals, not a stub table.
EOF
)")")
link_sub "$E4" "$T41"

T42=$(num "$(gh issue create --repo "$REPO" --title "Wall page: pins as memory objects" --label "enhancement,P2,design" --body "$(cat <<EOF
## Parent

Sub-issue of #$E4 (Residue and rituals).

## Work

- Pins as memory objects (empty-state dignity, object-row contract)
- Pin failure UX from Honesty epic
- Desk peek parity

## Exit

Wall feels intentional; failed pin never silent.
EOF
)")")
link_sub "$E4" "$T42"

T43=$(num "$(gh issue create --repo "$REPO" --title "Agents ritual: secret-drawer shown-once mint UX" --label "enhancement,P2,auth,design,mcp" --body "$(cat <<EOF
## Parent

Sub-issue of #$E4 (Residue and rituals).

## Work

Design-led secret drawer for mint: bearer shown once, hard to accidentally leave on screen, Autopilot remains loud.

## Exit

Mint ritual matches experience-system \"Rituals\" layer — not a bare settings form forever.
EOF
)")")
link_sub "$E4" "$T43"

T44=$(num "$(gh issue create --repo "$REPO" --title "Delivery timeline fidelity (draft / enrich / deliver clocks)" --label "enhancement,P2,mail,design" --body "$(cat <<EOF
## Parent

Sub-issue of #$E4 (Residue and rituals).

## Work

Improve \`/sent/{id}\` ceremony timeline so draft/enrich/deliver clocks reflect real events when cheap; avoid fake identical timestamps if we have better data.

## Exit

Delivery page story feels true, not placeholder.
EOF
)")")
link_sub "$E4" "$T44"

gh issue edit "$E4" --repo "$REPO" --body "$(cat <<EOF
## Intent

Calendar, Wall, and Agents feel first-class (residue UX C → A). Experience waves 4–5.

## Parent

Sub-issue of #$SAGA.

## Depends on

Epic Honesty (#$E1); prefers Architecture (#$E2).

## Tasks

| Issue | Work |
| --- | --- |
| #$T41 | Calendar commitments UX |
| #$T42 | Wall pins UX |
| #$T43 | Agents secret-drawer mint |
| #$T44 | Delivery timeline fidelity |

## Exit

Experience-system residue/rituals no longer thin lists.
EOF
)"

###############################################################################
# Epic 5 — Loft trust productization
###############################################################################
E5_URL=$(gh issue create --repo "$REPO" --title "Epic: Loft trust productization — invite-only private loft" --label "epic,P2,auth" --body "$(cat <<EOF
## Intent

Match trust model to \"private loft,\" not open register (auth A- → A+).

## Parent

Sub-issue of #$SAGA.

## Exit

Stranger cannot join loft without invitation; Autopilot remains loud and gated.
EOF
)")
E5=$(num "$E5_URL")
echo "E5=#$E5"
link_sub "$SAGA" "$E5"

T51=$(num "$(gh issue create --repo "$REPO" --title "Invite-only registration gate after loft setup" --label "enhancement,P2,auth" --body "$(cat <<EOF
## Parent

Sub-issue of #$E5 (Loft trust productization).

## Work

After setup, registration requires an owner-issued invite (or equivalent bootstrap token path for additional members). Open \`/register\` without invite must fail closed.

## Exit

Stranger finding \`pidge.lol/register\` cannot join the loft.
EOF
)")")
link_sub "$E5" "$T51"

T52=$(num "$(gh issue create --repo "$REPO" --title "Parent-link trust ladder follow-ons (#30 / #42 / #43) under loft trust" --label "enhancement,P3,auth,mcp" --body "$(cat <<EOF
## Parent

Sub-issue of #$E5 (Loft trust productization).

## Work

Do **not** re-scope. Comment/link so [#30](https://github.com/lbliii/pidge/issues/30), [#42](https://github.com/lbliii/pidge/issues/42), [#43](https://github.com/lbliii/pidge/issues/43) are clearly \"next after invite-only / consumes foundation saga.\" Optionally add as GitHub sub-issues of #$E5 if the API allows without disrupting existing parents.

## Exit

Board shows trust follow-ons as downstream of this epic.
EOF
)")")
link_sub "$E5" "$T52"

gh issue edit "$E5" --repo "$REPO" --body "$(cat <<EOF
## Intent

Match trust model to \"private loft,\" not open register (auth A- → A+).

## Parent

Sub-issue of #$SAGA.

## Tasks

| Issue | Work |
| --- | --- |
| #$T51 | Invite-only registration gate |
| #$T52 | Parent-link #30 / #42 / #43 (no re-scope) |

Saga #1 Autopilot constraint correction is a comment on [#1](https://github.com/lbliii/pidge/issues/1) (filed with this saga), not a separate code task.

## Related Later (do not re-scope)

- [#30](https://github.com/lbliii/pidge/issues/30) Trust ladder follow-ons
- [#42](https://github.com/lbliii/pidge/issues/42) MCP App draft card
- [#43](https://github.com/lbliii/pidge/issues/43) Autopilot mint hardening

## Exit

Stranger cannot join loft without invitation; Autopilot remains loud and gated.
EOF
)"

# Final saga body with epic numbers
gh issue edit "$SAGA" --repo "$REPO" --body "$(cat <<EOF
## North star

Saga [#1](https://github.com/lbliii/pidge/issues/1) got the desk real. Closed saga [#54](https://github.com/lbliii/pidge/issues/54) raised object craft. This successor makes the **codebase and product surfaces strong enough that the next features (stamps, trust polish, eventual federation) don’t fight the architecture**.

**One sentence:** A single loft on \`pidge.lol\` where architecture, errors, and residue feel as intentional as Mail/People — so extensions plug in instead of sprawling \`web.py\` / dual-store further.

## Provenance

- Readiness conversation (Aug 2026)
- Experience contract: [\`design/experience-system.md\`](https://github.com/lbliii/pidge/blob/main/design/experience-system.md)
- Parent / prior: [#1](https://github.com/lbliii/pidge/issues/1), [#54](https://github.com/lbliii/pidge/issues/54)

## Sequencing (locked)

Foundation-first, then finish surfaces, then trust productization.

1. Honesty & errors → #$E1
2. Architecture spine → #$E2
3. Store confidence → #$E3
4. Residue & rituals → #$E4
5. Loft trust productization → #$E5

Delight (stamps [#75](https://github.com/lbliii/pidge/issues/75)) and federation ([#22](https://github.com/lbliii/pidge/issues/22)) stay linked Later — they consume this foundation; they don’t block it.

## Grade targets

| Category | From | To | Owned by |
| --- | --- | --- | --- |
| Error messaging / handling | B | A+ | #$E1 |
| Encapsulation | C+ | A | #$E2 |
| DRY / decomposability | C | A | #$E2 / #$E3 |
| Composability (code) | B | A+ | #$E2 |
| Residue UX (Calendar/Wall/Agents) | C | A | #$E4 |
| Auth / loft trust product | A- | A+ | #$E5 |
| Core loop / discovery | A- / A | hold | already shipped |

## Workstreams (epics)

| Epic | Issue |
| --- | --- |
| Honesty and errors | #$E1 |
| Architecture spine | #$E2 |
| Store confidence | #$E3 |
| Residue and rituals | #$E4 |
| Loft trust productization | #$E5 |

## Suggested build order

1. #$E1 errors
2. #$E2 architecture
3. #$E3 store (can overlap late #$E2)
4. #$E4 residue
5. #$E5 invite-only
6. Then stamps / [#30](https://github.com/lbliii/pidge/issues/30) / federation research

## Constraints

- No UI free-compose textarea as the write path
- Agent credential ≠ browser session
- Seal irreversible; Autopilot MCP seal remains opt-in with acknowledge
- Discovery public; credentials human-minted
- Design mocks lead for residue/stamps; production follows
- Do not invent federation in this saga

## Explicitly Later (linked, not blocking)

| Issue | Why |
| --- | --- |
| [#75](https://github.com/lbliii/pidge/issues/75) stamps (+ [#78](https://github.com/lbliii/pidge/issues/78)/[#79](https://github.com/lbliii/pidge/issues/79)) | Delight after residue; consumes #$E2 |
| [#22](https://github.com/lbliii/pidge/issues/22) federation | Research; needs honest Beyond + architecture first |
| [#44](https://github.com/lbliii/pidge/issues/44) recipient coerce | Chirp dependency |
| [#30](https://github.com/lbliii/pidge/issues/30) trust ladder follow-ons | Consumes #$E5; do not re-scope here |

## Success signal

Someone can extend Calendar or Stamps without touching MCP wiring or inventing a third origin resolver; failed pin/act never looks like success; Postgres path is tested; invite-only loft exists; Calendar/Wall/Agents feel first-class.
EOF
)"

echo
echo "DONE saga=#$SAGA"
echo "  E1=#$E1 E2=#$E2 E3=#$E3 E4=#$E4 E5=#$E5"
echo "  honesty: #$T11 #$T12 #$T13 #$T14"
echo "  arch: #$T21 #$T22 #$T23 #$T24 #$T25"
echo "  store: #$T31 #$T32 #$T33"
echo "  residue: #$T41 #$T42 #$T43 #$T44"
echo "  trust: #$T51 #$T52"
echo "$SAGA" > /tmp/pidge-foundation-saga-num.txt
