# Pidge — design mocks

HTML/CSS prototypes for the secretary desk. Not the production app.

## Demo flow

1. [compose.html](./compose.html) — agent inbound → flight → seal  
2. [sent.html](./sent.html) — delivery confirmation  
3. [lucy.html](./lucy.html) — recipient verifies + RSVP  
4. [thread.html](./thread.html) — settled thread  

Also: [index.html](./index.html) · [inbox.html](./inbox.html) · [fonts.html](./fonts.html)

```bash
python -m http.server 8766
# open http://localhost:8766
```

**Vibe:** oat / leather / bay · Barlow Semi Condensed + Source Sans 3.

**Compose constraint:** No free-type authoring box. Compose is **agent-inbound
only** — the mock shows waiting / flight / seal. Humans seal; agents draft and
enrich via MCP (`draft_pidge`, `enrich_pidge`). See [saga #1](https://github.com/lbliii/pidge/issues/1)
and [epic #3](https://github.com/lbliii/pidge/issues/3).
