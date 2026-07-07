"""corpus/manifest.py — signed shard manifests: how a leecher trusts "common knowledge". 💜

SCAFFOLDING / STUB. Hashing is REAL; the signing/verify crypto is a TODO behind a clear interface.

A **shard manifest** is the trust anchor of the corpus mesh. Pac's Arcade (the non-profit)
seeds the first canonical "common knowledge" corpus; before any other Verse ingests those shards
into DB-1 (The Source), it must prove the bytes are *authentic Pac's Arcade content* and not a
poisoned corpus injected by a hostile peer.

Two independent checks make that possible:

  1. **Content addressing** (real, here): every shard is named by the SHA-256 of its bytes. A shard
     whose bytes don't hash to its `content_hash` is rejected — tamper-evidence for free.
  2. **A signed manifest** (interface real, crypto TODO): the seeding node signs the *list* of
     shard hashes with its private key. A leecher verifies that signature against a trust anchor
     (Pac's Arcade's published pubkey for `common-knowledge`) before trusting the set. This stops a
     peer from serving a *valid-but-not-ours* corpus.

Tier: COLD. This module is pure data + crypto; it never touches the gameplay hot path. It is used
by `torrent.py` (verify before cache) and by the `common-knowledge` connector (verify before ingest).

See docs/CORPUS-MESH.md (poisoning defense) and docs/SECURITY.md (good randomness or nothing).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

# --------------------------------------------------------------------------- #
# Config / trust anchors                                                       #
# --------------------------------------------------------------------------- #

# This node's own operator identity (also the discovery key — CONVENTIONS §6).
PA_NODE_PUBKEY = os.environ.get("PA_NODE_PUBKEY", "")

# The ONE public key a leecher trusts to have signed the canonical `common-knowledge` manifest.
# Pac's Arcade publishes this out-of-band (website, well-known, the ARCHITECTURE doc). Pinning it
# is what makes "common knowledge" *Pac's Arcade's* common knowledge and not a stranger's.
PA_COMMON_KNOWLEDGE_PUBKEY = os.environ.get("PA_COMMON_KNOWLEDGE_PUBKEY", "")

# Path to this node's manifest signing key (seed nodes only). Never enters git (SECURITY.md).
PA_MANIFEST_SIGNING_KEY = os.environ.get(
    "PA_MANIFEST_SIGNING_KEY", "/corpus/keys/manifest_ed25519.key"
)

MANIFEST_SCHEMA = 1              # bump when the signed-bytes layout changes (invalidates old sigs)
HASH_ALGO = "sha256"            # content-address algorithm; part of the signed payload


# --------------------------------------------------------------------------- #
# Data model                                                                   #
# --------------------------------------------------------------------------- #

@dataclass
class ShardRef:
    """One shard's entry in the manifest — its content-addressed identity + provenance.

    `id` is a stable, human-ish handle (e.g. "simple-wikipedia/0007"); `content_hash` is the
    cryptographic identity that the bytes must match. `covers` records which corpus range this
    shard holds so a leecher can pull only the shards it needs (topic subsets, repair, etc.).
    """
    id: str
    content_hash: str            # "sha256:abcd…" over the shard's raw bytes
    size: int                    # shard size in bytes
    covers: str = ""             # free-form range hint, e.g. "documents[0:5000]" or "topic:bitcoin"


@dataclass
class ShardManifest:
    """The signed list of shards that constitute one corpus version.

    Everything except `signature` is the *signed payload*; `signature` covers the canonical bytes
    of that payload (see `canonical_payload`). A verifier recomputes those bytes and checks the sig.
    """
    corpus_id: str                       # e.g. "common-knowledge" or "operator:pac/bitcoin-101"
    version: str                         # monotonic content version, e.g. "2026.07.01"
    shards: list[ShardRef] = field(default_factory=list)
    created_at: float = field(default_factory=lambda: time.time())
    schema: int = MANIFEST_SCHEMA
    hash_algo: str = HASH_ALGO
    signer_pubkey: str = ""              # who signed this (should equal the pinned trust anchor)
    signature: str = ""                  # "" until sign_manifest() fills it; excluded from payload

    @property
    def total_bytes(self) -> int:
        return sum(s.size for s in self.shards)


# --------------------------------------------------------------------------- #
# Content addressing (REAL — this is the tamper-evidence layer)                #
# --------------------------------------------------------------------------- #

def content_hash(data: bytes) -> str:
    """Return the content address of a shard's bytes, e.g. "sha256:1a2b…". Real, not a stub."""
    digest = hashlib.new(HASH_ALGO, data).hexdigest()
    return f"{HASH_ALGO}:{digest}"


def verify_shard_bytes(data: bytes, ref: ShardRef) -> bool:
    """True iff `data` hashes to `ref.content_hash` AND its length matches. Real check.

    This alone catches corruption and blunt tampering; the manifest signature (below) is what
    proves the *set* of hashes itself wasn't swapped for a poisoned one.
    """
    if len(data) != ref.size:
        return False
    return content_hash(data) == ref.content_hash


# --------------------------------------------------------------------------- #
# Canonical serialization (REAL — the exact bytes that get signed/verified)    #
# --------------------------------------------------------------------------- #

def canonical_payload(manifest: ShardManifest) -> bytes:
    """Deterministic bytes of the manifest MINUS the signature — the thing that gets signed.

    Signing and verifying MUST hash the identical bytes, so we serialize with sorted keys, no
    whitespace, and a stable field order, and we drop `signature`. Any wobble here silently breaks
    verification — keep it boring and deterministic.
    """
    body = asdict(manifest)
    body.pop("signature", None)          # the signature never signs itself
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


# --------------------------------------------------------------------------- #
# Build                                                                        #
# --------------------------------------------------------------------------- #

def build_manifest(corpus_id: str, version: str, shards: list[ShardRef]) -> ShardManifest:
    """Assemble an *unsigned* manifest for a set of already-hashed shards.

    The caller (the seed node's packer) is responsible for having computed each ShardRef's
    `content_hash` from real shard bytes via `content_hash()`. Sign it with `sign_manifest()`.
    """
    return ShardManifest(
        corpus_id=corpus_id,
        version=version,
        shards=list(shards),
        signer_pubkey=PA_NODE_PUBKEY,
    )


# --------------------------------------------------------------------------- #
# Sign / verify (INTERFACE REAL, CRYPTO TODO)                                  #
# --------------------------------------------------------------------------- #

def sign_manifest(manifest: ShardManifest, signing_key_path: Optional[str] = None) -> ShardManifest:
    """Sign the canonical payload and return the manifest with `.signature` populated.

    Only the seed operator (Pac's Arcade for `common-knowledge`) runs this. The signature lets
    every leecher verify authenticity without trusting any peer that served the bytes.
    """
    signing_key_path = signing_key_path or PA_MANIFEST_SIGNING_KEY
    payload = canonical_payload(manifest)

    # TODO: load an Ed25519 private key from `signing_key_path` (OS CSPRNG-generated, never in git —
    #       SECURITY.md) and sign `payload`:
    #           from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    #           key = Ed25519PrivateKey.from_private_bytes(_read_key(signing_key_path))
    #           sig = key.sign(payload)
    #           manifest.signature = "ed25519:" + sig.hex()
    #           manifest.signer_pubkey = _pub_hex(key)   # so verifiers can match the trust anchor
    #       Use a vetted crypto lib only — no home-rolled signatures (SECURITY.md).
    _ = payload
    raise NotImplementedError("TODO: Ed25519-sign the manifest with the seed node's key")


def verify_manifest(manifest: ShardManifest, trusted_pubkey: Optional[str] = None) -> bool:
    """True iff `manifest.signature` is a valid signature by `trusted_pubkey` over its payload.

    This is the gate a leecher runs BEFORE trusting any shard hashes into DB-1. For the canonical
    corpus, `trusted_pubkey` is Pac's Arcade's pinned key (`PA_COMMON_KNOWLEDGE_PUBKEY`). A manifest
    signed by anyone else — or with a broken signature — must be rejected, not merely warned about.
    """
    trusted_pubkey = trusted_pubkey or PA_COMMON_KNOWLEDGE_PUBKEY
    if not manifest.signature or not trusted_pubkey:
        return False
    # Refuse a manifest that claims a different signer than the one we pinned. Defense in depth:
    # even if the crypto below had a bug, a mismatched signer never passes.
    if manifest.signer_pubkey and manifest.signer_pubkey != trusted_pubkey:
        return False

    payload = canonical_payload(manifest)

    # TODO: verify the Ed25519 signature over `payload` against `trusted_pubkey`:
    #           from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    #           pub = Ed25519PublicKey.from_public_bytes(_pub_bytes(trusted_pubkey))
    #           alg, _, sig_hex = manifest.signature.partition(":")
    #           pub.verify(bytes.fromhex(sig_hex), payload)   # raises on mismatch → return False
    #       Return True only if verification succeeds; fail CLOSED on any exception.
    _ = payload
    raise NotImplementedError("TODO: Ed25519-verify the manifest against the pinned trust anchor")


# --------------------------------------------------------------------------- #
# Load / dump                                                                  #
# --------------------------------------------------------------------------- #

def to_json(manifest: ShardManifest) -> str:
    """Serialize a (signed) manifest for publishing alongside the torrent / on the swarm."""
    return json.dumps(asdict(manifest), indent=2, sort_keys=True)


def from_json(text: str) -> ShardManifest:
    """Parse a manifest received from a peer. Does NOT verify — call `verify_manifest()` after."""
    raw = json.loads(text)
    shards = [ShardRef(**s) for s in raw.pop("shards", [])]
    return ShardManifest(shards=shards, **raw)


def load_manifest(path: str) -> ShardManifest:
    """Read a manifest file from disk (unverified)."""
    with open(path, "r", encoding="utf-8") as fh:
        return from_json(fh.read())


# --------------------------------------------------------------------------- #
# CLI — mint or check a manifest by hand                                       #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build / sign / verify a corpus shard manifest.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_verify = sub.add_parser("verify", help="Verify a manifest file against the trust anchor.")
    p_verify.add_argument("path", help="path to a manifest.json received from the swarm")
    p_verify.add_argument("--pubkey", default=None, help="trusted signer pubkey (defaults to env)")

    args = parser.parse_args()
    if args.cmd == "verify":
        man = load_manifest(args.path)
        ok = verify_manifest(man, args.pubkey)   # TODO returns once crypto is wired
        print(f"{man.corpus_id}@{man.version}: {'TRUSTED' if ok else 'REJECTED'}")
        raise SystemExit(0 if ok else 1)
