# Pidge — design mocks

HTML/CSS prototypes for the secretary desk. Not the production app.

## Demo flow

1. [compose.html](./compose.html) — agent flight → enrich → seal  
2. [sent.html](./sent.html) — delivery confirmation  
3. [lucy.html](./lucy.html) — recipient verifies + RSVP  
4. [thread.html](./thread.html) — settled thread  

Also: [index.html](./index.html) · [inbox.html](./inbox.html) · [fonts.html](./fonts.html)

```bash
python -m http.server 8766
# open http://localhost:8766
```

**Vibe:** oat / leather / bay · Barlow Semi Condensed + Source Sans 3.

**Note:** Compose still shows a dictate textarea for the story beat. Product constraint is **no UI authoring** — next mock pass should make this agent-inbound only (see repo [`PLAN.md`](../PLAN.md)).
