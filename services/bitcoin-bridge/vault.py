# =============================================================================
# ██  SECURITY-CRITICAL FILE — THE VAULT  ██                                💜
# =============================================================================
# READ docs/SECURITY.md BEFORE EDITING.
#
# This file handles seed material and real-value bitcoin operations. It is
# REGTEST-ONLY by default and REFUSES to do anything with real value unless it
# is explicitly, deliberately unlocked. The guard below is the FIRST thing in
# the file on purpose — nothing real-value runs before it. Do not move it, do
# not weaken it, do not add a real-value code path that bypasses `require_safe_network()`.
#
# Two invariants that must never be broken:
#   1. The full 24-word seed phrase is NEVER stored in one place. It exists only
#      as Shamir's Secret Sharing shares, scattered as loot. Recombine transiently,
#      never persist the whole phrase, never log it, never write it to DB.
#   2. Default network posture is REFUSE. Real value requires regtest/testnet, OR
#      an explicit mainnet acknowledgement AND the seed-loot opt-in (AND a passing
#      security-auditor review — see docs/SECURITY.md).
# =============================================================================
"""bitcoin-bridge/vault.py — SSS seed loot, tipping, OP_RETURN discovery. COLD, :8085.

SCAFFOLDING / STUB. The safety guard is REAL and mandatory. The crypto/RPC bodies are TODOs.
"""

from __future__ import annotations

import os
from enum import Enum


# --------------------------------------------------------------------------- #
# ██ HARD SAFETY GUARD — evaluated at import, enforced on every real-value op ██
# --------------------------------------------------------------------------- #

class Network(str, Enum):
    REGTEST = "regtest"
    TESTNET = "testnet"
    MAINNET = "mainnet"


PA_NETWORK = os.environ.get("PA_NETWORK", "regtest").strip().lower()
PA_MAINNET_ACK = os.environ.get("PA_MAINNET_ACK", "false").strip().lower() == "true"
PA_SEED_LOOT_ENABLED = os.environ.get("PA_SEED_LOOT_ENABLED", "false").strip().lower() == "true"


class VaultRefused(RuntimeError):
    """Raised whenever a real-value operation is attempted under an unsafe posture."""


def real_value_allowed() -> bool:
    """True only if it is safe to perform a real-value bitcoin operation.

    SAFE when:
      - PA_NETWORK is regtest or testnet (no real value at stake), OR
      - PA_NETWORK is mainnet AND PA_MAINNET_ACK is true AND PA_SEED_LOOT_ENABLED is true.
    Anything else → NOT safe. Default posture is refuse.

    NOTE: even the mainnet override still requires a passing security-auditor review per
    docs/SECURITY.md — this function is a floor, not a green light on its own.
    """
    if PA_NETWORK in (Network.REGTEST.value, Network.TESTNET.value):
        return True
    if PA_NETWORK == Network.MAINNET.value and PA_MAINNET_ACK and PA_SEED_LOOT_ENABLED:
        return True
    return False


def require_safe_network(operation: str) -> None:
    """Gate a real-value operation. Call this FIRST inside every such function.

    Refuses loudly (VaultRefused) unless real_value_allowed(). This is the choke point that
    keeps the Vault regtest-only until the operator has deliberately, verifiably opted in.
    """
    if not real_value_allowed():
        raise VaultRefused(
            f"Refusing '{operation}': unsafe network posture. "
            f"PA_NETWORK={PA_NETWORK!r}, PA_MAINNET_ACK={PA_MAINNET_ACK}, "
            f"PA_SEED_LOOT_ENABLED={PA_SEED_LOOT_ENABLED}. "
            "The Vault is regtest-only by default; mainnet requires an explicit ack, the "
            "seed-loot opt-in, AND a passing security-auditor review (docs/SECURITY.md). "
            "Not today, fren. 💜"
        )


# Fail fast, visibly, at import time if someone points this at mainnet unsafely.
if PA_NETWORK == Network.MAINNET.value and not real_value_allowed():
    # We don't raise at import (the module may be imported for read-only helpers), but we make
    # the posture unmistakable. Every real-value function still calls require_safe_network().
    import warnings
    warnings.warn(
        "vault.py imported with PA_NETWORK=mainnet but the mainnet safety conditions are NOT "
        "met — ALL real-value operations will be REFUSED. See docs/SECURITY.md.",
        stacklevel=2,
    )


# --------------------------------------------------------------------------- #
# Config (non-secret)                                                         #
# --------------------------------------------------------------------------- #

PA_BITCOIN_RPC = os.environ.get("PA_BITCOIN_RPC", "http://arcade:change-me@bitcoin:18443")
PA_NODE_PUBKEY = os.environ.get("PA_NODE_PUBKEY", "")
PA_MATRIX_SERVER_NAME = os.environ.get("PA_MATRIX_SERVER_NAME", "verse.local")
BRIDGE_PORT = 8085

# SSS defaults: split into N shares, need K to recombine. Tune per quest design.
SSS_TOTAL_SHARES = 5
SSS_THRESHOLD = 3


# --------------------------------------------------------------------------- #
# 1. Seed loot — Shamir's Secret Sharing (regtest)                            #
# --------------------------------------------------------------------------- #

def split_seed_into_shares(seed_phrase: str,
                           total: int = SSS_TOTAL_SHARES,
                           threshold: int = SSS_THRESHOLD) -> list[str]:
    """Split a 24-word seed into `total` SSS shares (need `threshold` to recombine).

    INVARIANT: the returned shares are the ONLY persisted representation. The caller scatters
    them as loot; the full phrase must be discarded from memory immediately and never stored
    whole, logged, or written to any DB.
    """
    require_safe_network("split_seed_into_shares")
    # TODO: use SLIP-39 (shamir-mnemonic) to produce `total` shares with `threshold` recovery.
    #       Zeroize the seed_phrase buffer after splitting. Never return or log the phrase.
    raise NotImplementedError("TODO: SLIP-39 / Shamir split (regtest)")


def combine_shares(shares: list[str]) -> str:
    """Transiently recombine >= threshold shares back into the seed. Never persist the result.

    The recombined phrase lives only long enough to derive/sign, then is zeroized. It is never
    written anywhere. This is the ONLY moment the whole phrase exists, and only in memory.
    """
    require_safe_network("combine_shares")
    # TODO: SLIP-39 combine; hand the transient seed to the signer, then zeroize. Never log it.
    raise NotImplementedError("TODO: SLIP-39 / Shamir combine (regtest, transient)")


# --------------------------------------------------------------------------- #
# 2. Tipping — Lightning / regtest                                            #
# --------------------------------------------------------------------------- #

async def tip_operator(amount_sats: int, memo: str = "gg's, fren 💜") -> dict:
    """Send a Lightning (regtest) tip to the node operator."""
    require_safe_network("tip_operator")
    # TODO: create/pay a BOLT11 invoice via the node's LN backend (regtest). Return payment info.
    raise NotImplementedError("TODO: Lightning/regtest tipping")


# --------------------------------------------------------------------------- #
# 3. Discovery — OP_RETURN announce + scan                                    #
# --------------------------------------------------------------------------- #

async def announce_node() -> str:
    """Publish this node's pubkey + Matrix address on-chain via OP_RETURN. Returns the txid.

    This is how a federated verse advertises itself. Real value (a funded tx) is required to
    write to the chain, so it is guarded — regtest by default.
    """
    require_safe_network("announce_node")
    # TODO: build an OP_RETURN tx encoding (PA_NODE_PUBKEY, PA_MATRIX_SERVER_NAME); broadcast
    #       via PA_BITCOIN_RPC. Keep the payload tiny and clearly namespaced.
    raise NotImplementedError("TODO: OP_RETURN announce")


async def scan_realm_directory(from_height: int = 0) -> list[dict]:
    """Scan the chain for other nodes' OP_RETURN announcements → realm directory entries.

    READ-ONLY (no funds move), so it is NOT gated by require_safe_network — discovery scanning
    is always allowed, even on a read-only/regtest node.
    """
    # TODO: scan blocks >= from_height via PA_BITCOIN_RPC for our OP_RETURN namespace; decode
    #       (pubkey, matrix_address) pairs; return them for the realm directory. No guard needed.
    raise NotImplementedError("TODO: OP_RETURN scan → realm directory")


if __name__ == "__main__":
    # TODO: argparse; `--selftest` should run SSS split/combine round-trip on regtest ONLY.
    print(f"[vault] PA_NETWORK={PA_NETWORK} real_value_allowed={real_value_allowed()}")
    raise SystemExit("TODO: wire a regtest-only CLI/self-test for the Vault")
