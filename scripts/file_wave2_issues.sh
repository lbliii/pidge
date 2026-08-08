#!/usr/bin/env bash
# File Pidge saga > epics > tasks on GitHub.
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

num() { echo "$1" | grep -oE '[0-9]+$'; }

EXISTING=$(gh issue list --repo "$REPO" --search '"[Saga] Pidge"' --json number,title --jq '.[0].number // empty')
if [[ -n "$EXISTING" ]]; then
  echo "Saga already exists: #$EXISTING"
  gh issue list --repo "$REPO" --limit 40 --json number,title
  exit 0
fi

SAGA=$(gh issue create --repo "$REPO" --title "[Saga] Pidge — agent secretary desk (mail, calendar, wall)" --label "saga,P1,dogfood" --body "$(cat <<'EOF'
## North star

Pidge is your **agent’s secretary**: structured mail, calendar, and a personal wall of notes.

Agents write only via **MCP** with delegated scopes. Humans **review, seal, and act** in a hypermedia desk. No ChirpUI — oat/leather design from [`design/`](./tree/main/design).

One Railway deployment = one **loft**. Same-loft members are addressable from the directory; out-of-loft recipients require the address book (Battle.net / WoW friends model).

## Provenance

- Product plan: [`PLAN.md`](./blob/main/PLAN.md)
- Design mocks: [`design/`](./tree/main/design)
- Scaffold landed: Chirp app in `src/pidge/` (Postgres/MemoryStore, MCP tools, human seal, directory/contacts, calendar, wall)
- Related: [lbliii/chirp#959](https://github.com/lbliii/chirp/issues/959) Orrery · Chirp auth scopes / `@app.tool`

## Dogfood story

**Tonight at Nowadays** — agent drafts invite → enrich flight → human seals → Lucy RSVPs → hold + wall pin.

## Workstreams (epics)

Tracked as native GitHub sub-issues (not a checklist):

1. Dogfood path — scripted end-to-end Nowadays story
2. Compose UX — flight rail, agent-inbound polish, design mock cleanup
3. Auth hard edges — revoke kills MCP; seal stays session-only under test
4. Railway proof — Postgres deploy, setup, `/ready`
5. Design parity — desk/inbox/thread closer to mocks (still no ChirpUI)

## Constraints (non-negotiable)

- No UI free-compose textarea as the write path
- Seal is irreversible and **session-only** (MCP never seals)
- Acts, not prose replies
- Structured slots (who/when/where or explicit none) before seal
- Agent credential ≠ browser session cookie

## Not now

Cross-loft federation protocol; SMTP/IMAP; public social feed; Envelope-as-seal productization; multi-agent policy matrix.

## Success signal

An agent with a scoped token drafts and enriches a Pidge over `/mcp`; a human seals in the UI; the recipient RSVPs; a calendar hold and wall pin appear — on a Railway loft with Postgres.
EOF
)")
echo "SAGA=$SAGA"

E1=$(gh issue create --repo "$REPO" --title "Epic: Dogfood path — Nowadays end-to-end" --label "epic,P1,dogfood,mail,mcp" --body "## Intent

Make the **Tonight at Nowadays** story one command / one checklist away: mint agent → draft → enrich → seal → Lucy RSVP → hold + pin.

## Out of scope

Railway deploy (Epic: Railway proof). Full design polish (Epic: Design parity).")

E2=$(gh issue create --repo "$REPO" --title "Epic: Compose UX — flight rail + agent-inbound polish" --label "epic,P1,mail,mcp,design" --body "## Intent

Compose is agent-inbound only. Live enrichment should show on the flight rail; design mocks must drop the dictate textarea so product + mocks agree.

## Out of scope

New MCP tools beyond enrich/draft; federation.")

E3=$(gh issue create --repo "$REPO" --title "Epic: Auth hard edges — revoke, scopes, seal gate" --label "epic,P1,auth,mcp" --body "## Intent

Prove the two-identity model under tests: revoked tokens fail MCP; missing scopes fail loud; seal remains CSRF session-only and unreachable from \`/mcp\`.

## Out of scope

Passkeys (follow-on leaf); OAuth device-flow UX beyond mint/revoke.")

E4=$(gh issue create --repo "$REPO" --title "Epic: Railway proof — Postgres loft deploy" --label "epic,P1,railway,dogfood" --body "## Intent

Ship a real loft on Railway: app + Postgres, env vars, \`/setup\` with bootstrap token, \`/ready\` green, smoke of login + one sealed Pidge.

## Out of scope

Marketplace template publication; custom domain / passkeys RP.")

E5=$(gh issue create --repo "$REPO" --title "Epic: Design parity — desk surfaces vs mocks" --label "epic,P2,design,mail" --body "## Intent

Bring desk, inbox, thread, and compose closer to validated \`design/\` oat/leather visuals without adopting ChirpUI.

## Out of scope

New brand mark / pigeon logo; Tumblr-style wall.")

echo "E1=$E1 E2=$E2 E3=$E3 E4=$E4 E5=$E5"

S=$(num "$SAGA"); e1=$(num "$E1"); e2=$(num "$E2"); e3=$(num "$E3"); e4=$(num "$E4"); e5=$(num "$E5")
link_sub "$S" "$e1"
link_sub "$S" "$e2"
link_sub "$S" "$e3"
link_sub "$S" "$e4"
link_sub "$S" "$e5"

# --- Leaf tasks ---
mk_task() {
  local title=$1 labels=$2 body=$3
  gh issue create --repo "$REPO" --title "$title" --label "$labels" --body "$body"
}

# E1 leaves
T11=$(mk_task "Add Nowadays dogfood script (MCP draft → enrich → seal → RSVP)" "P1,dogfood,mcp,mail" "## Acceptance

- Script or \`make dogfood\` creates owner+Lucy (or uses fixtures), mints agent token, calls draft+enrich over MCP, seals via session, records RSVP, asserts hold+pin.
- Documented in README.
- Runs against MemoryStore locally without Postgres.")
T12=$(mk_task "Document agent MCP curl recipe for draft + enrich" "P2,dogfood,mcp,documentation" "## Acceptance

- README (or docs/) shows copy-paste curl for tools/list, draft_pidge, enrich_pidge with Bearer token.
- Points at Agents settings for mint.")
T13=$(mk_task "Contract test: sealed invite appears in recipient inbox" "P1,dogfood,mail" "## Acceptance

- Pytest covers author seal → recipient inbox visibility → rsvp_yes act (extend existing suite if needed).")

# E2 leaves
T21=$(mk_task "Wire compose flight rail to tool_events / SSE safely" "P1,mail,mcp,design" "## Acceptance

- Compose draft page updates flight steps when agent enrich runs (SSE or poll).
- Passes \`app.check()\` SSE contract rules (no bad sse-swap on connect root).")
T22=$(mk_task "Remove dictate textarea from design/ compose mock" "P2,design,mail" "## Acceptance

- \`design/compose.html\` shows agent-inbound / waiting / flight / seal — no free-type authoring box.
- design/README notes the constraint.")
T23=$(mk_task "Seal affordance: clear ready vs blocked slot states" "P2,mail,design" "## Acceptance

- Compose UI makes seal enabled/disabled reason obvious from slot status.")

# E3 leaves
T31=$(mk_task "Test: revoked agent token cannot call MCP tools" "P1,auth,mcp" "## Acceptance

- Mint → revoke → tools/call returns auth error.
- Active token still works.")
T32=$(mk_task "Test: missing scope denied on scoped tools" "P1,auth,mcp" "## Acceptance

- Token without pidge:notes.pin cannot pin_note; draft scope still works for draft_pidge.")
T33=$(mk_task "Test: seal_pidge is not an MCP tool and UI seal requires session" "P1,auth,mail,mcp" "## Acceptance

- tools/list has no seal tool.
- Unauthenticated seal POST redirects/fails; author session succeeds when slots ready.")

# E4 leaves
T41=$(mk_task "Railway: provision Postgres + set PIDGE_* env vars" "P1,railway" "## Acceptance

- Service linked to Postgres; DATABASE_URL, PIDGE_ENV, PIDGE_SECRET_KEY, PIDGE_BOOTSTRAP_TOKEN set.
- Documented in README.")
T42=$(mk_task "Railway smoke: /ready green and /setup claims loft" "P1,railway,dogfood" "## Acceptance

- Deploy SUCCESS; /ready 200; setup with bootstrap token creates owner; login works.")
T43=$(mk_task "Add Dockerfile or confirm Railpack Python 3.14 start command" "P2,railway" "## Acceptance

- Start command matches railway.json; RAILPACK_PYTHON_VERSION=3.14 noted.")

# E5 leaves
T51=$(mk_task "Port floating seal + hero rhythm onto desk home" "P2,design" "## Acceptance

- Desk first viewport closer to design/index.html composition (brand, one lead, actions) without ChirpUI.")
T52=$(mk_task "Inbox/thread visual pass against design mocks" "P2,design,mail" "## Acceptance

- Inbox list + thread/RSVP match design/inbox.html and design/lucy.html / thread.html tone.")
T53=$(mk_task "Compose empty state matches agent-inbound story" "P2,design,mcp" "## Acceptance

- compose_empty explains MCP path and links Agents; no textarea.")

echo "Tasks created; linking..."

link_sub "$e1" "$(num "$T11")"
link_sub "$e1" "$(num "$T12")"
link_sub "$e1" "$(num "$T13")"
link_sub "$e2" "$(num "$T21")"
link_sub "$e2" "$(num "$T22")"
link_sub "$e2" "$(num "$T23")"
link_sub "$e3" "$(num "$T31")"
link_sub "$e3" "$(num "$T32")"
link_sub "$e3" "$(num "$T33")"
link_sub "$e4" "$(num "$T41")"
link_sub "$e4" "$(num "$T42")"
link_sub "$e4" "$(num "$T43")"
link_sub "$e5" "$(num "$T51")"
link_sub "$e5" "$(num "$T52")"
link_sub "$e5" "$(num "$T53")"

echo "Done. Saga: $SAGA"
gh issue list --repo "$REPO" --limit 40
