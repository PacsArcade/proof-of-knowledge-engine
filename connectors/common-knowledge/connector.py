"""connectors/common-knowledge/connector.py — the shared corpus swarm → corpus records. 💜

SCAFFOLDING / STUB. Implements the connector `fetch()` interface (see connectors/README.md).

This is the canonical shared corpus. It joins Pac's Arcade's **common-knowledge** BitTorrent swarm
(via services/corpus/torrent.py), VERIFIES the signed shard manifest against Pac's Arcade's pinned
key (services/corpus/manifest.py), pulls each content-addressed shard, and yields one record per
document into the ingest pipeline — which chunks, embeds, and inserts them into DB-1.

Unlike most connectors this ships **enabled: true**: "common knowledge" is the shared baseline the
whole federation carries. It's still COLD tier and never on a gameplay hot path — ingest is a
background job, and the mesh degrades in-fiction on a miss.

Trust model (why this connector is safe to have on by default):
  * content addressing — every shard's bytes must hash to the `content_hash` in the manifest;
  * signed manifest — the manifest itself must be signed by Pac's Arcade's pinned key.
Fail either check → the shard is refused, never ingested. See docs/CORPUS-MESH.md (poisoning defense).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import AsyncIterator

# Reach the corpus service modules (torrent.py / manifest.py) for the swarm + verification layer.
_CORPUS_DIR = Path(__file__).resolve().parents[2] / "services" / "corpus"
if str(_CORPUS_DIR) not in sys.path:
    sys.path.insert(0, str(_CORPUS_DIR))

_MANIFEST = json.loads((Path(__file__).parent / "manifest.json").read_text(encoding="utf-8"))
_CONFIG = _MANIFEST.get("config", {})

# Which swarm to join and how to bootstrap it. Env overrides let an operator point at a mirror.
CORPUS_ID = os.environ.get("PA_COMMON_KNOWLEDGE", _CONFIG.get("corpus_id", "common-knowledge"))
MAGNET = os.environ.get("PA_COMMON_KNOWLEDGE_MAGNET", _CONFIG.get("magnet", ""))
TRACKERS = _CONFIG.get("trackers", [])


async def fetch() -> AsyncIterator[dict]:
    """Yield {source_url, title, content} for each document in the verified common-knowledge corpus.

    Consumed by `ingest_records()` in services/corpus/ingest.py exactly like any other connector.
    """
    # Import here so a box without python-libtorrent can still import this module for inspection.
    from manifest import from_json, verify_manifest, verify_shard_bytes  # noqa: F401
    from torrent import CorpusMesh, KnowledgeSwarm

    if not MAGNET:
        # No bootstrap yet (Pac's Arcade publishes the magnet/infohash once the seed is live).
        # Nothing to sync — yield nothing rather than fetch from an untrusted default.
        return

    mesh = CorpusMesh()
    await mesh.start()
    swarm = KnowledgeSwarm(corpus_id=CORPUS_ID, magnet=MAGNET, role="leech", trackers=TRACKERS)

    # TODO: pull the signed manifest.json from the swarm, then GATE on its signature:
    #   raw = await mesh.fetch_manifest_bytes(swarm)          # a well-known shard / side channel
    #   swarm.manifest = from_json(raw.decode("utf-8"))
    #   if not verify_manifest(swarm.manifest):               # checks Pac's Arcade's pinned key
    #       raise PermissionError("common-knowledge manifest failed signature check — refusing ingest")
    await mesh.join_swarm(swarm)

    # TODO: for each ShardRef in the verified manifest, pull + verify the shard, unpack it into its
    #       constituent documents, and yield each as a record:
    #   for ref in swarm.manifest.shards:
    #       shard = await _pull_and_verify(mesh, swarm, ref)  # verify_shard_bytes() inside
    #       for doc in _unpack_documents(shard):              # a shard packs many DB-1 rows
    #           yield {
    #               "source_url": doc.source_url,             # e.g. "zim://…#Bitcoin" — de-dupable
    #               "title": doc.title,
    #               "content": doc.content,                   # plain text / markdown to embed
    #           }
    raise NotImplementedError(
        "TODO: verify common-knowledge manifest, pull verified shards, yield document records"
    )
    if False:  # pragma: no cover - keeps tooling treating this as an async generator
        yield {}
