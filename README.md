# Pidge

**Your agent’s secretary — structured mail, calendar, and a wall of notes.**

You don’t type into Pidge. Your agent writes via MCP. You review, seal, and act.
Mail that means something: hypermedia objects, not SMTP cosplay.

## Thesis

Pidge is the desk, not the typewriter.

| Surface | Job |
|---|---|
| **Mail** | Directed, sealed, actionable messages (invite, RSVP, enrichments) |
| **Calendar** | Holds and commitments the secretary keeps for you |
| **Wall of notes** | Your loft / corkboard — pinned sealed objects, not a social feed |

Built to sit beside [Orrery](https://github.com/lbliii/orrery) (skills you point at) and on [Chirp](https://github.com/lbliii/chirp) (HTML-first hypermedia).

## Creative constraints

Like Twitter’s character limit — scarcity that makes the product legible:

1. **No UI authoring** — humans don’t free-type compose. Agents draft over MCP.
2. **Seal freezes** — after seal, content is immutable; revoke or supersede instead of quiet edits.
3. **Acts, not replies** — recipients hit typed actions (RSVP, propose time, decline); prose is optional garnish from *their* agent.
4. **Structured or it doesn’t fly** — who / when / where (or explicit none) before seal.
5. **Two identities** — your browser session ≠ your agent’s credential (scoped token).

Full product plan: [`PLAN.md`](./PLAN.md).

## Status

Early product repo. Design direction is in [`design/`](./design/) (HTML/CSS mocks). Implementation is next.

**Palette:** oat / leather / bay / stable — Barlow Semi Condensed + Source Sans 3.

## Preview the mocks

```bash
cd design
python -m http.server 8766
# open http://localhost:8766
```

## Screens

| File | Screen |
|---|---|
| [design/index.html](./design/index.html) | Landing |
| [design/compose.html](./design/compose.html) | Agent flight → enrich → seal |
| [design/inbox.html](./design/inbox.html) | Inbox |
| [design/sent.html](./design/sent.html) | Delivery confirmation |
| [design/lucy.html](./design/lucy.html) | Recipient verify + RSVP |
| [design/thread.html](./design/thread.html) | Settled thread |
| [design/fonts.html](./design/fonts.html) | Type pairing explorer |

## License

TBD.
