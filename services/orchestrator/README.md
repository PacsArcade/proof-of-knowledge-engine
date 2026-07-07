# orchestrator — The Agent Swarm 💜

> Part of **Pac's Arcade — Proof of Knowledge Engine (P.O.K.E.)**.
> See the canonical contract in [`docs/CONVENTIONS.md`](../../docs/CONVENTIONS.md).

## Role

The `orchestrator` runs the **product runtime agent swarm** (openclaw-style). These are the
five personas that actually play the game with your frens — the Oracle who interviews, the
Architect who builds dungeons, the Custodian who guards the seed loot, the Archivist who
keeps the corpus, and the Warden who reviews. They are **not** the `.claude/agents/` build
agents; these ship inside the node and run at runtime.

Persona specs live in [`agents/`](./agents/). The swarm is declared in
[`swarm.yaml`](./swarm.yaml). All five agents coordinate through the **Blackboard** (DB-2),
never through context windows alone — see [`blackboard.py`](./blackboard.py).

## Tier

**WARM.** Agent reasoning happens on the local GPU through the pluggable inference endpoint
(`PA_INFERENCE_BASE_URL`). First token < 300 ms. The swarm must never put a COLD-tier call
(Matrix, torrent, on-chain) on a gameplay hot path — it hands those off to the COLD services.

## Port

**8080** (docker-compose service name: `orchestrator`).

## How it fits the whole

```
          reads/writes nodes
  swarm ───────────────────────►  DB-2  (postgres-gamestate, the Blackboard)
   │                                 ▲
   │ generation via                  │ HOT game-state writes
   ▼ PA_INFERENCE_BASE_URL           │
 inference (WARM)              state-sync (HOT)  ◄── Luanti / MUD front-ends
```

- **Oracle** reads a learner's `competency_node`s, runs a Socratic interview (delegating all
  bitcoin/nostr pedagogy to the bundled **pacbot** skill), and writes new `competency_node`s
  on demonstrated mastery.
- **Architect** watches the Blackboard for knowledge gaps and generates Training Dungeon rooms.
- **Custodian** manages seed-phrase loot via Shamir's Secret Sharing — **regtest-only** until
  security sign-off.
- **Archivist** owns corpus ingest, pgvector, and the torrent mesh (delegates to `corpus`).
- **Warden** runs the guardrail loop and routes quarantines to the operator's Matrix admin room.

`honcho` tracks per-user learning style/progress alongside the Blackboard.

## How to run it

```bash
# From repo root, with .env populated (see .env.example).
docker compose up orchestrator            # production-ish, alongside the swarm's deps

# Local dev (stub):
cd services/orchestrator
pip install -r requirements.txt           # TODO: add requirements.txt
python -m orchestrator                     # TODO: wire an entrypoint that loads swarm.yaml
```

Required env (from `docs/CONVENTIONS.md` §6 and `.env.example`):

- `PA_INFERENCE_BASE_URL` — OpenAI-compatible endpoint for all generation.
- `PA_GEN_MODEL` — chat/generation model the wizard selected.
- `PA_DB2_URL` — the Blackboard (DB-2, `postgres-gamestate`).
- `PA_NETWORK` — gates the Custodian (regtest by default).

> ⚠️ **Scaffolding.** Every file in this service is a commented stub with `TODO`s marking
> where real logic goes. Nothing here talks to a real model or DB yet.
