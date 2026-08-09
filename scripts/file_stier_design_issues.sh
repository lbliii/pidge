#!/usr/bin/env bash
# File S-tier object-mail design saga > epics > tasks (child of saga #1).
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
SAGA_URL=$(gh issue create --repo "$REPO" --title "[Saga] S-tier object mail — projection room for sealed packets" --label "saga,P1,design,mail" --body "$(cat <<'EOF'
## North star (S-tier)

Pidge is a **private projection room for consequential objects** — not an inbox, not a chatbot transcript, not a calendar app with mail bolted on.

**One sentence:** Your agent gathers the world into a sealed packet; you decide; the other person receives something as considered as a letter and as useful as a product page.

### In the hand

- **The object is the product** — open a *title* (hero), then modules; chrome dissolves
- **Secretary, not author** — no free-type box; desk is judgment (seal / discard / act)
- **Kinds without modes** — invite / share / ask / fyi / note as genres
- **Enrich is craft; seal is ceremony** — optional blocks may degrade; seal is irreversible and calm
- **Deliver after commit** — “fly” only post-seal (fix Fly-before-Seal language)
- **Needs you = Continue Watching** — blotter shows incomplete human work only
- **Trust is quiet** — verified · short hash; agent tokens stay in a ritual settings surface
- **Two chairs, one object** — author CTA ≠ recipient CTA

### Emotional beat

Arrive → something needs you → open a packet that already knows → one decisive act → leave.

## Parent

Child saga of [#1](https://github.com/lbliii/pidge/issues/1). Complements [#26](https://github.com/lbliii/pidge/issues/26) (trust ladder) — this saga is **object craft + kinds + enrichment**, not mint presets.

## Workstreams (epics)

1. Language & IA — Draft → Enrich → Seal; slim chrome; Needs you
2. Message kinds & acts — taxonomy, badges, kind-aware act choosers
3. Enrichment blocks & rich canvas — `extras.blocks[]`, invite + share mocks
4. Design system kit — specimens, degraded/fallback states
5. Production port — schema `kind`, block render in Chirp templates (after mocks)

## Constraints

- No UI free-compose textarea as the write path
- who/when/where each `ready` or explicit `none` before seal
- Blocks optional for seal; slot readiness still gates seal
- Design mocks in `design/` lead; production follows
- Invite is one kind — not the product identity

## Success signal

A designer can open desk + rich invite + rich share mocks and feel the projection-room beat; production later renders the same block contract from sealed slots.
EOF
)")
SAGA=$(num "$SAGA_URL")
echo "SAGA=#$SAGA $SAGA_URL"
link_sub 1 "$SAGA" || true

###############################################################################
# Epic A — Language & IA
###############################################################################
EA_URL=$(gh issue create --repo "$REPO" --title "Epic: Language & IA — Draft → Enrich → Seal + Needs you" --label "epic,P1,design,mail" --body "$(cat <<EOF
## Intent

Fix inverted pigeon metaphor and overcrowded chrome so the S-tier beat is readable.

Compose steps must be **Draft → Enrich → Seal** (never Fly-before-Seal). Thread lifecycle **Drafted → Enriched → Sealed → Delivered → Acted**. Desk primary stack is **Needs you**.

## Parent

Sub-issue of #$SAGA.

## Out of scope

New MCP tools; production nav rewrite beyond what mocks prescribe (port is Epic: Production port).
EOF
)")
EA=$(num "$EA_URL")
echo "EA=#$EA"
link_sub "$SAGA" "$EA"

###############################################################################
# Epic B — Kinds & acts
###############################################################################
EB_URL=$(gh issue create --repo "$REPO" --title "Epic: Message kinds & acts — taxonomy + kind-aware choosers" --label "epic,P1,design,mail" --body "$(cat <<EOF
## Intent

Categorize send jobs and receive stances so Pidge is not “calendar invites only.”

Kinds: **invite · share · ask · fyi · remind · note**. Receive stances: **Needs act · Needs eyes · Result · Filed**. Acts are kind-scoped (RSVP invite-only).

## Parent

Sub-issue of #$SAGA.

## Out of scope

Full ask/remind mock pages (document only); production \`kind\` column (Production port epic).
EOF
)")
EB=$(num "$EB_URL")
echo "EB=#$EB"
link_sub "$SAGA" "$EB"

###############################################################################
# Epic C — Enrichment & canvas
###############################################################################
EC_URL=$(gh issue create --repo "$REPO" --title "Epic: Enrichment blocks & rich object canvas" --label "epic,P1,design,mail,mcp" --body "$(cat <<EOF
## Intent

Sealed Pidges render agent-fetched **typed blocks** (place/map/menu/reviews/article) as a hero-first object canvas — not three flat text cards.

Contract: \`extras.blocks[]\`. Agent webfetches outside Pidge; desk stores/renders.

## Parent

Sub-issue of #$SAGA.

## Dogfood

- Invite: Nowadays place packet (thread + lucy)
- Share: article packet (\`design/share.html\`) with when/where \`none\`

## Out of scope

In-process scraping; real map tile providers; image CDN proxy (defer).
EOF
)")
EC=$(num "$EC_URL")
echo "EC=#$EC"
link_sub "$SAGA" "$EC"

###############################################################################
# Epic D — System kit
###############################################################################
ED_URL=$(gh issue create --repo "$REPO" --title "Epic: Design system kit — enrichment specimens + degraded states" --label "epic,P1,design" --body "$(cat <<EOF
## Intent

If it isn’t on \`design/system.html\`, it isn’t in the system. Lock primitives + enrichment widgets including **degraded block** and **no-image fallback** (Apple/Netflix craft).

## Parent

Sub-issue of #$SAGA.
EOF
)")
ED=$(num "$ED_URL")
echo "ED=#$ED"
link_sub "$SAGA" "$ED"

###############################################################################
# Epic E — Production port
###############################################################################
EE_URL=$(gh issue create --repo "$REPO" --title "Epic: Production port — kind field + block render in Chirp templates" --label "epic,P2,design,mail,mcp" --body "$(cat <<EOF
## Intent

After mocks validate the vision, port to \`src/pidge/\`: optional \`kind\` on pidges, structured \`extras.blocks\`, kind-aware acts, slim nav, Draft/Enrich/Seal copy.

## Parent

Sub-issue of #$SAGA.

## Depends on

Epics Language & IA, Kinds & acts, Enrichment canvas, Design system kit (mocks first).
EOF
)")
EE=$(num "$EE_URL")
echo "EE=#$EE"
link_sub "$SAGA" "$EE"

###############################################################################
# Tasks — Epic A
###############################################################################
T=$(gh issue create --repo "$REPO" --title "Rename compose/thread step chrome to Draft → Enrich → Seal" --label "P1,design,mail" --body "$(cat <<EOF
## Parent

Sub-issue of #$EA (Language & IA). Saga #$SAGA.

## Problem

\`Agent → Fly → Seal\` and \`Dictated → Flew → Sealed\` invert the pigeon metaphor and overload “fly.”

## Acceptance

- [ ] \`design/compose.html\`, \`system.html\`, \`desk.html\`, \`thread.html\`, \`lucy.html\`, \`inbox.html\`, \`sent.html\`: visible copy uses **Draft / Enrich / Seal**
- [ ] Thread lifecycle chips: **Drafted → Enriched → Sealed → Delivered → Acted** (final chip kind-specific label OK)
- [ ] Side panel titled **Enriching** (not Flight); badge **Enriching** (not In flight / Flying)
- [ ] Kickers: \`Draft → enrich → seal\`
- [ ] CSS class names may keep \`.flight-rail\` temporarily; user-visible strings must change
- [ ] \`design/README.md\` documents the naming rule

## Files

\`design/compose.html\`, \`design/system.html\`, \`design/desk.html\`, \`design/thread.html\`, \`design/lucy.html\`, \`design/inbox.html\`, \`design/sent.html\`, \`design/README.md\`, optionally \`design/styles.css\` badge labels
EOF
)")
link_sub "$EA" "$(num "$T")"
echo "task rename $(num "$T")"

T=$(gh issue create --repo "$REPO" --title "Slim mock topbar: Desk · Mail · People · Account" --label "P1,design" --body "$(cat <<EOF
## Parent

Sub-issue of #$EA. Saga #$SAGA.

## Acceptance

- [ ] Primary chrome ≤4 items: Desk, Mail, People, Account (Agents under Account)
- [ ] Compose is not a permanent top-level tab (entry from desk/mail needs-you)
- [ ] Mail uses In|Out segmented control (not separate Sent nav)
- [ ] Applied on journey mocks touched this wave (\`desk\`, \`inbox\`, \`compose\`, \`system\`, \`agents\`, \`login\`, \`share\`)

## Note

Production \`layout.html\` port is Epic Production port — this task is mocks only.
EOF
)")
link_sub "$EA" "$(num "$T")"

T=$(gh issue create --repo "$REPO" --title "Desk blotter copy matches Needs you / Continue Watching beat" --label "P2,design" --body "$(cat <<EOF
## Parent

Sub-issue of #$EA. Saga #$SAGA.

## Acceptance

- [ ] \`design/desk.html\` primary stack = Needs you only
- [ ] Calendar/wall remain quiet peeks
- [ ] Empty / enriching copy uses Draft → Enrich → Seal language
- [ ] No four equal pillars competing with Needs you
EOF
)")
link_sub "$EA" "$(num "$T")"

###############################################################################
# Tasks — Epic B
###############################################################################
T=$(gh issue create --repo "$REPO" --title "Document send/receive kind taxonomy in design/README" --label "P1,design,documentation" --body "$(cat <<EOF
## Parent

Sub-issue of #$EB. Saga #$SAGA.

## Acceptance

- [ ] README tables for kinds: invite, share, ask, fyi, remind, note (slots, blocks, acts, mock-now?)
- [ ] Receive stances: Needs act, Needs eyes, Result, Filed
- [ ] Explicit “not a kind”: lifecycle state, enriching, hold/pin, loft vs external
- [ ] Design rules: invite ≠ product identity; fact strip hides \`none\`; acts kind-scoped; badge = kind + stance
EOF
)")
link_sub "$EB" "$(num "$T")"

T=$(gh issue create --repo "$REPO" --title "Mock kind badges + stance on object header and list rows" --label "P1,design,mail" --body "$(cat <<EOF
## Parent

Sub-issue of #$EB. Saga #$SAGA.

## Acceptance

- [ ] Object header shows kind badge (Invite / Share / …)
- [ ] List/needs-you rows show kind + stance where relevant (\`Invite · needs act\`, \`Share · sealed\`, \`Result · accepted\`)
- [ ] System kit specimens for badge variants
- [ ] No RSVP act chooser on share specimen
EOF
)")
link_sub "$EB" "$(num "$T")"

T=$(gh issue create --repo "$REPO" --title "Kind-aware act choosers: RSVP vs Ack/Pin" --label "P1,design,mail" --body "$(cat <<EOF
## Parent

Sub-issue of #$EB. Saga #$SAGA.

## Acceptance

- [ ] Invite recipient canvas: Accept / Decline / Maybe (existing rsvp-choice)
- [ ] Share recipient canvas: Ack / Pin (no RSVP)
- [ ] System kit shows both chooser variants
- [ ] Thread lifecycle final chip uses Acted label appropriate to kind
EOF
)")
link_sub "$EB" "$(num "$T")"

###############################################################################
# Tasks — Epic C
###############################################################################
T=$(gh issue create --repo "$REPO" --title "Specify extras.blocks[] contract (invite + share JSON)" --label "P1,design,mcp,documentation" --body "$(cat <<EOF
## Parent

Sub-issue of #$EC. Saga #$SAGA.

## Contract

\`extras\` remains a slot-like object with \`status\` plus \`blocks: []\`.

### Block types (this wave)

\`place\` · \`map\` · \`menu\` · \`reviews\` · \`article\` / \`link\`

Unknown \`type\` → generic link/note fallback card.

### Seal gating

Unchanged: \`who\` / \`when\` / \`where\` each \`ready\` or \`none\`. Blocks do **not** gate seal.

### Acceptance

- [ ] JSON examples for Nowadays invite and federation article share in \`design/README.md\`
- [ ] Field notes: image optional; \`fetched_at\` / \`source_url\` for freshness; lat/lng optional for map
- [ ] Explicit: agent webfetch is outside Pidge; MCP \`enrich_pidge\` carries structured extras
EOF
)")
link_sub "$EC" "$(num "$T")"

T=$(gh issue create --repo "$REPO" --title "Rich invite object canvas on design/thread.html + lucy.html" --label "P1,design,mail" --body "$(cat <<EOF
## Parent

Sub-issue of #$EC. Saga #$SAGA.

## Acceptance

- [ ] Hero-first place block (artwork or monogram fallback) inside bubble
- [ ] Fact strip: who/when/where only (no empty none slots)
- [ ] Map / menu / reviews blocks below hero
- [ ] Author thread vs Lucy recipient: different primary acts (no competing CTAs)
- [ ] Lifecycle chips use Enriched / Acted language
- [ ] Feels like a forwarded place packet, not three equal text tiles

## Files

\`design/thread.html\`, \`design/lucy.html\`, \`design/styles.css\`, \`design/flow.css\`
EOF
)")
link_sub "$EC" "$(num "$T")"

T=$(gh issue create --repo "$REPO" --title "Add design/share.html — non-event article packet" --label "P1,design,mail" --body "$(cat <<EOF
## Parent

Sub-issue of #$EC. Saga #$SAGA.

## Acceptance

- [ ] New \`design/share.html\` sealed share object
- [ ] when/where shown as none (omitted from fact strip)
- [ ] \`article\` block: title, source, blurb, open link
- [ ] Acts: Ack / Pin only
- [ ] Linked from README demo map + system kit
- [ ] Proves Pidge ≠ calendar-only product
EOF
)")
link_sub "$EC" "$(num "$T")"

T=$(gh issue create --repo "$REPO" --title "Compose enrich preview: skeletons → rich stack + one failed block" --label "P1,design,mail" --body "$(cat <<EOF"
## Parent

Sub-issue of #$EC. Saga #$SAGA.

## Acceptance

- [ ] \`design/compose.html\` after enrich shows rich preview (not only slot rows)
- [ ] Skeleton → filled motion for blocks (reuse \`is-skel\` language)
- [ ] One optional block in **degraded** state (e.g. menu failed) while slots still sealable
- [ ] Side panel Enriching log lists resolve/fetch steps matching blocks
- [ ] Step chips Draft → Enrich → Seal
EOF
)")
link_sub "$EC" "$(num "$T")"

###############################################################################
# Tasks — Epic D
###############################################################################
T=$(gh issue create --repo "$REPO" --title "System kit: enrichment widgets + fact strip specimens" --label "P1,design" --body "$(cat <<EOF"
## Parent

Sub-issue of #$ED. Saga #$SAGA.

## Acceptance

- [ ] \`design/system.html\` live specimens: fact-strip, place-hero, map-block, menu-block, reviews-block, article-block
- [ ] CSS modules in \`design/styles.css\` / \`flow.css\`: \`.enrich-stack\`, \`.place-hero\`, \`.map-block\`, \`.menu-block\`, \`.reviews-block\`, \`.article-block\`, \`.fact-strip\`
- [ ] Slim topbar specimen already present — keep ≤4 primary items
EOF
)")
link_sub "$ED" "$(num "$T")"

T=$(gh issue create --repo "$REPO" --title "System kit: degraded block + no-image fallback" --label "P1,design" --body "$(cat <<EOF"
## Parent

Sub-issue of #$ED. Saga #$SAGA.

## Acceptance

- [ ] Degraded/missing block specimen (failed fetch / skipped) with calm copy — not a red page
- [ ] No-image place fallback: monogram / faux-map plane from venue name (never broken-image icon)
- [ ] Documented in README under craft anticipations
EOF
)")
link_sub "$ED" "$(num "$T")"

###############################################################################
# Tasks — Epic E (production — detailed for later)
###############################################################################
T=$(gh issue create --repo "$REPO" --title "Schema: optional kind on pidges + extras.blocks shape" --label "P2,mail,mcp" --body "$(cat <<EOF"
## Parent

Sub-issue of #$EE. Saga #$SAGA.

## Technical detail

- Add nullable/text \`kind\` on \`pidges\` (\`invite|share|ask|fyi|remind|note\`) with default inferred or \`invite\` for dogfood compat
- MemoryStore + Postgres migration
- \`enrich_pidge\` accepts \`extras.blocks\` array; validate lightly (list of dicts with \`type\` string); unknown types preserved
- \`content_hash\` continues to hash summary+slots (blocks included via slots/extras)
- Tests: seal still blocked on incomplete who/when/where; blocks absent OK; blocks present round-trip \`get_pidge\`

## Out of scope

Image hosting; scraping service.
EOF
)")
link_sub "$EE" "$(num "$T")"

T=$(gh issue create --repo "$REPO" --title "Templates: render enrich-stack from blocks in thread/compose" --label "P2,design,mail" --body "$(cat <<EOF"
## Parent

Sub-issue of #$EE. Saga #$SAGA.

## Technical detail

- Port CSS from \`design/\` enrichment widgets into \`src/pidge/static/styles.css\` + \`flow.css\`
- \`thread.html\`: fact strip + block stack; kind badge; kind-aware acts
- \`compose.html\` / live SSE partials: preview stack + degraded state
- No ChirpUI
- Mirror author vs recipient CTA split already in templates

## Depends on

Schema kind + blocks task; validated mocks.
EOF
)")
link_sub "$EE" "$(num "$T")"

T=$(gh issue create --repo "$REPO" --title "Production IA: slim layout nav + Draft/Enrich/Seal copy" --label "P2,design,mail" --body "$(cat <<EOF"
## Parent

Sub-issue of #$EE. Saga #$SAGA.

## Technical detail

- \`layout.html\`: Desk · Mail · People · Account (Agents under settings); demote Sent/Calendar/Wall/Directory/Contacts from top-level
- Mail In|Out via segment or query on inbox/sent
- Replace user-visible Fly/Flight strings with Enrich/Enriching across templates
- Keep routes working; this is chrome IA, not deleting features

## Acceptance

- [ ] ≤4 primary nav items when logged in
- [ ] No Fly-before-Seal copy in UI
EOF
)")
link_sub "$EE" "$(num "$T")"

echo ""
echo "Done. Saga #$SAGA"
gh issue view "$SAGA" --repo "$REPO" --json url,title,number --jq '"\(.number) \(.title) \(.url)"'
