# Pidge experience system

Compositional contract for how surfaces fit together. Not a glossary of
isolated terms — every layer has a job, a layout family, and components it
may reuse.

Mental model (unchanged): a **private projection room for consequential
objects**. Agents Draft / Enrich; humans Seal / Act. One deployment = one
**loft**.

---

## Layers

```text
Shell: Desk · Mail · People · Account
  ├── Desk          attention blotter (Needs you + quiet peeks)
  ├── Mail          In · Out facets
  ├── People        In the loft · Beyond the loft
  ├── Workflow      Draft → Enrich → Seal (compose state, not a tab)
  ├── Object        sealed packet canvas (/p/{id})
  ├── Residue       Calendar · Wall (Account; desk peeks)
  └── Rituals       Agents · Stamps (Account)
```

| Layer | Job | Route family | Layout family | Canonical components | States |
|-------|-----|--------------|---------------|----------------------|--------|
| **Shell** | Orient; ≤4 primary destinations | all authenticated | `.topbar` · `.nav` · `.nav-account` | brand, primary links, Account drawer | viewer / guest |
| **Desk** | Route attention — one stack for decisions | `/` | blotter · Needs you + quiet peeks | `.needs-row`, `.quiet-strip`, hold/pin peeks | empty / needs seal / enriching / needs act |
| **Mail** | Browse sealed traffic | `/inbox` · `/sent` | page-head + `.segmented` + list | `.segmented`, `.msg` / `.object-row`, `.empty-state` | In · Out; empty loft |
| **People** | Address graph for agents + humans | `/people` · `/people/address-book` | page-head + `.segmented` + folio | `.segmented`, `.person-row`, introductions tray, add-address panel | loft empty; pending intro; address book empty |
| **Workflow** | Build a packet until seal | `/compose`, `/compose/{id}` | compose-panel + enriching rail | slots, `.enrich-stack`, `.flight-rail`, seal CTA | draft / enriching / ready / blocked |
| **Object** | Projection of one sealed Pidge | `/p/{id}` | thread-layout + bubble | recipient-bar, kind acts, enrich stack, (later) stamp + cancellation | sealed / revoked / superseded / acted |
| **Residue** | Quiet aftermath of seals | `/calendar` · `/wall` | object lists | `.object-row`, pin / hold cards | empty residue |
| **Rituals** | Trust + delight under Account | `/settings/agents` · stamps (later) | preset / album | `.preset-card`, secret drawer, stamp grid | mint once / revoked |

### Cross-links (intentional)

- Desk → Compose / Thread / Mail peek / Calendar peek / Wall peek
- Mail → Thread (object canvas)
- People → Compose addressing (via agents); introductions stay on People
- Object → Calendar hold / Wall pin (acts leave residue)
- Account → Agents (MCP), Stamps (album), Calendar, Wall

---

## Facet pattern

Mail and People share one control: **`.segmented`** with real links and
`aria-current="page"`. Not JS tabs. Each facet owns its collection layout
under a shared page-head.

| Surface | Facets | Collection beat |
|---------|--------|-----------------|
| Mail | In · Out | Message rows (stance badges next wave) |
| People | In the loft · Beyond the loft | Person folio + introductions / add-address |

---

## People subsystem (this foundation)

**Metaphor:** loft directory + address book — not a CRM, not a glossary.

- **In the loft** — same-deployment members; addressable without a friend
  edge; optional connection request as social “introduction.”
- **Beyond the loft** — external handles agents may address only after the
  human adds them.
- **Introductions tray** — pending connection requests with **names**, never
  raw user IDs.
- **Add an address** — bounded form panel on the Beyond facet only.

Canonical routes: `/people`, `/people/address-book`. Legacy `/directory` and
`/contacts` redirect.

Mock: [people.html](./people.html).

---

## Component contracts (shared)

| Primitive | Owns | Must not |
|-----------|------|----------|
| `.segmented` | Facet switching | Page content |
| `.person-row` / `.object-row` / `.needs-row` | One decision / person / object | Dump raw IDs as primary label |
| `.empty-state` | First-run dignity | “0 items” / XP tone |
| `.field` / `.alert` | Forms + errors | Inline hex colors |
| `.enrich-stack` | Packet media blocks | Seal gating logic |
| `.btn` / `.btn-seal` / `.btn-ghost` / `.btn-danger` | Actions | Nested accidental CSS blocks |

CSS integrity: top-level rules for `.segmented`, `.empty-state`, `.person-row`
must stay un-nested (see `tests/test_design_system.py`).

---

## Next experience waves

1. ~~**Desk blotter** — replace pillars with Needs-you stack + quiet peeks~~ (#92)
2. **Out / delivery** — post-seal ceremony (design `sent.html`) vs list-only
3. **Mail stance badges** — `Invite · needs act` vocabulary
4. **Calendar / Wall** — residue page mocks aligned with desk peeks
5. **Agents ritual** — secret drawer “shown once”
6. **Stamp affix** — cancellation + face on sealed bubble (#78)

---

## Success check

Someone can open Mail and see a leather pill facet; open People and feel an
address book, not a database dump; and the design README points here when
someone asks “where does this surface live?”
