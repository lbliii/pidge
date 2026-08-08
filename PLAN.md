# Pidge — product plan

Status: living draft. Design mocks validate direction; app scaffold comes next.

## One-liner

Pidge is your **agent’s secretary**: structured mail, calendar, and a personal wall of notes — authored by agents over MCP, reviewed and sealed by humans in a hypermedia UI.

## Why it exists

Inbox apps assume *you* type. Agent stacks assume chat or JSON APIs. Pidge assumes:

- the interesting payload is a **structured object** (place, time, menu, RSVP, map),
- an **agent** is better at assembling that object than a blank textarea,
- a **human** should still notarize (seal) and act (RSVP) without becoming a clerk.

Not Tumblr. Not a public feed. A desk.

## Surfaces (v1 scope)

| Surface | In | Out (for now) |
|---|---|---|
| **Mail** | Compose-via-agent, inbox, thread, seal, verify, RSVP | SMTP gateway, mega-CC, freeform reply boxes |
| **Calendar** | Holds / events derived from sealed Pidges | Full Google-Calendar clone |
| **Wall of notes** | Personal loft of pinned sealed objects | Social timeline, likes, reblogs |

Ship order: **mail → calendar hooks → notes wall**.

## Creative constraints (non-negotiable)

1. **No typing to author** — the product UI has no free-compose textarea as the write path. Agents create and enrich drafts via MCP. (Buttons and typed acts for humans are fine.)
2. **Seal is irreversible** — sealed content is frozen. Amendments are new flights or signed supersessions, not silent edits.
3. **Acts, not prose replies** — recipient vocabulary is structured (accept / decline / propose). Their agent may attach garnish; the primary response is an act.
4. **Structured gate** — a Pidge does not seal without required slots filled or explicitly marked none (who, when, where as the starter set).
5. **One intent → one draft flight** — enrichment is a flight (resolve contacts, parse time, fetch place/menu); humans seal when ready.

Optional later: hard cap on human-facing summary length (Twitter energy); direct-address-only v1 (no CC sprawl).

## Auth model

**Do not share the browser session cookie with the agent.**

| Actor | Credential | Capabilities |
|---|---|---|
| Human (browser) | Session cookie | Read inbox/calendar/wall; approve; **seal**; RSVP / acts |
| Agent (MCP client) | Delegated bearer / API token with **scopes** | Draft, enrich, propose — e.g. `pidge:compose`, `pidge:calendar.write` |

Flow sketch:

1. Human logs into Pidge (session).
2. Human connects an agent → mints a scoped, expiring, revocable token (device/link flow or “issue agent key”).
3. MCP tools call with `Authorization: Bearer …`.
4. **Hard mode (preferred):** agent may only create/update **drafts**; **seal** requires the human session (notary).

Audit must distinguish “human sealed” vs “agent drafted.” Chirp’s human permissions vs machine **scopes** axis is the intended fit.

## Object model (sketch)

- **Pidge** — the sealed (or draft) message object: slots + attachments + seal metadata.
- **Flight** — agent enrichment run (who / when / where / extras).
- **Act** — typed recipient response (RSVP, propose, decline).
- **Hold / Event** — calendar projection of a sealed Pidge.
- **Note pin** — wall entry pointing at a sealed object (personal loft).

Exact schema TBD in implementation; mocks use the “Tonight at Nowadays” invite as the dogfood story.

## MCP surface (sketch)

Write path (agent):

- `draft_pidge` / `enrich_pidge` / `attach_*`
- calendar: `propose_hold`, `update_hold` (draft)
- notes: `pin_note` (maybe seal-gated)

Read path may be MCP *and* HTML; humans primarily use the hypermedia client.

## UI principles

- Desk, not dashboard: mail / calendar / wall as secretary surfaces.
- Earth palette (oat, leather, bay, stable) — pigeon-adjacent without literal grey marble.
- Brand mark: letter **P** in the seal for now; animal mark deferred.
- Compose mock should evolve from “textarea dictate” → “waiting on agent / live flight rail / seal.”

## Relationship to sibling products

| Product | Role |
|---|---|
| **Chirp** | Runtime: HTML, fragments, SSE, contracts, auth scopes |
| **Orrery** | Skills / gaze / resolve — callable capabilities Pidge agents may use |
| **Pidge** | The secretary application — mail + calendar + loft |

## Near-term work

- [x] Design mocks (landing, compose flight, inbox, sent, recipient RSVP, thread)
- [x] Product plan (this doc) + standalone repo
- [ ] Kill free-type compose in mocks; show agent-inbound draft + flight + seal
- [ ] Chirp app scaffold (pages, session + CSRF stack, scope registry)
- [ ] MCP tool stubs + delegated token mint/revoke
- [ ] Calendar projection from sealed invites
- [ ] Notes wall (personal loft) v0

## Open questions

- Envelope / attestation: reuse Orrery/Chirp skill Envelope for sealed Pidges, or a Pidge-specific seal?
- Multi-agent: one primary secretary vs multiple agents with overlapping scopes?
- Cross-user delivery: shared Pidge network vs email bridge for cold recipients?
- Notes wall sharing: private only at v1, or room-scoped later?

## Non-goals (explicit)

- Competing with Gmail/Outlook as a general mail client
- Becoming a Tumblr/Twitter-style public feed
- Letting the agent inherit the human session cookie
