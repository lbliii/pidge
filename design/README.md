# Pidge — design mocks

HTML/CSS prototypes for the secretary desk. Not the production app.

## Mental model

Pidge is a **private projection room for consequential objects** — not an
inbox transcript, not a calendar app with mail bolted on. Agents write via
MCP; humans **review, seal, and act**. One deployment = one **loft**.

### Naming rule (Draft → Enrich → Seal)

Compose steps are **Draft → Enrich → Seal**. Never “Fly before Seal.”

- **Draft** — agent inbound (`draft_pidge`)
- **Enrich** — agent fills slots + optional blocks (`enrich_pidge`)
- **Seal** — human commits; delivery happens after seal

Thread lifecycle chips: **Drafted → Enriched → Sealed → Delivered → Acted**.

Side panel / badge copy uses **Enriching** (CSS may still use `.flight-rail`).

### Core journeys

1. **Owner seal** — mint agent → Draft → Enrich → Seal
2. **Recipient act** — open packet → kind-scoped act → hold / pin
3. **Desk blotter** — arrive → **Needs you** → one primary action

Primary chrome: **Desk · Mail · People · Account** (Agents · Stamps under Account).
Compose is a state, not a permanent top-level tab. Calendar and wall are
quiet peeks on the desk.

## Demo flow (object mail)

1. [compose.html](./compose.html) — Draft → Enrich → Seal (rich preview + one degraded block)
2. [sent.html](./sent.html) — delivery confirmation
3. [lucy.html](./lucy.html) — recipient invite · RSVP acts
4. [thread.html](./thread.html) — settled author thread
5. [share.html](./share.html) — non-event article packet · Ack / Pin

## Journey + system mocks

- [system.html](./system.html) — design language + enrichment kit + **tokens**
- [desk.html](./desk.html) — blotter / Needs you home
- [agents.html](./agents.html) — mint ritual + secret drawer
- [login.html](./login.html) — enter the loft
- [index.html](./index.html) — landing
- [inbox.html](./inbox.html) · [fonts.html](./fonts.html)
- [stamps.html](./stamps.html) — stamp album + cancellation specimen
- [stamps.md](./stamps.md) — letter stamp rules (mint, types, anti-HUD)

```bash
python -m http.server 8766
# open http://localhost:8766
```

**Vibe:** oat / leather / bay · Barlow Semi Condensed + Source Sans 3.

**Tokens:** brand → semantic (`--action`, `--success`, `--danger`, `--warn`,
`--muted`) → type / space / radius / shadow / motion scales in `:root`.
Primitives: `.field`, `.alert`, `.empty-state`, `.person-row`, `.object-row`,
`.preset-card`, `.btn-danger`. See [system.html](./system.html).

**Compose constraint:** No free-type authoring box. Compose is **agent-inbound
only**. Humans seal; agents draft and enrich via MCP (`draft_pidge`,
`enrich_pidge`).

---

## Letter stamps (delight layer)

Collectible postage earned on **Seal** — not XP. Full rules:
[stamps.md](./stamps.md). Album mock: [stamps.html](./stamps.html) (#77). Affixed packet face still TBD (#78).

Summary:

- **Mint** only on `draft → sealed` (session, challenge, or Autopilot)
- **Cancellation** = date · loft · hash · **Stamp** = commemorative face
- Types: definitive (by kind) · pictorial (first place/article) · person
  (first recipient) · special (rare loft moments)
- Anti-HUD: no streaks, no gating, no stamp showers

---

## Kind taxonomy (send)

| Kind | Slots | Typical blocks | Acts (recipient) | Mock now? |
|------|-------|----------------|------------------|-----------|
| **invite** | who, when, where | place, map, menu, reviews | Accept / Decline / Maybe | yes · thread, lucy, compose |
| **share** | who; when/where often `none` | article / link | Ack / Pin | yes · share.html |
| **ask** | who (+ optional when/where) | link / note | Answer acts (later) | document only |
| **fyi** | who | article / link | Ack | document only |
| **remind** | who, when | — | Ack / Snooze (later) | document only |
| **note** | who optional | — | Pin / Filed | document only |

Invite is **one kind**, not the product identity.

## Receive stances

| Stance | Meaning |
|--------|---------|
| **Needs act** | Kind-scoped decision required (RSVP, answer) |
| **Needs eyes** | Read/ack attention (share, fyi) |
| **Result** | Settled outcome visible on author thread |
| **Filed** | Done / pinned / archived residue |

## Not a kind

These are **not** message kinds:

- Lifecycle state (drafted / enriched / sealed / delivered / acted)
- Enriching progress
- Hold / pin residue
- Loft vs external addressing

## Design rules

- Fact strip shows only slots that are `ready` — hide `none`
- Acts are kind-scoped (no RSVP on share)
- Badge = **kind + stance** (e.g. `Invite · needs act`, `Share · sealed`, `Result · accepted`)
- Author CTA ≠ recipient CTA on the same object
- Blocks never gate seal; who/when/where each `ready` or `none` do

## Craft anticipations

- **Degraded block** — calm dashed panel when a fetch fails/skips; seal still OK
- **No-image place** — monogram / faux plane from venue name; never a broken-image icon

---

## `extras.blocks[]` contract

`extras` stays a slot-like object with per-slot `status` plus optional
`blocks: []`. Agent webfetch happens **outside** Pidge; MCP `enrich_pidge`
carries structured extras only.

### Block types (this wave)

`place` · `map` · `menu` · `reviews` · `article` / `link`

Unknown `type` → generic link/note fallback.

### Field notes

- `image` optional on place/article
- `fetched_at` / `source_url` for freshness
- map may include optional `lat` / `lng`
- Blocks do **not** gate seal

### Example — Nowadays invite

```json
{
  "who": { "status": "ready", "value": "Lucy" },
  "when": { "status": "ready", "value": "Tonight · 7:00 PM", "tz": "America/New_York" },
  "where": { "status": "ready", "value": "Nowadays", "address": "56 Bogart St, Brooklyn" },
  "blocks": [
    {
      "type": "place",
      "title": "Nowadays",
      "blurb": "Bushwick · kitchen + natural wine",
      "image": null,
      "fetched_at": "2026-08-08T22:00:00Z",
      "source_url": "https://example.com/nowadays"
    },
    {
      "type": "map",
      "address": "56 Bogart St, Brooklyn",
      "lat": 40.706,
      "lng": -73.923
    },
    {
      "type": "menu",
      "title": "Kitchen + natural wine",
      "items": ["Small plates · shared", "Natural wine list"],
      "fetched_at": "2026-08-08T22:00:00Z"
    },
    {
      "type": "reviews",
      "rating": 4.6,
      "blurb": "Best patio in Bushwick",
      "source_url": "https://example.com/reviews"
    }
  ]
}
```

### Example — federation article share

```json
{
  "who": { "status": "ready", "value": "Lucy" },
  "when": { "status": "none" },
  "where": { "status": "none" },
  "blocks": [
    {
      "type": "article",
      "title": "DNS-like destinations for private lofts",
      "source": "federation-notes",
      "blurb": "How peer lofts register reachable handles without a public social graph.",
      "source_url": "https://example.com/federation",
      "fetched_at": "2026-08-08T18:00:00Z"
    }
  ]
}
```
