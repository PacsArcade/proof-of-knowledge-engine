"""corpus/relays.py — the verse subscription registry (nostr-relay-style). 💜

Multi-relay verse subscription. A node subscribes to whatever **verses** it wants to see —
exactly like subscribing to a set of **nostr relays** — and the corpus mesh keeps the *union*
of their group knowledge synced over BitTorrent.

The nostr analogy (say it plainly, so the mental model transfers):

  * A **verse** ≈ a **nostr relay**. It advertises a body of corpus knowledge you can pull.
  * You **subscribe** to any verse you want (`subscribe()`), and **unsubscribe** to stop
    (`unsubscribe()`) — the same freedom nostr gives you over relays.
  * What you actually sync is the **union of every *enabled* verse's corpora**. Toggle a verse
    on/off with `set_enabled()` without forgetting it (like muting a relay).
  * Trust is **per-verse and pinned**: each verse's signed manifest is verified against *its own*
    pinned `pubkey` before any shard reaches DB-1 — see `manifest.py::verify_manifest()`. A verse
    you subscribe to is not a verse you blindly trust; the manifest signature is the gate.

This module is the **subscription config** only — pure, file-backed, no network. The BitTorrent
wiring that joins the union of enabled swarms lives in `torrent.py`; the trust crypto lives in
`manifest.py`. This is COLD-tier config: it never touches the gameplay hot path.

## The shared config file

Subscriptions live in a JSON file at `PA_RELAYS_FILE` (default `data/relays.json`). The MUD's
operator/admin rails read and write the **same file**, so the schema is fixed and must match
exactly on both sides:

```json
{"relays": [
  {"name": "pacs-common", "ref": "magnet:?xt=urn:btih:...", "pubkey": "npub1... or null",
   "kind": "verse", "enabled": true, "added_at": "2026-07-07T..."}
]}
```

  * `name`      — stable, human handle for the subscription; the upsert key.
  * `ref`       — how to reach it: a magnet URI / bare infohash, OR a verse pubkey / relay URL.
  * `pubkey`    — the pinned trust anchor whose signature the verse's manifest must carry
                  (`null` if not yet known — the swarm is joined but nothing is trusted into DB-1).
  * `kind`      — `"verse"` (a whole verse advertising *many* corpora) or `"corpus"` (a single
                  corpus swarm).
  * `enabled`   — whether this verse is part of the synced union right now.
  * `added_at`  — ISO-8601 UTC timestamp of first subscription.

On first load the file is seeded with the canonical **`pacs-common`** verse (enabled), using
`PA_COMMON_KNOWLEDGE` / `PA_COMMON_KNOWLEDGE_MAGNET` / `PA_COMMON_KNOWLEDGE_PUBKEY` if present —
so a fresh node already carries Pac's Arcade's shared ground truth, and the operator can add more.

Design doc: docs/CORPUS-MESH.md ("Multi-relay subscription").
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Optional

# --------------------------------------------------------------------------- #
# Config (env — CONVENTIONS §6)                                                #
# --------------------------------------------------------------------------- #

# Where the shared subscription list lives. The MUD admin rails point at the SAME path.
DEFAULT_RELAYS_FILE = "data/relays.json"

# The canonical verse every node carries by default (the federation's shared ground truth). Seeded
# on first load from the common-knowledge env so a fresh box starts already subscribed to Pac's.
CANONICAL_VERSE_NAME = "pacs-common"

# What a `kind` may be. "verse" advertises many corpora; "corpus" is a single swarm.
VALID_KINDS = ("verse", "corpus")


def _relays_path() -> str:
    """Resolve the subscription file path (env-overridable, read fresh so tests can repoint it)."""
    return os.environ.get("PA_RELAYS_FILE", DEFAULT_RELAYS_FILE)


def _now_iso() -> str:
    """ISO-8601 UTC timestamp, second precision — e.g. '2026-07-07T12:00:00+00:00'."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- #
# Seeding + persistence                                                        #
# --------------------------------------------------------------------------- #

def _seed_document() -> dict:
    """Build the first-run document: the canonical `pacs-common` verse, enabled.

    `ref`/`pubkey` come from the common-knowledge env if present (`PA_COMMON_KNOWLEDGE_MAGNET` is
    the bootstrap ref, falling back to the `PA_COMMON_KNOWLEDGE` corpus id; `PA_COMMON_KNOWLEDGE_PUBKEY`
    is the pinned trust anchor). Read fresh from the environment so it reflects the running config.
    """
    common_id = os.environ.get("PA_COMMON_KNOWLEDGE", "common-knowledge")
    magnet = os.environ.get("PA_COMMON_KNOWLEDGE_MAGNET", "")
    pubkey = os.environ.get("PA_COMMON_KNOWLEDGE_PUBKEY", "")
    return {
        "relays": [
            {
                "name": CANONICAL_VERSE_NAME,
                "ref": magnet or common_id,
                "pubkey": pubkey or None,
                "kind": "verse",
                "enabled": True,
                "added_at": _now_iso(),
            }
        ]
    }


def _normalize(doc: object) -> dict:
    """Coerce whatever we read into the canonical `{"relays": [...]}` shape (never raise on shape)."""
    if isinstance(doc, dict) and isinstance(doc.get("relays"), list):
        return {"relays": [r for r in doc["relays"] if isinstance(r, dict)]}
    return {"relays": []}


def _write(doc: dict) -> None:
    """Atomically persist the subscription document (temp file + os.replace).

    Atomic because the MUD admin rails write the same file; a half-written JSON must never be
    observed by the other reader.
    """
    path = _relays_path()
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".relays-", suffix=".json", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)          # atomic on POSIX and Windows
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# --------------------------------------------------------------------------- #
# Public API (pure, file-backed)                                              #
# --------------------------------------------------------------------------- #

def load() -> dict:
    """Return the full subscription document, creating + seeding the file on first use.

    Creates the `data/` dir and `relays.json` (seeded with the canonical `pacs-common` verse) if
    they don't exist yet. A malformed/foreign file is normalized to the canonical shape rather than
    raising — the operator UI should degrade, not crash.
    """
    path = _relays_path()
    if not os.path.exists(path):
        doc = _seed_document()
        _write(doc)
        return doc
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return _normalize(json.load(fh))
    except (json.JSONDecodeError, OSError):
        # Corrupt or unreadable — reseed rather than wedge the node. (TODO: node-doctor warning.)
        doc = _seed_document()
        _write(doc)
        return doc


def list_relays() -> list[dict]:
    """Return the list of subscribed verses/corpora (every entry, enabled or not)."""
    return load()["relays"]


def enabled_relays() -> list[dict]:
    """Return only the *enabled* subscriptions — the set whose union `torrent.py` actually syncs."""
    return [r for r in list_relays() if r.get("enabled")]


def get(name: str) -> Optional[dict]:
    """Return the subscription entry with this name, or None."""
    for r in list_relays():
        if r.get("name") == name:
            return r
    return None


def subscribe(name: str, ref: str, kind: str = "verse", pubkey: Optional[str] = None) -> dict:
    """Subscribe to a verse (or a single corpus). Idempotent upsert keyed by `name`.

    New subscription  → added enabled, stamped `added_at`.
    Existing `name`   → `ref` and `kind` are updated; `enabled` and `added_at` are preserved; the
                        pinned `pubkey` is overwritten only when a non-None `pubkey` is supplied
                        (so a bare re-subscribe never silently drops a verse's trust anchor).

    `kind` must be one of VALID_KINDS ("verse" | "corpus").
    """
    if kind not in VALID_KINDS:
        raise ValueError(f"kind must be one of {VALID_KINDS}, got {kind!r}")

    doc = load()
    for r in doc["relays"]:
        if r.get("name") == name:                       # upsert: update in place
            r["ref"] = ref
            r["kind"] = kind
            if pubkey is not None:
                r["pubkey"] = pubkey
            r.setdefault("enabled", True)
            r.setdefault("added_at", _now_iso())
            _write(doc)
            return r

    entry = {
        "name": name,
        "ref": ref,
        "pubkey": pubkey,
        "kind": kind,
        "enabled": True,
        "added_at": _now_iso(),
    }
    doc["relays"].append(entry)
    _write(doc)
    return entry


def unsubscribe(name: str) -> bool:
    """Drop a subscription by name. Returns True if something was removed, False if not found."""
    doc = load()
    before = len(doc["relays"])
    doc["relays"] = [r for r in doc["relays"] if r.get("name") != name]
    removed = len(doc["relays"]) != before
    if removed:
        _write(doc)
    return removed


def set_enabled(name: str, enabled: bool) -> Optional[dict]:
    """Toggle a subscription into/out of the synced union (like muting a nostr relay).

    Returns the updated entry, or None if `name` isn't subscribed.
    """
    doc = load()
    for r in doc["relays"]:
        if r.get("name") == name:
            r["enabled"] = bool(enabled)
            _write(doc)
            return r
    return None


# --------------------------------------------------------------------------- #
# CLI — inspect/edit subscriptions by hand (torrent.py wraps these too)        #
# --------------------------------------------------------------------------- #

def _print_relays() -> None:
    rows = list_relays()
    if not rows:
        print("(no subscriptions)")
        return
    for r in rows:
        flag = "on " if r.get("enabled") else "off"
        pin = (r.get("pubkey") or "-")
        print(f"[{flag}] {r.get('name',''):<20} {r.get('kind','verse'):<6} {pin:<16} {r.get('ref','')}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog="relays.py",
        description="Verse subscription registry (nostr-relay-style). See docs/CORPUS-MESH.md.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List all subscribed verses/corpora.")

    p_sub = sub.add_parser("subscribe", help="Subscribe to (or update) a verse/corpus.")
    p_sub.add_argument("name", help="stable handle, e.g. 'pacs-common' or 'operator:pac/btc-101'")
    p_sub.add_argument("ref", help="magnet/infohash OR verse pubkey/relay URL")
    p_sub.add_argument("--kind", default="verse", choices=VALID_KINDS, help="verse | corpus")
    p_sub.add_argument("--pubkey", default=None, help="pinned trust anchor (npub/hex) for manifest verify")

    p_unsub = sub.add_parser("unsubscribe", help="Remove a subscription by name.")
    p_unsub.add_argument("name")

    p_en = sub.add_parser("enable", help="Enable a subscription (add it to the synced union).")
    p_en.add_argument("name")
    p_dis = sub.add_parser("disable", help="Disable a subscription (keep it, but stop syncing).")
    p_dis.add_argument("name")

    args = parser.parse_args()
    if args.cmd == "list":
        _print_relays()
    elif args.cmd == "subscribe":
        r = subscribe(args.name, args.ref, kind=args.kind, pubkey=args.pubkey)
        print(f"[subscribe] {r['name']} ({r['kind']}) -> {r['ref']}  enabled={r['enabled']}")
    elif args.cmd == "unsubscribe":
        ok = unsubscribe(args.name)
        print(f"[unsubscribe] {args.name}: {'removed' if ok else 'not found'}")
    elif args.cmd == "enable":
        r = set_enabled(args.name, True)
        print(f"[enable] {args.name}: {'enabled' if r else 'not found'}")
    elif args.cmd == "disable":
        r = set_enabled(args.name, False)
        print(f"[disable] {args.name}: {'disabled' if r else 'not found'}")
