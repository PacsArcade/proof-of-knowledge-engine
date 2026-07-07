# pacBOT roadmap

v0.1 (current) ships the educator: Socratic method, whitepaper anchor,
fact-check, course builder, agent mode, arcade voice. The next versions make
pacBOT configurable, verifiable, and networked — the Curator, not just the
attendant.

## v0.2 — Configurable personality

A `pacbot.config.json` beside `SKILL.md` (see
[references/configuration.md](references/configuration.md) for the schema):

- **Voice presets**: `arcade` (default), `classic` (plain, warm, no game
  language), `scholar` (citation-forward). Communities forking pacBOT keep
  the pedagogy and swap the skin.
- **Style matching**: pacBOT reads the learner's register — vocabulary,
  pacing, formality, emoji use — and meets them there. A skater gets the
  half-pipe metaphor; an accountant gets the ledger. The Socratic method and
  the facts never bend; only the delivery does.
- **Lexicon overrides**: community words (fren, GG's) are config, not
  hardcode.

## v0.3 — Configurable knowledge sources

The whitepaper stays the anchor; everything else becomes a configured,
trust-tiered source list:

- **Tier 0 — canon**: the bitcoin whitepaper, BIPs, NIPs (bundled or local
  paths). Claims here are stated as fact.
- **Tier 1 — curated**: community-approved corpora ("My First Bitcoin",
  local class materials, a self-hosted wiki). Cited when used.
- **Tier 2 — live**: URLs and APIs (mempool.space for network state). Always
  labeled with fetch time; numbers decay, and pacBOT says so.
- Anything not in the source list gets the honest "I'd verify this before
  teaching it" treatment — pacBOT never launders an unsourced claim.

## v0.4 — Node sync (the fact-check network)

pacBOT instances verify each other, the bitcoin way — don't trust, verify.
**Educators run the nodes** — the game world pacBOT lives in syncs against
educator-run infrastructure, so the people teaching are the people hosting.

Two transports, two jobs:

- **Nostr** for public, signed fact attestations (claim, source tier,
  verdict) — published to configured relays (the arcade will run its own).
- **[Matrix](https://github.com/matrix-org)** for the live layer: federated,
  self-hostable homeservers that educators already can run. Game-state sync,
  classroom rooms, and node-to-node coordination ride Matrix federation;
  pacBOT also *teaches* Matrix (homeservers, federation, E2EE) as part of
  its sovereignty curriculum — same lesson as bitcoin and nostr: run your
  own infrastructure, verify instead of trust.
- Nodes cross-check contested claims: a fact taught as canon must trace to
  Tier 0/1 sources; disagreements surface to operators instead of silently
  propagating.
- Security-grade claims (anything touching key handling or spend safety)
  require **unanimous** attestation across a node's peer set before pacBOT
  teaches them as settled.
- The peer list is config: a lone pacBOT works fine; a network of arcades
  becomes an immune system for bad bitcoin education.

## v0.5 — The Curator (game-side integration)

A parallel agent track builds the arcade's games. pacBOT plugs in as the
in-world attendant — Ready Player One's Curator energy. The game world
syncs to educator-run nodes (see v0.4's Matrix layer), so every arcade
location can host its own shard of the world:

- Hooks for game clients to ask questions mid-play ("ASK THE ATTENDANT").
- Class attendance and cert lifecycle awareness (QUEUED → ✓ ETCHED), so the
  attendant knows what a fren has earned and teaches at their level.
- Archive stewardship: arcade lore, bitcoin history, and the community's own
  story, kept accurate by the same source-tier rules.

## Non-goals

- pacBOT never gives financial advice — education, never advice.
- pacBOT never handles keys or sats. It teaches; wallets do wallet things.
- No engagement tricks: no streaks, no FOMO, no dark patterns. Consequences,
  not prohibitions.
