# corpus — ingest + pgvector loader + torrent seeder 💜

> Part of **Pac's Arcade — Proof of Knowledge Engine (P.O.K.E.)**.
> See the canonical contract in [`docs/CONVENTIONS.md`](../../docs/CONVENTIONS.md).

## Role

`corpus` builds and shares **The Source** (DB-1 `postgres-source`). It does two jobs, both
owned by the **Archivist** agent:

1. **Ingest** (`ingest.py`) — take a ZIM file (Kiwix/Wikipedia), extract articles, chunk them,
   embed each chunk with `PA_EMBED_MODEL`, and insert into DB-1 `documents` (pgvector). This is
   the *only* writer to DB-1 — The Source is read-only to everything else.
2. **Mesh** (`torrent.py`) — seed and fetch corpus shards over BitTorrent so nodes can share the
   heavy lifting of a big corpus. Keeps a local LRU cache; **prefetches in the background**.

## Tier

**COLD.** Seconds→minutes, async, and it **crosses the network** (the torrent mesh). It **must
never block gameplay.** A cache miss degrades **in-fiction** — the Archivist answers "The
Archivist is retrieving that tome from the network…" and queues a background fetch. Never a hang.

## Ports

- **8083** — corpus service HTTP API (docker-compose service name: `corpus`).
- **6881** — BitTorrent (seed/fetch corpus shards).

## How it fits the whole

```
 ZIM file ─► ingest.py ─► chunk ─► embed (PA_EMBED_MODEL) ─► DB-1 documents (pgvector)
                                                                   ▲
 corpus mesh ─► torrent.py (LRU cache, background prefetch) ───────┘
      │
      └── cache miss ─► "The Archivist is retrieving that tome from the network…" (in-fiction)
```

Connectors (`connectors/`) feed *supplemental* records into this same ingest pipeline — see
[`connectors/README.md`](../../connectors/README.md).

## How to run it

```bash
docker compose up corpus
# or, local dev:
cd services/corpus
pip install httpx asyncpg pgvector libzim libtorrent   # TODO: pin in requirements.txt
python ingest.py  path/to/wikipedia.zim                 # TODO: add CLI arg parsing
python torrent.py --seed                                # TODO: add CLI
```

Required env: `PA_CORPUS`, `PA_EMBED_MODEL`, `PA_INFERENCE_BASE_URL`, `PA_DB1_URL`,
`PA_CORPUS_TORRENT`.

> ⚠️ **Scaffolding.** `ingest.py` and `torrent.py` are commented stubs with `TODO`s where the
> ZIM parsing, embedding, pgvector inserts, and libtorrent wiring go.
