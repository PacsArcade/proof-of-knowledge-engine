"""connectors/wikipedia-zim/connector.py — Kiwix ZIM → corpus records. 💜

SCAFFOLDING / STUB. Implements the connector `fetch()` interface (see connectors/README.md).

Reads a Kiwix ZIM archive (offline Wikipedia and friends) and yields one record per article for
the corpus ingest pipeline, which chunks + embeds + inserts them into DB-1.

Tier: COLD. Optional / opt-in (manifest `enabled: false`). Offline-capable — a local ZIM never
touches the network. Runs as a background ingest job; never on a gameplay hot path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import AsyncIterator

# Load this connector's manifest to pick up its config (zim_path, namespaces).
_MANIFEST = json.loads((Path(__file__).parent / "manifest.json").read_text(encoding="utf-8"))
_CONFIG = _MANIFEST.get("config", {})

ZIM_PATH = os.environ.get("PA_ZIM_PATH", _CONFIG.get("zim_path", "/corpus/zim/wikipedia_simple.zim"))
NAMESPACES = _CONFIG.get("namespaces", ["A"])   # "A" = articles in the ZIM spec.


async def fetch() -> AsyncIterator[dict]:
    """Yield {source_url, title, content} for each article in the ZIM.

    The corpus ingest pipeline consumes this exactly like native ZIM ingest — see
    `ingest_records()` in services/corpus/ingest.py.
    """
    # TODO: open ZIM_PATH with `libzim` (Archive), iterate entries, keep only NAMESPACES,
    #       strip HTML to clean text, and for each article yield:
    #         {
    #           "source_url": f"zim://{ZIM_PATH}#{entry.path}",
    #           "title": entry.title,
    #           "content": clean_text,
    #         }
    #       Yield lazily so a multi-GB ZIM never has to fit in memory.
    raise NotImplementedError("TODO: read ZIM at %s and yield article records" % ZIM_PATH)
    # Unreachable, kept so tooling sees this as an async generator:
    if False:  # pragma: no cover
        yield {}
