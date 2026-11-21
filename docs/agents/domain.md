# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

**Layout: single-context.** This repo uses one shared `GLOSSARY.md` at the root for every area (backend and frontend alike), and architecture decision records live in `docs/adr/`. There is no `GLOSSARY-MAP.md` and no per-context or per-package glossary.

## Before exploring, read these

- **`GLOSSARY.md`** at the repo root: the shared vocabulary for the whole repo.
- **`docs/adr/`**: read ADRs that touch the area you're about to work in.

If either doesn't exist, **proceed silently**. Don't flag its absence; don't suggest creating it upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

## File structure

Single-context repo (the layout used here):

```
/
├── GLOSSARY.md          ← created lazily, on the first real glossary entry
├── docs/
│   ├── adr/             ← created lazily, on the first accepted decision
│   │   ├── 0001-event-sourced-orders.md
│   │   └── 0002-postgres-for-write-model.md
│   └── agents/          ← this skill configuration
├── backend/
└── frontend/
```

Both `GLOSSARY.md` and `docs/adr/` start absent by design; they appear the first time a term or a decision is actually written down. Do not scaffold empty stubs of either.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `GLOSSARY.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders), but worth reopening because…_
