---
name: corpus-ingest
description: Ingest a knowledge corpus into DB-1 (the read-only vectorized Source) and manage the shared corpus mesh. Use when someone wants to "load Wikipedia", "clone the knowledge base", "ingest a ZIM", "add a knowledge connector", "re-embed the corpus", or "join/seed the corpus torrent". Handles Simple English Wikipedia first, with an upgrade path to full enwiki and curated subsets.
---

# Corpus Ingest 📚

You fill **DB-1 (`postgres-source`, 5433)** — *The Source* — the read-only, vectorized ground
truth the whole node checks itself against. Get this right and the guardrail can do its job.

## The pipeline
1. **Acquire** the corpus. Default `PA_CORPUS=simple-wikipedia` — a Kiwix **ZIM** (~350k
   articles) that embeds locally on a 4070 Ti in **hours, not weeks**. Options:
   `simple-wikipedia` → `en-wikipedia` (full, ~6.9M articles, a multi-week batch) → `curated`
   (only the operator's subjects, via connectors).
2. **Extract** articles from the ZIM (`connectors/wikipedia-zim`).
3. **Chunk** semantically with overlap — keep chunks retrieval-sized, preserve headings for
   context. Never load the whole corpus into memory; stream and batch.
4. **Embed** each chunk via `PA_EMBED_MODEL` (nomic-embed-text, 768-dim) through
   `PA_INFERENCE_BASE_URL`.
5. **Upsert** into DB-1 `documents` (source, source_url, title, chunk_index, content, embedding,
   tsv) so both vector KNN and full-text (hybrid) search work.

Run it via `services/corpus/ingest.py`. Show honest progress/time estimates — full enwiki is a
commitment; Simple English is a coffee break.

## The corpus mesh (COLD tier — never on the gameplay path)
- Shards are **content-addressed** and shared over **BitTorrent** (port 6881) so a Verse pulls
  only the bits it needs and repairs from peers instead of re-embedding from scratch.
- **Background prefetch** popular shards; keep an **LRU cache**. A cache miss degrades
  **in-fiction** ("The Archivist is retrieving that tome from the network…"), never a hang.
- A room/embedding generated on one Verse can be reused on another via the mesh.

## The knowledge swarm (seed / sync / link / serve)
The mesh is a **peer-to-peer knowledge swarm**. Pac's Arcade (the non-profit) **seeds the first
canonical "common knowledge" corpus**; every other Verse can sync it, add its own sources
alongside, and re-share. Full design: `docs/CORPUS-MESH.md`. Code: `services/corpus/torrent.py`
(swarm/cache) + `services/corpus/manifest.py` (signed shard manifests). Modes:

- **Seed** (Pac's Arcade) — `python torrent.py seed`. Packs DB-1 into content-addressed shards,
  builds + **signs** a shard manifest with the seed key, creates + seeds the torrent, and
  publishes the **magnet/infohash** for operators to sync against.
- **Sync common** — `python torrent.py sync-common`. Joins the `common-knowledge` swarm
  (`PA_COMMON_KNOWLEDGE_MAGNET`), **verifies the manifest signature** against Pac's Arcade's
  pinned key (`PA_COMMON_KNOWLEDGE_PUBKEY`), then pulls verified shards. **On by default** via
  `connectors/common-knowledge/` (`enabled: true`) — the shared baseline every Verse can carry.
- **Add your own alongside common** — `python torrent.py link-source <corpus_id>`. Publishes an
  operator's *own* ingested material as its **own swarm**, signed with the **operator's own key**,
  running next to common. A Verse can carry common only, common + its own topics, or seed a niche
  corpus for the federation — all at once (one session, many swarms).
- **Serve** — `python torrent.py serve`. The background daemon: carries the swarms, prefetches
  popular shards, keeps the LRU warm, DHT-first with optional tracker fallback.

### Trust / verification model (why sync is safe on by default)
Two independent gates, **both must pass** before any shard reaches DB-1:
1. **Signed manifest** — the shard list must be signed by the **pinned trust anchor** (Pac's
   Arcade's key for `common-knowledge`; the operator's own key for a linked source).
2. **Content hash** — each downloaded shard's bytes must match the `content_hash` in that
   verified manifest.
Fail either → **refuse, don't warn**. DB-1 is what the guardrail checks everything against, so a
poisoned shard would corrupt the whole node — we **fail closed** (see `docs/SECURITY.md`).
Discovery is **DHT-first** (no central server), with trackers as an optional fallback.

Env: `PA_COMMON_KNOWLEDGE`, `PA_COMMON_KNOWLEDGE_MAGNET`, `PA_COMMON_KNOWLEDGE_PUBKEY`,
`PA_TORRENT_PORT` (6881), `PA_CORPUS_CACHE_GB`, `PA_CORPUS_DATA_DIR`, `PA_TORRENT_TRACKERS`,
`PA_MANIFEST_SIGNING_KEY`.

## Connectors (supplemental sources — opt-in, offline-first)
Add a source under `connectors/<name>/` implementing `fetch()` → `{source_url, title, content}`;
it feeds the same pipeline into DB-1. Existing stubs: `wikipedia-zim`, `nostr` (NIP-23 long-form),
`custom-markdown` (a local folder of `.md`). Nothing fetches unless the operator enables it in
its `manifest.json`.

## Rules
- DB-1 is **read-only** except this pipeline. Never let game logic write to The Source.
- Default to Simple English; make scale an explicit, informed operator choice.
- Content-addressed + torrent so the community shares the load — that's the whole point.
