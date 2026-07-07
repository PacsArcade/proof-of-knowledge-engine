# ARCHITECTURE — Proof of Knowledge Engine (P.O.K.E.)

A community-owned, federated, gamified education node. A local LLM swarm generates curriculum
grounded in a Wikipedia-scale corpus, a human-in-the-loop guardrail guards against hallucination,
and a Bitcoin layer handles discovery and (regtest-first) rewards. Fully open-source,
self-hostable, offline-capable. No proprietary APIs.

**POKE is an engine; games are extensions.** The services below are the engine (one shared brain);
the MUD and the Luanti voxel world are two *extensions* that render it — and any game can be the
next one. The MUD and Luanti already drive the same `state-sync` against the same DB-2, so they are
literally one world in two windows. How to plug a game in: **`EXTENSIONS.md`**.

See `CONVENTIONS.md` for the canonical service/port/tier table — this doc explains the *why*.

## System at a glance

```
                         ┌───────────────────────────── ONE VERSE (one operator's node) ─────────────────────────────┐
   players               │                                                                                            │
  ┌───────┐  telnet/ssh  │   ┌─────────┐        ┌──────────────┐        ┌─────────────────────────────────────────┐  │
  │  MUD  │◄────────────►│   │   MUD   │◄──────►│              │◄──────►│  DB-2  postgres-gamestate (Blackboard)  │  │
  └───────┘              │   │ (4000)  │        │  state-sync  │        │  users · rooms · competency · seed_frags │  │
  ┌───────┐   voxel/udp  │   ┌─────────┐        │   (8082)     │        └───────────────────┬─────────────────────┘  │
  │Luanti │◄────────────►│   │ Luanti  │◄──────►│   HOT tier   │                            │                        │
  └───────┘              │   │(30000)  │        └──────────────┘                            │ read/write             │
                         │                                          ┌─────────────────────────────────────────────┐  │
                         │                      ┌──────────────┐    │           orchestrator (swarm, 8080)         │  │
                         │                      │  guardrail   │◄──►│  Oracle · Architect · Custodian · Archivist  │  │
                         │                      │   (8081)     │    │                  · Warden                    │  │
                         │                      └──────┬───────┘    └───────────────┬──────────────────────────────┘  │
                         │                             │ KNN                        │ generate (stream)               │
                         │              ┌──────────────▼────────┐        ┌──────────▼──────────┐                      │
                         │              │ DB-1 postgres-source  │        │  inference (WARM)   │                      │
                         │              │  pgvector · read-only │        │  Ollama | vLLM      │                      │
                         │              └──────────┬────────────┘        └─────────────────────┘                      │
                         │                         │ ingest                                                           │
                         │   ┌─────────────────────▼─────────┐   ┌───────────┐   ┌───────────────┐  ┌──────────────┐ │
                         │   │  corpus (ingest + torrent)    │   │  matrix   │   │ matrix-bridge │  │   bitcoin    │ │
                         │   │  COLD · 8083 · bt 6881        │   │ Dendrite  │◄─►│    (8084)     │  │  (regtest)   │ │
                         │   └───────────────┬───────────────┘   │8008/8448  │   └───────────────┘  │ bitcoin-bridge│ │
                         │                   │                   └─────┬─────┘                       │   (8085)     │ │
                         └───────────────────┼─────────────────────────┼──────────────────────────────────┼─────────┘
                                    corpus mesh (BitTorrent)   Matrix federation              OP_RETURN discovery
                                    ── COLD tier: other Verses ── async, eventually-consistent, never on the hot path ──
```

## The four subsystems

### 1. Communication foundation — Matrix (COLD)
Every operator runs their own Dendrite homeserver beside the game node. In-game chat is authored
locally and mirrored into Matrix rooms by `matrix-bridge`. Verses federate natively, so a player
on one node can reach a player on another. The **encrypted admin room** is where the Warden posts
guardrail quarantines for the operator to approve. Federation is best-effort and never blocks play.

### 2. Dual-interface game engine (HOT)
Two synchronized front-ends over **one** state engine: the **MUD** (ANSI text terminal) and the
**Voxel Verse** (Luanti/Minetest). Both mutate the same DB-2 game state through `state-sync` — a
lever in Luanti and a typed command in the MUD converge on the identical write. The node is
authoritative; clients are thin.

### 3. AI orchestration & hallucination guardrails (WARM)
A **swarm** (openclaw-managed) over a persistent **Blackboard** (DB-2), not context windows alone:
- **Oracle** runs Socratic interviews (brain = the `pacbot` skill) and writes `competency_node`s.
- **Architect** watches the Blackboard and generates Training Dungeon rooms targeting each player's
  knowledge gaps.
- **Custodian** manages seed-loot via SSS (regtest-first).
- **Archivist** owns the corpus/pgvector/torrent.
- **Warden** runs the guardrail loop.

**Dual-Postgres validation:** DB-1 (*The Source*, read-only, vectorized corpus) vs DB-2 (*The Game
State*). Any generated content is embedded and checked against DB-1; below-threshold content is
**quarantined** to the operator's Matrix room. Humans are the final guardrail. `honcho` tracks
per-user learning style and progress across sessions.

### 4. Bitcoin federation & incentives (COLD)
A locally-synced node (regtest by default). **Discovery** is decentralized: operators announce
their Verse (pubkey + Matrix address) via `OP_RETURN`; nodes scan the ledger to build the realm
directory — no central server list. **Seed-phrase rewards** distribute SSS fragments as high-tier
loot behind knowledge checks. **Tipping** (Lightning) lets players reward operators for quality
curriculum. All value handling obeys `docs/SECURITY.md`.

## Cross-cutting: the three tiers
HOT (local, authoritative, <50 ms) / WARM (local GPU, streamed) / COLD (federated, async). The
mesh is never on a path a player waits on. Full rationale in `docs/LATENCY.md`.

## Repo map
- `.claude/agents/` — build sub-agents (one per subsystem).
- `.claude/skills/` — node-wizard, issue-node-cert, corpus-ingest, hallucination-guardrail,
  seed-loot-forge, and the bundled pacbot educator.
- `infra/` — compose.yaml (Podman) + quadlet units, Postgres schemas, Dendrite, inference, bitcoin, luanti configs.
- `services/` — orchestrator (swarm + personas), state-sync, guardrail, corpus, mud, matrix-bridge,
  bitcoin-bridge.
- `luanti/mods/pacsarcade/` — the Voxel Verse mod.
- `connectors/` — supplemental knowledge sources feeding DB-1.
- `scripts/` — node-doctor, bootstrap, issue-cert.
- `docs/` — this file, LATENCY, SECURITY, CONVENTIONS, ONBOARDING-WIZARD.
