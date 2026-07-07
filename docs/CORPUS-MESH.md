# CORPUS-MESH — the BitTorrent knowledge swarm 💜

> How Verses share a Wikipedia-scale corpus peer-to-peer without ever making the game slower.
> This doc explains the *why*; the canonical service/port/tier table lives in
> [`CONVENTIONS.md`](./CONVENTIONS.md), the latency contract in [`LATENCY.md`](./LATENCY.md), and
> the system map in [`ARCHITECTURE.md`](./ARCHITECTURE.md). Code: `services/corpus/torrent.py`,
> `services/corpus/manifest.py`, `connectors/common-knowledge/`.

## The one rule (tier reminder)

The mesh is **COLD tier**. Gameplay must never block on it.

| Tier | Lives here | Budget | Crosses the network? |
|------|-----------|--------|----------------------|
| **HOT** | MUD/Luanti actions, state-sync, DB-2 | < 50 ms | No — node-local, authoritative |
| **WARM** | LLM generation, guardrail embed/KNN | first token < 300 ms | No — local GPU |
| **COLD** | Matrix, **the corpus mesh**, on-chain discovery | seconds → minutes | Yes — async, background |

DB-1 (`postgres-source`, pgvector — *The Source*) is read **locally**. The mesh only *fills and
repairs* DB-1's shards in the background. A cache miss degrades **in-fiction** — never a hang.

## Why a mesh at all

Simple English Wikipedia embeds on a 4070 Ti in hours; full enwiki is a multi-week batch. Making
every operator re-embed the same 6.9M articles is wasteful. Instead, Pac's Arcade (the non-profit)
**embeds it once, seeds it**, and every other Verse pulls **verified shards** from the swarm —
repairing from peers instead of re-embedding from scratch. The community shares the load. That's the
whole point. 💜

## Content-addressed shards

The corpus is split into **shards** — each a packed range of DB-1 `documents` rows. A shard is named
by the **SHA-256 of its bytes** (`sha256:…`), so its name *is* its integrity check: bytes that don't
hash to the expected value are corrupt or tampered and get dropped. This is tamper-evidence for free,
and it lets a Verse pull only the shards it needs (a topic subset, a repair) rather than the whole
corpus. See `content_hash()` / `verify_shard_bytes()` in `manifest.py`.

## Signed manifests (the poisoning defense)

Content addressing proves a shard matches *a* hash. It does **not** prove the *set* of hashes is
Pac's Arcade's and not a hostile peer's look-alike corpus. That's the manifest's job.

A **shard manifest** is:

```
{ corpus_id, version, shards:[{ id, content_hash, size, covers }], created_at, signer_pubkey, signature }
```

The seed node **signs** the manifest with its private key (Ed25519). A leecher **verifies** that
signature against a **pinned trust anchor** — Pac's Arcade's published key
(`PA_COMMON_KNOWLEDGE_PUBKEY`) for the canonical corpus — *before* trusting any shard into DB-1.

Two independent gates, both must pass:

1. **Manifest signature** — proves the shard list is authentic Pac's Arcade content.
2. **Per-shard content hash** — proves each downloaded shard matches that trusted list.

Fail either → **refuse**, don't warn. A poisoned "fact" that reached DB-1 would silently corrupt the
guardrail (the Source is what everything checks itself against — CONVENTIONS §3), so we **fail
closed**. This mirrors the money-path posture in [`SECURITY.md`](./SECURITY.md): rigor where the
stakes are high, and no home-rolled crypto.

## DHT + tracker fallback

Peers are discovered **trackerless-first**:

- **DHT** (Kademlia, bootstrapped off the public routers) is the primary discovery layer — no
  central server, no single point of failure, fits the federated ethos.
- **Trackers** (`PA_TORRENT_TRACKERS`, optional) are a **fallback** for networks where DHT is
  blocked or flaky. Pac's Arcade can run one for the common corpus without it ever being *required*.
- Local Service Discovery (LSD) picks up peers on the same LAN — two Verses in one community
  building swap shards without touching the internet.

## Magnet / infohash distribution

The seed node publishes the corpus as a **magnet URI / infohash**. Operators bootstrap the swarm
from it via `PA_COMMON_KNOWLEDGE_MAGNET` (and it's recorded in
`connectors/common-knowledge/manifest.json`). The infohash identifies the swarm; the *signed
manifest* — fetched over that same swarm — is what establishes trust. Distribution channels: the
Pac's Arcade site, a `.well-known` endpoint, the onboarding wizard, and eventually OP_RETURN
discovery (ARCHITECTURE §4) so the realm directory can carry it too.

## `common` knowledge vs your `own-sources`

Every operator gets a **choice**, and they compose:

- **Sync common** (`sync-common`, on by default) — carry Pac's Arcade's canonical shared corpus.
  This is the federation's shared ground truth.
- **Link your own** (`link-source`) — publish an operator's *own* ingested material (meetup notes, a
  curated ZIM, long-form nostr — see `connectors/`) as **its own swarm**, signed with the
  **operator's own key**. Other Verses that trust that operator pin *that* key to sync it.

So a Verse can run **common only**, **common + its own topics**, or seed a niche corpus for the
federation — all at once. Supplemental sources still flow through the same ingest pipeline into DB-1
(`ingest_records()`); the mesh just decides *who else can pull them*.

## Joining multiple knowledge swarms

A node runs **one** libtorrent session (port `6881`) carrying **many** `KnowledgeSwarm`s — common,
per-topic subsets, an operator's linked source — each with its own infohash and its own signed
manifest. `CorpusMesh.join_swarm()` adds them; `get_shard(swarm_id, shard_id)` reads across them.

## Cache, prefetch, and never-block

- **LRU cache**, byte-budgeted by `PA_CORPUS_CACHE_GB` (a big corpus won't fit locally — keep the hot
  working set, evict the cold tail, repair from peers on demand).
- **Background prefetch** warms popular shards (and speculatively, shards near a player's current
  topic) so the working set is usually already resident.
- **Cache miss → in-fiction degrade.** `get_shard()` returns
  *"The Archivist is retrieving that tome from the network…"* and queues an async fetch. Gameplay
  keeps scrolling; the shard arrives, gets **verified**, and lands in the cache for next time. This
  is the exact behavior [`LATENCY.md`](./LATENCY.md) promises: a slow mesh makes cross-Verse *social*
  features slower, never *the game*.

## The four modes (`services/corpus/torrent.py`)

| Mode | Who | Does |
|------|-----|------|
| `seed` | Pac's Arcade | Pack DB-1 → shards, build + **sign** the manifest, create + seed the torrent, publish the magnet/infohash. |
| `sync-common` | any operator | Join the common swarm, **verify** the manifest against the pinned key, pull verified shards. |
| `link-source` | any operator | Register/seed the operator's **own** corpus alongside common, signed with their own key. |
| `serve` | any operator | Background daemon: carry swarms, prefetch popular shards, keep the LRU warm, DHT + tracker fallback. |

```bash
python torrent.py seed                              # Pac's Arcade canonical seed node
python torrent.py sync-common                       # pull the shared corpus (verified)
python torrent.py link-source operator:pac/btc-101  # also seed your own corpus
python torrent.py serve                             # the background daemon
```

## Verses swarming a corpus

```
                          ┌──────────────────────────────────────────────┐
                          │  Pac's Arcade SEED NODE  (the non-profit)      │
                          │  • packs DB-1 → content-addressed shards       │
                          │  • signs the manifest  (Ed25519, pinned key)   │
                          │  • publishes magnet / infohash                 │
                          └───────────────┬──────────────────────────────┘
                                          │  magnet + signed manifest
                        ┌─────────────────┼──────────────────┐
                        │   DHT (primary) + trackers (fallback)│
                        ▼                 ▼                  ▼
             ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
             │   Verse A     │  │   Verse B     │  │   Verse C     │
             │ sync-common   │◄─┤ sync-common   ├─►│ common +      │
             │ (leech→seed)  │  │ (leech→seed)  │  │ link-source   │
             │  DB-1 ▲ LRU   │  │  DB-1 ▲ LRU   │  │  DB-1 ▲ LRU   │
             └───────┼───────┘  └───────┼───────┘  └───────┼───────┘
                     └── peers swap verified shards ──┘     │  also seeds
                        (each Verse re-shares what it holds)│  operator:pac/btc-101
                                                            ▼
                                                   ┌───────────────┐
                                                   │   Verse D      │
                                                   │ syncs A's topic│
                                                   │ swarm (pins A's│
                                                   │ operator key)  │
                                                   └───────────────┘

  Every shard: verified against the signed manifest before it touches DB-1.
  Every read:  local (DB-1 + LRU). A miss → "The Archivist is retrieving that tome…" (in-fiction).
```

## Config (env — CONVENTIONS §6)

| Env var | Default | Meaning |
|---------|---------|---------|
| `PA_CORPUS_TORRENT` | `true` | Master switch for the mesh. `false` → fully local, no swarm. |
| `PA_COMMON_KNOWLEDGE` | `common-knowledge` | corpus_id of the canonical shared swarm. |
| `PA_COMMON_KNOWLEDGE_MAGNET` | *(empty)* | magnet URI / infohash bootstrapping the common swarm. |
| `PA_COMMON_KNOWLEDGE_PUBKEY` | *(empty)* | pinned key that must have signed the common manifest. |
| `PA_TORRENT_PORT` | `6881` | libtorrent listen port (CONVENTIONS §2). |
| `PA_CORPUS_CACHE_GB` | `8` | LRU byte budget for resident shards. |
| `PA_CORPUS_DATA_DIR` | `/corpus/shards` | on-disk shard store. |
| `PA_TORRENT_TRACKERS` | *(empty)* | comma-separated tracker fallback (DHT is primary). |
| `PA_MANIFEST_SIGNING_KEY` | `/corpus/keys/manifest_ed25519.key` | seed node's signing key (never in git). |
| `PA_NODE_PUBKEY` | *(empty)* | this node's identity / discovery key (CONVENTIONS §6). |

> ⚠️ **Scaffolding.** `torrent.py` and `manifest.py` are structurally real but the libtorrent
> transport and the Ed25519 sign/verify are `TODO`s behind clear interfaces. Content addressing
> (SHA-256) and the cache/swarm/CLI shape are real today.
