"""corpus/torrent.py — the BitTorrent knowledge swarm: seed, sync, link, serve. 💜

SCAFFOLDING / STUB. The mesh/cache/swarm shape is REAL; the libtorrent wiring is TODO, marked.

Verses share the weight of a Wikipedia-scale corpus by seeding and fetching content-addressed
corpus *shards* over BitTorrent (port 6881, CONVENTIONS §2). Pac's Arcade (the non-profit) runs
the canonical **seed** node for the first "common knowledge" repo and publishes its magnet/infohash;
every other operator can **sync-common** to pull it, **link-source** their own corpus to also share,
and run **serve** as a background daemon that prefetches popular shards behind an LRU cache.

Trust: a shard is named by the SHA-256 of its bytes (content addressing), and the *set* of shards is
listed in a **signed manifest** (see manifest.py). A leecher verifies the manifest signature against
Pac's Arcade's pinned key before trusting "common knowledge" into DB-1 — poisoning defense.

Tier: COLD. Crosses the network, async, eventually-consistent. It must NEVER block gameplay
(CONVENTIONS §1, docs/LATENCY.md). A cache miss degrades in-fiction ("The Archivist is retrieving
that tome from the network…") and fetches in the background — never a hang.

Design doc: docs/CORPUS-MESH.md.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

from manifest import (
    ShardManifest,
    ShardRef,
    load_manifest,
    verify_manifest,
    verify_shard_bytes,
)

# libtorrent is the transport. Import is guarded so the rest of the module (cache, manifest, CLI)
# stays importable/testable on a box that hasn't installed python-libtorrent yet.
try:  # pragma: no cover - environment dependent
    import libtorrent as lt
except ImportError:  # pragma: no cover
    lt = None  # TODO: `pip install libtorrent` (python-libtorrent) to enable the real transport.


# --------------------------------------------------------------------------- #
# Config (env — CONVENTIONS §6; report these to the .env.example owner)        #
# --------------------------------------------------------------------------- #

PA_CORPUS = os.environ.get("PA_CORPUS", "simple-wikipedia")
PA_CORPUS_TORRENT = os.environ.get("PA_CORPUS_TORRENT", "true").lower() == "true"

# The canonical shared corpus everyone can sync. On by default — it's the whole point of the mesh.
PA_COMMON_KNOWLEDGE = os.environ.get("PA_COMMON_KNOWLEDGE", "common-knowledge")
# Magnet URI (or bare infohash) that bootstraps the common-knowledge swarm. Pac's Arcade publishes
# this out-of-band and via the connectors/common-knowledge manifest.
PA_COMMON_KNOWLEDGE_MAGNET = os.environ.get("PA_COMMON_KNOWLEDGE_MAGNET", "")

PA_TORRENT_PORT = int(os.environ.get("PA_TORRENT_PORT", "6881"))     # canonical BT port (§2)
PA_CORPUS_CACHE_GB = float(os.environ.get("PA_CORPUS_CACHE_GB", "8"))  # LRU byte budget on disk
PA_CORPUS_DATA_DIR = os.environ.get("PA_CORPUS_DATA_DIR", "/corpus/shards")  # where shards live
# Optional comma-separated tracker fallback for networks where DHT is blocked/unreliable.
PA_TORRENT_TRACKERS = [
    t.strip() for t in os.environ.get("PA_TORRENT_TRACKERS", "").split(",") if t.strip()
]

CACHE_BYTES = int(PA_CORPUS_CACHE_GB * 1024 * 1024 * 1024)

# Public DHT bootstrap routers — the trackerless discovery layer. Trackers (above) are a fallback.
DHT_BOOTSTRAP = [
    ("router.bittorrent.com", 6881),
    ("router.utorrent.com", 6881),
    ("dht.libtorrent.org", 25401),
]

# In-fiction cache-miss message. The Archivist speaks; gameplay never sees a spinner or a hang.
ARCHIVIST_RETRIEVING = "The Archivist is retrieving that tome from the network…"


# --------------------------------------------------------------------------- #
# Data model                                                                   #
# --------------------------------------------------------------------------- #

@dataclass
class Shard:
    """A resident unit of the corpus (a range of DB-1 `documents` rows, packed to a file).

    `content_hash` is the shard's cryptographic identity (from manifest.py); `path` is where its
    verified bytes live on disk once fetched. `swarm_id` says which corpus/swarm it belongs to.
    """
    shard_id: str
    content_hash: str
    size_bytes: int
    swarm_id: str
    path: Optional[str] = None


@dataclass
class KnowledgeSwarm:
    """One corpus that this node participates in — its own infohash and role.

    A node can join SEVERAL swarms at once: the canonical `common-knowledge`, per-topic subsets, and
    an operator's own linked source. Each has an independent infohash and manifest.
    """
    corpus_id: str                       # e.g. "common-knowledge"
    magnet: str = ""                     # magnet URI or bare infohash bootstrapping the swarm
    role: str = "leech"                  # "seed" (we publish it) | "leech" (we pull it)
    trackers: list[str] = field(default_factory=list)
    manifest: Optional[ShardManifest] = None   # the signed shard list (verified before trust)
    handle: object = None                # libtorrent torrent_handle once added to the session


# --------------------------------------------------------------------------- #
# LRU cache (byte-budgeted, disk-backed)                                       #
# --------------------------------------------------------------------------- #

class ShardLRUCache:
    """LRU over resident shards, bounded by a BYTE budget (PA_CORPUS_CACHE_GB), not a count.

    A big corpus won't fit locally, and that's the point — keep the hot working set, evict the cold
    tail, and repair from peers on demand. Real impl backs each entry with a file under
    PA_CORPUS_DATA_DIR and stops seeding an evicted shard.
    """

    def __init__(self, capacity_bytes: int = CACHE_BYTES) -> None:
        self.capacity_bytes = capacity_bytes
        self._store: "OrderedDict[str, Shard]" = OrderedDict()
        self._bytes = 0

    def get(self, shard_id: str) -> Optional[Shard]:
        if shard_id not in self._store:
            return None
        self._store.move_to_end(shard_id)          # mark most-recently-used
        return self._store[shard_id]

    def put(self, shard: Shard) -> None:
        if shard.shard_id in self._store:
            self._bytes -= self._store[shard.shard_id].size_bytes
        self._store[shard.shard_id] = shard
        self._store.move_to_end(shard.shard_id)
        self._bytes += shard.size_bytes
        while self._bytes > self.capacity_bytes and len(self._store) > 1:
            _, evicted = self._store.popitem(last=False)   # evict least-recently-used
            self._bytes -= evicted.size_bytes
            # TODO: stop seeding the evicted shard's torrent and delete/unlink its file to free disk.

    def __contains__(self, shard_id: str) -> bool:
        return shard_id in self._store


# --------------------------------------------------------------------------- #
# The mesh                                                                     #
# --------------------------------------------------------------------------- #

class CorpusMesh:
    """Join knowledge swarms, seed/fetch content-addressed shards, keep the LRU warm — never block.

    One `CorpusMesh` owns one libtorrent session bound to PA_TORRENT_PORT and can carry many
    `KnowledgeSwarm`s (common + per-topic + operator-linked) at once.
    """

    def __init__(self) -> None:
        self.cache = ShardLRUCache()
        self._session = None                        # libtorrent session (created in start())
        self._swarms: dict[str, KnowledgeSwarm] = {}
        self._prefetch_queue: "asyncio.Queue[tuple[str, str]]" = asyncio.Queue()  # (swarm_id, shard_id)
        self._started = False

    # -- lifecycle --------------------------------------------------------- #

    async def start(self) -> None:
        """Create the libtorrent session (DHT + optional trackers) and the prefetch worker."""
        if not PA_CORPUS_TORRENT:
            return                                  # operator opted out of the mesh; stay fully local.
        if lt is None:
            # No transport installed. The cache/manifest/CLI still work; fetches will no-op.
            # TODO: surface this as a node-doctor warning rather than a silent degrade.
            self._started = True
            asyncio.create_task(self._prefetch_worker())
            return

        # TODO: build a real libtorrent session:
        #   settings = {
        #       "listen_interfaces": f"0.0.0.0:{PA_TORRENT_PORT}",
        #       "enable_dht": True, "enable_lsd": True, "enable_upnp": True, "enable_natpmp": True,
        #       "alert_mask": lt.alert.category_t.all_categories,
        #   }
        #   self._session = lt.session(settings)
        #   for host, port in DHT_BOOTSTRAP: self._session.add_dht_router(host, port)
        self._session = object()                    # placeholder handle
        self._started = True
        asyncio.create_task(self._prefetch_worker())
        asyncio.create_task(self._alert_pump())     # drain libtorrent alerts off the hot path

    # -- swarm membership -------------------------------------------------- #

    async def join_swarm(self, swarm: KnowledgeSwarm) -> KnowledgeSwarm:
        """Add a corpus swarm to the session (DHT first, trackers as fallback).

        For a leech we add by magnet/infohash and let DHT + trackers find peers; for a seed we add
        the packed shard files. The signed manifest is fetched/verified separately before we trust
        any shard into DB-1 (see `sync_common`).
        """
        self._swarms[swarm.corpus_id] = swarm
        if self._session is None or lt is None:
            return swarm                            # opted-out / no transport: registered only.

        trackers = swarm.trackers or PA_TORRENT_TRACKERS
        # TODO: real add_torrent:
        #   params = lt.parse_magnet_uri(swarm.magnet) if swarm.magnet else lt.add_torrent_params()
        #   params.save_path = PA_CORPUS_DATA_DIR
        #   params.trackers = trackers               # DHT is primary; these are the fallback (§ doc)
        #   swarm.handle = self._session.add_torrent(params)
        #   if swarm.role == "seed": swarm.handle.set_upload_mode(False)  # actually seed
        _ = trackers
        return swarm

    # -- the never-block read path ---------------------------------------- #

    async def get_shard(self, swarm_id: str, shard_id: str) -> Shard | str:
        """Return a resident Shard, or — on a miss — the in-fiction message + a queued fetch.

        NEVER blocks on the network (COLD tier rule). A cache miss returns ARCHIVIST_RETRIEVING and
        schedules a background fetch; the caller degrades in-fiction and moves on (docs/LATENCY.md).
        """
        hit = self.cache.get(shard_id)
        if hit is not None:
            return hit
        self._prefetch_queue.put_nowait((swarm_id, shard_id))
        return ARCHIVIST_RETRIEVING

    async def prefetch(self, swarm_id: str, shard_id: str) -> None:
        """Ask the background worker to pull a shard before it's needed (warms the LRU)."""
        self._prefetch_queue.put_nowait((swarm_id, shard_id))

    # -- background workers ------------------------------------------------ #

    async def _prefetch_worker(self) -> None:
        """Background loop: fetch queued shards over BitTorrent and warm the LRU. Off the hot path."""
        while True:
            swarm_id, shard_id = await self._prefetch_queue.get()
            try:
                await self._fetch_shard(swarm_id, shard_id)
            except Exception:
                # TODO: log + exponential backoff/retry. A failed COLD fetch must NEVER surface as a
                #       hang or an exception on a gameplay path — it just means "try again later".
                pass
            finally:
                self._prefetch_queue.task_done()

    async def _alert_pump(self) -> None:
        """Drain libtorrent's alert queue (piece-finished, tracker replies, DHT) in the background."""
        while True:
            # TODO: for a in self._session.pop_alerts(): react (piece finished → verify+cache; error
            #       → backoff). This keeps all torrent I/O asynchronous and off the request path.
            await asyncio.sleep(1)

    async def _fetch_shard(self, swarm_id: str, shard_id: str) -> None:
        """Download one shard from its swarm, VERIFY it, and insert it into the LRU.

        Verification is mandatory: the shard's bytes must match the `content_hash` in the swarm's
        signed, already-verified manifest. Un-verifiable bytes are dropped, never cached.
        """
        swarm = self._swarms.get(swarm_id)
        if swarm is None or swarm.manifest is None:
            return                                  # unknown/untrusted swarm — nothing to verify against.

        ref = _find_shard_ref(swarm.manifest, shard_id)
        if ref is None:
            return                                  # shard not listed in the trusted manifest → refuse.

        if lt is None or self._session is None:
            raise NotImplementedError(f"TODO: libtorrent fetch for {swarm_id}/{shard_id}")

        # TODO: resolve shard_id → its file/piece range in swarm.handle; prioritize those pieces
        #       (set_piece_deadline) so a wanted shard downloads first; await the piece-finished
        #       alert in the background; then:
        data: bytes = b""                           # placeholder for the fetched bytes
        if not verify_shard_bytes(data, ref):
            # Content-address mismatch → tampered/corrupt. Drop it; do NOT cache or ingest.
            return
        shard = Shard(
            shard_id=ref.id,
            content_hash=ref.content_hash,
            size_bytes=ref.size,
            swarm_id=swarm_id,
            path=os.path.join(PA_CORPUS_DATA_DIR, swarm_id, ref.id),
        )
        self.cache.put(shard)


def _find_shard_ref(manifest: ShardManifest, shard_id: str) -> Optional[ShardRef]:
    """Look up a shard's trusted reference (hash/size) in a verified manifest."""
    for ref in manifest.shards:
        if ref.id == shard_id:
            return ref
    return None


# --------------------------------------------------------------------------- #
# Modes (CLI verbs) — the four things an operator actually runs                #
# --------------------------------------------------------------------------- #

async def seed(corpus_id: str = PA_COMMON_KNOWLEDGE) -> None:
    """SEED MODE — Pac's Arcade's canonical seed node for the first common-knowledge repo.

    Packs DB-1 into content-addressed shards, builds + signs a manifest, creates the torrent, and
    seeds it — then prints the magnet/infohash for operators to `sync-common` against.
    """
    mesh = CorpusMesh()
    await mesh.start()
    # TODO:
    #   1. pack: read DB-1 `documents` in ranges → write shard files under PA_CORPUS_DATA_DIR;
    #      content_hash() each (manifest.py).
    #   2. manifest: build_manifest(corpus_id, version, refs) then sign_manifest() with the seed key.
    #   3. torrent: lt.create_torrent over the shard dir; add DHT + PA_TORRENT_TRACKERS; write .torrent.
    #   4. publish: print the magnet URI / infohash so this can go into connectors/common-knowledge
    #      and PA_COMMON_KNOWLEDGE_MAGNET, plus serve the signed manifest.json to the swarm.
    swarm = KnowledgeSwarm(corpus_id=corpus_id, role="seed", trackers=PA_TORRENT_TRACKERS)
    await mesh.join_swarm(swarm)
    print(f"[seed] serving corpus '{corpus_id}' on port {PA_TORRENT_PORT} (DHT + {len(PA_TORRENT_TRACKERS)} trackers)")
    print("[seed] TODO: print magnet URI / infohash here once the torrent is created")
    await _run_forever()


async def sync_common() -> None:
    """SYNC-COMMON MODE — join the canonical common-knowledge swarm and pull verified shards.

    Fetches the signed manifest, VERIFIES it against Pac's Arcade's pinned key, then pulls shards
    (verifying each against the manifest) into the cache for ingest into DB-1.
    """
    if not PA_COMMON_KNOWLEDGE_MAGNET:
        print("[sync-common] no PA_COMMON_KNOWLEDGE_MAGNET set — cannot bootstrap the swarm.")
        print("[sync-common] get the magnet/infohash from connectors/common-knowledge/manifest.json")
        return
    mesh = CorpusMesh()
    await mesh.start()
    swarm = KnowledgeSwarm(
        corpus_id=PA_COMMON_KNOWLEDGE,
        magnet=PA_COMMON_KNOWLEDGE_MAGNET,
        role="leech",
        trackers=PA_TORRENT_TRACKERS,
    )
    # TODO:
    #   1. fetch the signed manifest.json from the swarm (a known shard / a side channel).
    #   2. swarm.manifest = from_json(...); if not verify_manifest(swarm.manifest): REFUSE and bail.
    #      This is the poisoning gate — untrusted "common knowledge" never reaches DB-1.
    #   3. join_swarm; enqueue prefetch for each ShardRef; each _fetch_shard re-verifies bytes.
    await mesh.join_swarm(swarm)
    print(f"[sync-common] joined '{PA_COMMON_KNOWLEDGE}' — verifying manifest against pinned key…")
    print("[sync-common] TODO: verify_manifest() then prefetch all shards")
    await _run_forever()


async def link_source(corpus_id: str, magnet: str = "") -> None:
    """LINK-SOURCE MODE — register an operator's OWN corpus so this node also seeds/shares it.

    An operator who ingested their own material (their meetup notes, a curated ZIM) can publish it
    as its own swarm alongside common-knowledge, so other Verses can sync it too. This is the
    "link your own sources" half of the common-vs-own choice.
    """
    mesh = CorpusMesh()
    await mesh.start()
    role = "leech" if magnet else "seed"   # magnet given → join someone else's; none → seed our own.
    swarm = KnowledgeSwarm(corpus_id=corpus_id, magnet=magnet, role=role, trackers=PA_TORRENT_TRACKERS)
    # TODO (seed path): pack this operator's DB-1 subset → shards → build+sign manifest with the
    #       operator's OWN key (NOT Pac's Arcade's) → create torrent → publish magnet. Other Verses
    #       that trust this operator pin THAT key to sync it.
    await mesh.join_swarm(swarm)
    print(f"[link-source] registered corpus '{corpus_id}' as {role} alongside '{PA_COMMON_KNOWLEDGE}'")
    await _run_forever()


async def serve() -> None:
    """SERVE MODE — the background daemon: join swarms, prefetch popular shards, keep the LRU warm.

    This is what runs beside the game node in normal operation. It carries common-knowledge (and any
    linked sources), prefetches the hot working set, and answers `get_shard()` — always off the hot
    path (COLD tier). A cache miss degrades in-fiction, never a hang.
    """
    mesh = CorpusMesh()
    await mesh.start()
    if PA_COMMON_KNOWLEDGE_MAGNET:
        await mesh.join_swarm(KnowledgeSwarm(
            corpus_id=PA_COMMON_KNOWLEDGE,
            magnet=PA_COMMON_KNOWLEDGE_MAGNET,
            role="leech",
            trackers=PA_TORRENT_TRACKERS,
        ))
    # TODO: also join any operator-linked swarms discovered on disk / in config; start a popularity
    #       tracker that feeds mesh.prefetch() for the most-requested shards (speculative warming).
    print(f"[serve] corpus mesh daemon up on port {PA_TORRENT_PORT}; cache budget {PA_CORPUS_CACHE_GB} GB")
    await _run_forever()


async def _run_forever() -> None:
    """Keep a daemon alive; all real work happens in the background workers."""
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):  # pragma: no cover
        pass


# --------------------------------------------------------------------------- #
# CLI — python torrent.py {seed|sync-common|link-source|serve} [...]           #
# --------------------------------------------------------------------------- #

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="torrent.py",
        description="Pac's Arcade corpus knowledge swarm (BitTorrent, COLD tier). See docs/CORPUS-MESH.md.",
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    p_seed = sub.add_parser("seed", help="Seed a canonical corpus (Pac's Arcade seed node).")
    p_seed.add_argument("--corpus-id", default=PA_COMMON_KNOWLEDGE, help="corpus to seed")

    sub.add_parser("sync-common", help="Join the common-knowledge swarm and pull verified shards.")

    p_link = sub.add_parser("link-source", help="Register/seed your own corpus alongside common.")
    p_link.add_argument("corpus_id", help="id for your corpus, e.g. 'operator:pac/bitcoin-101'")
    p_link.add_argument("--magnet", default="", help="join an existing swarm by magnet (else seed a new one)")

    sub.add_parser("serve", help="Background daemon: prefetch + LRU cache + DHT/trackers.")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if args.mode == "seed":
        asyncio.run(seed(args.corpus_id))
    elif args.mode == "sync-common":
        asyncio.run(sync_common())
    elif args.mode == "link-source":
        asyncio.run(link_source(args.corpus_id, args.magnet))
    elif args.mode == "serve":
        asyncio.run(serve())


if __name__ == "__main__":
    main()
