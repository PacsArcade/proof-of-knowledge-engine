# CONVENTIONS — the shared contract 💜

> Every service, script, agent, and skill in this repo agrees on the names, ports,
> and tiers below. If you are a build agent, **treat this file as canonical.** Do not
> invent new service names or ports; reference these.

Pac's Arcade — **The Federated Knowledge Engine**. A community-owned, federated,
gamified education node. Fully open-source, self-hostable, offline-capable. No
proprietary APIs, ever.

Brand voice: we say **"fren"**, never "friend" 💜. We teach with game language and
explain **consequences, not prohibitions**. See `.claude/skills/pacbot`.

---

## 1. The three transport tiers (the latency contract)

The single most important rule in this codebase: **the mesh is never on the hot path.**

| Tier | What runs here | Latency budget | Crosses the network? |
|------|----------------|----------------|----------------------|
| **HOT** | MUD commands, Luanti world actions, state-sync, DB-2 game state | < 50 ms | No — node-local, authoritative |
| **WARM** | LLM generation (Oracle dialogue, Architect rooms), guardrail embed | first token < 300 ms | No — local GPU |
| **COLD** | Matrix federation, BitTorrent corpus mesh, on-chain discovery | seconds→minutes, async | Yes — background, eventually-consistent |

Gameplay must **never block** on a COLD-tier operation. A corpus cache-miss degrades
**in-fiction** ("The Archivist is retrieving that tome from the network…"), never as a hang.
See `docs/LATENCY.md`.

---

## 2. Canonical services & ports (compose.yaml service names)

| Service name | Role | Host port | Tier |
|--------------|------|-----------|------|
| `postgres-gamestate` | DB-2, the live world | 5432 | HOT |
| `postgres-source` | DB-1, read-only vectorized knowledge (pgvector) | 5433 | WARM/COLD |
| `state-sync` | Translation API: Luanti ⇄ MUD ⇄ DB-2 | 8082 | HOT |
| `mud` | Text terminal MUD server (telnet/SSH, ANSI) | 4000 | HOT |
| `luanti` | Voxel Verse (Minetest engine) | 30000/udp | HOT |
| `inference` | Local LLM (Ollama **or** vLLM, pluggable) | 11434 (ollama) / 8000 (vllm) | WARM |
| `orchestrator` | The agent swarm (openclaw-style) | 8080 | WARM |
| `guardrail` | Hallucination check vs DB-1 | 8081 | WARM |
| `corpus` | Ingest + pgvector loader + torrent seeder | 8083 / 6881 (bt) | COLD |
| `matrix` | Dendrite homeserver | 8008 / 8448 (federation) | COLD |
| `matrix-bridge` | Bridges MUD/Luanti chat ⇄ Matrix rooms | 8084 | COLD |
| `bitcoin` | Bitcoin node (**regtest by default**) | 18443 rpc / 18444 p2p | COLD |
| `bitcoin-bridge` | Vault: SSS seed loot, tipping, OP_RETURN discovery | 8085 | COLD |

**Inference is pluggable.** All generation goes through one OpenAI-compatible interface
at `INFERENCE_BASE_URL`. The node-wizard picks the backend: Ollama for small/solo nodes,
vLLM (continuous batching) when it detects the VRAM + concurrency to justify it.

---

## 3. The two databases (the guardrail loop)

- **DB-1 `postgres-source`** — *The Source*. Read-only. Holds the exact Markdown of the
  knowledge corpus (Simple English Wikipedia first; see `connectors/`), chunked and
  embedded into `pgvector`. Nothing writes here except the corpus ingest pipeline.
- **DB-2 `postgres-gamestate`** — *The Game State* / the **Blackboard**. The live world:
  users, topics, rooms, world objects, competency nodes, seed-fragment ledger.

Guardrail rule: any AI-generated room/course/puzzle is embedded and checked for semantic
similarity against DB-1. Below threshold → **quarantined** → the server operator is pinged
in their encrypted Matrix admin room to approve or reject. Human is the final guardrail.

---

## 4. The agent swarm (runtime — openclaw-managed)

These are **product runtime agents** (persona specs live in `services/orchestrator/agents/`),
distinct from the `.claude/agents/` build agents.

| Agent | Nickname | Job |
|-------|----------|-----|
| **Oracle** | The Interview Bot | Socratic dialogue; assesses mastery; writes `competency_node`. Brain = pacbot skill. |
| **Architect** | The Knowledge Agent | Watches the Blackboard; generates Training Dungeon rooms targeting knowledge gaps. |
| **Custodian** | The Vault | Manages seed-phrase loot via Shamir's Secret Sharing. **Regtest-only** until security sign-off. |
| **Archivist** | The Corpus Keeper | Corpus ingest, pgvector, torrent mesh, cache. |
| **Warden** | The Reviewer | Runs the guardrail loop; routes quarantines to the operator's Matrix room. |

Persistent shared state = **the Blackboard** (DB-2). Agents read/write nodes; they do not
rely on context windows alone. `honcho` tracks per-user learning style/progress.

---

## 5. Naming & layout

- Directories & service names: `kebab-case`. Database identifiers: `snake_case`.
- Env vars: `UPPER_SNAKE`, namespaced `PA_` (Pac's Arcade), e.g. `PA_INFERENCE_BASE_URL`.
- Everything offline-first. No call escapes the box unless the operator opts into a COLD-tier connector.
- License: **AGPL-3.0** — network copyleft keeps every fork community-owned.
- Money safety: **regtest is the default network.** Mainnet requires an explicit operator
  flag AND a passing `security-auditor` review. See `docs/SECURITY.md`.

---

## 6. Env var reference (see `.env.example`)

```
PA_NETWORK=regtest                 # regtest | testnet | mainnet (mainnet gated)
PA_INFERENCE_BACKEND=ollama        # ollama | vllm  (wizard sets this)
PA_INFERENCE_BASE_URL=http://inference:11434/v1
PA_GEN_MODEL=...                   # chat/generation model (wizard sets)
PA_EMBED_MODEL=nomic-embed-text    # embedding model for pgvector
PA_CORPUS=simple-wikipedia         # simple-wikipedia | en-wikipedia | curated
PA_GUARDRAIL_THRESHOLD=0.78        # cosine similarity floor before quarantine
PA_MATRIX_SERVER_NAME=...          # your homeserver domain
PA_NODE_PUBKEY=...                 # node operator identity (also the discovery key)
```
