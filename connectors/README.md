# connectors — supplemental knowledge sources for The Source 💜

> Part of **Pac's Arcade — Proof of Knowledge Engine (P.O.K.E.)**.
> See the canonical contract in [`docs/CONVENTIONS.md`](../docs/CONVENTIONS.md).

## What a connector is

A **connector** is a small, optional plug-in that pulls records from a *supplemental* knowledge
source and feeds them into the corpus ingest pipeline, which embeds them into **DB-1**
(`postgres-source`, The Source). Simple English Wikipedia is the baseline corpus; connectors are
how an operator adds *more* — their meetup's markdown notes, long-form nostr articles, another
Kiwix ZIM, and so on.

Connectors do **not** write to DB-1 directly. They only *yield records*; the Archivist's
`corpus` ingest pipeline (see [`services/corpus/ingest.py`](../services/corpus/ingest.py)) does
the chunking, embedding (`PA_EMBED_MODEL`), and pgvector inserts. One writer, one place.

## The interface

Every connector exposes a single async generator:

```python
async def fetch() -> AsyncIterator[dict]:
    """Yield records shaped like:
        {
            "source_url": str,   # canonical, de-dupable identity of the item
            "title":      str,   # human-readable title
            "content":    str,   # plain text / markdown body to be embedded
        }
    """
```

The ingest pipeline consumes `fetch()` exactly like it consumes ZIM articles:
`fetch() → chunk → embed(PA_EMBED_MODEL) → INSERT INTO documents`. See `ingest_records()` in
`services/corpus/ingest.py`.

Each connector directory also carries a **`manifest.json`**:

```json
{
  "name": "...",
  "type": "...",
  "description": "...",
  "enabled": false
}
```

## Tier & posture

**COLD, and optional / opt-in.** Connectors may reach out to the network (nostr relays, a remote
ZIM), so they are strictly COLD tier and **disabled by default** (`"enabled": false`). This keeps
the node **offline-first**: nothing pulls external knowledge unless the operator turns it on. A
connector must never sit on a gameplay hot path — ingest runs as a background job.

## How an operator adds a new supplemental source

1. Create a folder `connectors/<my-source>/`.
2. Add a `manifest.json` (`name`, `type`, `description`, `enabled: false`).
3. Add a `connector.py` implementing `async def fetch()` yielding the record shape above.
4. Flip `"enabled": true` in the manifest when ready to opt in.
5. Point the corpus ingest job at it (the Archivist discovers enabled connectors and runs their
   `fetch()` through `ingest_records()`).

## Bundled connectors (all disabled by default)

| Directory | Type | Source |
|-----------|------|--------|
| [`wikipedia-zim/`](./wikipedia-zim/) | `zim` | A Kiwix ZIM archive (offline Wikipedia and friends). |
| [`nostr/`](./nostr/) | `nostr` | Long-form NIP-23 articles from nostr relays. |
| [`custom-markdown/`](./custom-markdown/) | `markdown` | A local folder of `.md` files. |

> ⚠️ **Scaffolding.** Each `connector.py` is a commented stub implementing the `fetch()`
> interface with `TODO`s where the real source reading goes.
