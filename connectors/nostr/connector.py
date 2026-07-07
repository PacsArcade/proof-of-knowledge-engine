"""connectors/nostr/connector.py — long-form NIP-23 notes → corpus records. 💜

SCAFFOLDING / STUB. Implements the connector `fetch()` interface (see connectors/README.md).

Subscribes to long-form articles (NIP-23, kind 30023) from configured nostr relays and yields
each as a record for the corpus ingest pipeline (chunk → embed → DB-1).

Tier: COLD. Optional / opt-in (manifest `enabled: false`) and it CROSSES THE NETWORK (relay
websockets) — so it stays off by default to keep the node offline-first. Background job only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncIterator

_MANIFEST = json.loads((Path(__file__).parent / "manifest.json").read_text(encoding="utf-8"))
_CONFIG = _MANIFEST.get("config", {})

RELAYS = _CONFIG.get("relays", [])
KINDS = _CONFIG.get("kinds", [30023])     # NIP-23 long-form content.
AUTHORS = _CONFIG.get("authors", [])       # optional allow-list of pubkeys; empty = any.


async def fetch() -> AsyncIterator[dict]:
    """Yield {source_url, title, content} for each long-form nostr article.

    Consumed by `ingest_records()` in services/corpus/ingest.py.
    """
    # TODO: open a websocket to each relay in RELAYS; send a REQ with a filter
    #       {"kinds": KINDS, "authors": AUTHORS or <omit>}; for each EVENT:
    #         - title   := the "title" tag (NIP-23), fallback to first heading
    #         - content := event.content (markdown)
    #         - source_url := f"nostr:{event.id}"  (or an naddr for the article)
    #       De-dupe on source_url. Close the socket after EOSE for a one-shot ingest.
    #       Verify signatures before trusting content.
    raise NotImplementedError("TODO: subscribe to NIP-23 notes on relays %r" % RELAYS)
    if False:  # pragma: no cover
        yield {}
