# Letter stamps — rules (v0)

Research for [#76](https://github.com/lbliii/pidge/issues/76). Parent epic
[#75](https://github.com/lbliii/pidge/issues/75). **Design contract only** —
no production ledger, no SVG art pipeline yet.

Stamps are mail culture (envelope face + album). They commemorate *sealing
consequential packets*, not drafting, enriching, or daily streaks.

---

## One-liner

On every successful **Seal**, the packet gets a **cancellation** (trust mark)
plus a **stamp face** (commemorative). The album collects faces you have
earned. Nothing else in the product is gated by stamps.

---

## Mint moment

| Event | Stamps? |
|-------|---------|
| `draft_pidge` | No |
| `enrich_pidge` | No |
| Human **Seal** (session UI) | **Yes** |
| Confirm challenge redeem → seal | **Yes** (same seal transition) |
| Autopilot seal (opt-in mint) | **Yes** — human authorized the path; ceremony is still seal |
| Recipient acts (RSVP / ack / pin) | No |
| Discard draft / revoke / supersede alone | No new mint |

**Rule:** mint exactly when a pidge transitions `draft → sealed` and receives
a `content_hash`. One seal → one stamp selection for that packet.

Agents never mint stamps. Enrichment blocks never mint stamps.

---

## Cancellation vs stamp

These are **two layers** on the sealed object face:

| Layer | What it is | What it shows |
|-------|------------|---------------|
| **Cancellation** | Trust / provenance mark | Date · loft name · short `content_hash` fragment |
| **Stamp** | Commemorative face | Definitive / pictorial / person / special art |

- Cancellation is **always** present on a sealed packet (like a postmark).
- Stamp is the **collectible face** affixed with the cancellation.
- Cancellation is not a collectible and does not appear in the album grid.
- Stamp art never encodes XP, level, or “seal count.”

Visual placement (for mocks #78): corner/edge of the bubble — postage
position — never over the place hero or primary CTA.

---

## Stamp types + earn conditions

| Type | Face idea | Earns when | Album |
|------|-----------|------------|-------|
| **Definitive** | Quiet kind mark (invite / share / fyi / ask / remind / note) | Every seal of that kind | Always available as packet face; album shows each kind once you have sealed it |
| **Pictorial** | Place or article source (e.g. Nowadays patio, federation article) | First seal whose enrichment includes a distinct `place` or `article`/`link` identity | **First time only** per loft+identity key |
| **Person** | Recipient silhouette / monogram | First sealed packet **to** that recipient (loft user or external contact) | **First time only** per recipient |
| **Special** | Rare loft moment | Explicit specials only (see below) | Once per special |

### Definitive (always the fallback face)

Every sealed packet shows **at least** the definitive for its `kind`. If no
pictorial / person / special wins the face slot, the definitive is what
affixes.

Definitives are not “rare.” They are postage by kind — adult, quiet, always
in circulation.

### Pictorial identity key

Derive from enrichment when present:

1. Prefer `blocks[]` entry with `type == "place"` → key `place:<normalized title>`
2. Else `type in (article, link)` → key `article:<source_url or title>`
3. Else ready `where` slot → key `place:<normalized where value>`
4. Else no pictorial candidate

Normalization: casefold, strip, collapse whitespace. Unknown / empty → skip.

### Person identity key

- Loft recipient → `loft_user:<id>`
- External contact → `contact:<id>` (or handle if id missing in mocks)
- Multiple recipients → one person stamp **per recipient** may enter the
  album; the **packet face** still shows a single stamp (priority below)

### Specials (v0 list — keep short)

| Special | Earns when |
|---------|------------|
| **First seal** | Author’s first-ever successful seal in this loft |
| **Nowadays** (dogfood) | First seal whose pictorial key is the Nowadays place |

No seasonal calendar spam. New specials are a deliberate design decision,
not an automated holiday drop.

---

## Which face affixes on the packet?

When a seal mints, compute candidates, then pick **one face** for the object:

1. **Special** (if newly earned on this seal), else
2. **Pictorial** (if newly earned on this seal), else
3. **Person** (if newly earned for any recipient on this seal), else
4. **Definitive** for `message.kind`

Album updates:

- Always ensure the kind’s **definitive** is in the author’s album after seal
- Add pictorial / person / special **only on first earn**
- Re-sealing the same place or person later still gets a definitive (or
  another newly earned type) on the packet — album does not duplicate

Recipient view sees the **same affixed stamp + cancellation** as part of the
sealed object face. Recipients do **not** earn the author’s stamp into their
own album by opening or acting.

---

## Deduping (summary)

| Type | Packet face | Album row |
|------|-------------|-----------|
| Definitive | Every seal of that kind | One specimen per kind, after first seal of that kind |
| Pictorial | Priority when newly earned | One specimen per identity key |
| Person | Priority when newly earned | One specimen per recipient key |
| Special | Priority when newly earned | One specimen per special id |

---

## Anti-HUD constraints (hard rules)

**Never:**

- XP, levels, progress bars, “seal 5 more”
- Streaks framed as guilt or decay
- Animated stamp showers / confetti on Seal
- Feature gating (compose, enrich, seal, acts) behind stamp collection
- Leaderboards, trading, rarity marketplace
- Purple gamer gradients or achievement toast stacks

**Always:**

- Stamp reads as postage on an object, not a badge on chrome
- Album empty state is dignified (“No stamps yet — seal something
  consequential”) — never “0 points”
- Pet/pigeon (if any later) is **status only**; stamps remain the collectible

---

## Relationship to kinds + blocks

| Product concept | Stamp relationship |
|-----------------|--------------------|
| `kind` (`invite` / `share` / …) | Selects **definitive** face; never replaced by stance or lifecycle |
| `extras.blocks` place / article | May unlock **pictorial** (first time) |
| Ready `where` without place block | May still unlock pictorial via where value |
| Receive stance / acts | No mint; acts are not postage |
| Enriching / flight rail | No mint; unfinished drafts are not mail yet |

Invite is one kind — not the product identity. Share packets get share
definitives (and article pictorials), not invite art.

---

## Revoke, supersede, notes — decisions

| Question | v0 decision | Rationale |
|----------|-------------|-----------|
| Self-notes (`kind=note`, no external/loft recipient) | **No stamp mint** | Stamps commemorate *sending*; filing to yourself is residue, not postage |
| Note addressed to someone | Definitive `note` (+ person/pictorial rules) | Still a sealed packet to a person |
| Revoke after seal | **Keep** album earnings; packet face shows revoked overprint on cancellation; stamp face stays as historical mark | Collection is memory, not a score to claw back |
| Supersede | Prior sealed packet keeps its stamp; new draft mints only when **re-sealed**; pictorial/person already earned stay earned | Supersede is amend, not a farm loop |
| Discard draft | Nothing | Never sealed |
| Autopilot seal | Mints normally | Same `draft→sealed` transition |

---

## Album IA (for mocks)

- Route mock: `design/stamps.html` (Account menu · “Stamps”)
- Grid of collected specimens; empty loft state as above
- Cancellation specimen lives on the **system kit / packet**, not as an album
  tile
- Wall stays for pinned notes; album is adjacent in spirit, separate surface

---

## Open questions (do not block #77/#78)

1. **Multi-recipient person priority** — if two new people on one seal, which
   person face wins the packet? *Lean:* alphabetical by display name for
   mocks; album still gains both.
2. **External-only pictorial sources** — should `source_url` host be the key
   when titles collide? *Lean:* yes, prefer URL when present.
3. **Shared loft album vs per-user** — *Lean:* per-user (author’s seals);
   loft-wide album is a later federation story.
4. **Whether revoked packets hide the stamp on the face** — *Lean:* keep
   stamp, strike the cancellation (“revoked · hash”).

Resolve in mock review; update this doc when locked.

---

## Out of scope (still)

- Production `stamp_catalog` / `user_stamps` schema ([#79](https://github.com/lbliii/pidge/issues/79))
- SVG / generative art pipeline
- Trading, rarity economy, generative drops

---

## Success check

Someone opens the album once and remembers Pidge as “the mail app with the
little stamps” — without the desk feeling like a game.

Next: [#77](https://github.com/lbliii/pidge/issues/77) album mock ·
[#78](https://github.com/lbliii/pidge/issues/78) affix on sealed packets.
