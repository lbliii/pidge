#!/usr/bin/env bash
# File letter-stamps exploration under saga #54.
set -euo pipefail
REPO=lbliii/pidge
PARENT_SAGA=54

issue_id() {
  gh api graphql -f query="query { repository(owner:\"lbliii\", name:\"pidge\") { issue(number:$1) { id } } }" --jq '.data.repository.issue.id'
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

EPIC_URL=$(gh issue create --repo "$REPO" --title "Epic: Letter stamps exploration — collectible delight on seal" --label "epic,P3,design,mail,enhancement" --body "$(cat <<EOF
## Intent

Explore a **kitschy, sticky, memorable** delight layer for Pidge that fits S-tier object mail: **letter stamps** earned when you seal — not XP, not a coding pet HUD.

Stamps are mail culture (envelope face + album). They reward *sending consequential packets*, not drafting or streaks.

## Parent

Sub-issue of [#$PARENT_SAGA](https://github.com/lbliii/pidge/issues/$PARENT_SAGA) (S-tier object mail). Complements enrichment canvas; does **not** block kinds/blocks work.

## North star tie-in

- Seal is ceremony → stamp is the quiet commemorative mark
- Object is the product → tiny stamp on the sealed bubble, not chrome gamification
- Invite/share kinds → definitive + pictorial stamp faces
- No confetti-as-brand; no Duolingo guilt

## Concept

| Moment | What appears |
| --- | --- |
| **Seal** | Cancellation (date · loft · short hash) + stamp affixed to packet |
| **Album** | Grid of collected stamps (Wall-adjacent or Account) |
| **List/object** | Optional tiny stamp mark on sealed rows/bubbles |

### Stamp types (v0 exploration)

- **Definitive** — by kind (invite / share / fyi / note)
- **Pictorial** — first seal involving a distinct place or article source
- **Person** — first sealed packet to a recipient
- **Special** — rare loft moments (first seal ever, dogfood Nowadays)

### Anti-goals

- No XP bars, levels, or “seal 5 more for a badge”
- No animated stamp shower
- No stamp gating of product features
- Pet/pigeon (if any later) is status only — **stamps are the collectible**

## Deliverables (mocks first)

1. Rules write-up in \`design/README.md\` (or short \`design/stamps.md\` linked from README)
2. \`design/stamps.html\` — album + specimen sheet
3. Show stamp + cancellation on rich sealed invite (thread/lucy) and share packet
4. Optional: one desk/album entry point in slim Account menu

## Not now

Production stamp ledger schema, rarity economy, trading, generative AI stamp art pipeline.

## Success

Someone opens the album once and remembers Pidge as “the mail app with the little stamps” — without the desk feeling like a game.
EOF
)")
EPIC=$(num "$EPIC_URL")
echo "EPIC=#$EPIC"
link_sub "$PARENT_SAGA" "$EPIC"

T=$(gh issue create --repo "$REPO" --title "Research: letter stamp rules — mint moments, types, anti-HUD constraints" --label "P3,design,documentation,enhancement" --body "$(cat <<EOF
## Parent

Sub-issue of #$EPIC. Saga #$PARENT_SAGA.

## Goal

Lock the **rules** before art so stamps stay delightful and adult.

## Write up (design/README or design/stamps.md)

- [ ] When a stamp mints (on human **Seal** only — not draft/enrich)
- [ ] Cancellation vs stamp (cancellation = trust/date/hash; stamp = commemorative face)
- [ ] Types: definitive / pictorial / person / special — earn conditions
- [ ] Deduping: first-time pictorial/person only; definitives always available as face?
- [ ] Anti-HUD: no XP, no streaks-as-guilt, no feature gating
- [ ] Relationship to kinds (invite/share/…) and enrichment place/article blocks
- [ ] Open questions: self-notes get stamps? revoke removes stamp? supersede?

## Out of scope

SVG art production; production persistence.
EOF
)")
link_sub "$EPIC" "$(num "$T")"
echo "rules $(num "$T")"

T=$(gh issue create --repo "$REPO" --title "Mock: design/stamps.html album + specimen sheet" --label "P3,design,enhancement" --body "$(cat <<EOF"
## Parent

Sub-issue of #$EPIC. Saga #$PARENT_SAGA.

## Acceptance

- [ ] New \`design/stamps.html\` with oat/leather album grid
- [ ] 6–10 specimen stamps (SVG or pure CSS): mix of definitive, pictorial (Nowadays), person (Lucy), special
- [ ] Perforation / gummed-rectangle visual language (kitschy but crafty)
- [ ] Cancellation mark specimen (date · loft · hash fragment)
- [ ] Linked from \`design/README.md\` and Account menu on mocks
- [ ] Empty album state for first-run loft (dignified, not “0 points”)

## Craft notes

Barlow SC for stamp titles; mono for denominations/cancellation; no purple gamer gradients.
EOF
)")
link_sub "$EPIC" "$(num "$T")"
echo "album $(num "$T")"

T=$(gh issue create --repo "$REPO" --title "Mock: affix stamp + cancellation on sealed invite and share packets" --label "P3,design,mail,enhancement" --body "$(cat <<EOF"
## Parent

Sub-issue of #$EPIC. Saga #$PARENT_SAGA.

## Acceptance

- [ ] Sealed invite canvas (\`thread.html\` / \`lucy.html\`) shows a small stamp + cancellation on the envelope/bubble
- [ ] Share packet (\`share.html\` when present, or stub) shows a different definitive/pictorial
- [ ] Stamp does not compete with place hero — corner/edge placement like real postage
- [ ] Recipient view can see the stamp (it’s part of the sealed object face)
- [ ] No confetti / stamp shower on seal CTA

## Depends on

Stamp specimen art from album mock (can use placeholders first).
EOF
)")
link_sub "$EPIC" "$(num "$T")"
echo "affix $(num "$T")"

T=$(gh issue create --repo "$REPO" --title "[Later] Stamp ledger schema — collected stamps per user/loft" --label "P3,design,mail,enhancement" --body "$(cat <<EOF"
## Parent

Sub-issue of #$EPIC. Saga #$PARENT_SAGA.

## Intent

Only after mocks feel right: persist stamp collection.

## Sketch (not build yet)

- \`stamp_catalog\` (id, slug, type, title, art_key, kind_hint)
- \`user_stamps\` (user_id, stamp_id, earned_at, pidge_id, meta jsonb)
- Mint hook in seal service path (session seal only)
- Album route \`/stamps\` or wall module

## Out of scope until mocks ship

This task stays **Later** — no schema PR until \`design/stamps.html\` is loved.
EOF
)")
link_sub "$EPIC" "$(num "$T")"
echo "schema-later $(num "$T")"

gh issue comment "$PARENT_SAGA" --repo "$REPO" --body "$(cat <<EOF
## Delight exploration filed

Letter stamps (kitschy collectible on seal): epic [#$EPIC](https://github.com/lbliii/pidge/issues/$EPIC).

Does not block kinds/enrichment canvas; P3 exploration under this saga.
EOF
)"

echo "Done epic #$EPIC"
gh issue view "$EPIC" --json url,title,number --jq '"#\(.number) \(.title)\n\(.url)"'
