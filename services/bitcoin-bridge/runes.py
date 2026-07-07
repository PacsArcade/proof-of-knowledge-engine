# =============================================================================
# ██  SECURITY-CRITICAL FILE — CLASS-CERTIFICATE RUNES  ██                   💜
# =============================================================================
# READ docs/SECURITY.md AND docs/RUNES.md BEFORE EDITING.
#
# This module etches Bitcoin *runes* and issues them as soulbound class certificates
# (Pac's Arcade "one rune per class / bitcoin POAP-equivalent" model). It moves
# real value on non-regtest networks (etch + issuance pay on-chain fees from the
# non-profit "Arcade Treasury" wallet), so it is REGTEST-ONLY by default and
# REFUSES real-value operations unless deliberately, verifiably unlocked.
#
# It does NOT define its own safety gate. It REUSES the one and only vault guard
# from vault.py — `require_safe_network()` — so there is a single choke point for
# the whole bitcoin-bridge service and NO chance of the two drifting apart. Every
# value operation (etch, issue, reissue) calls `require_safe_network()` FIRST,
# before it touches ord / bitcoin-cli. Do not weaken it, do not add a real-value
# path that skips it. Read-only lookups (verify, list) do not move funds and are
# intentionally NOT gated, exactly like vault.scan_realm_directory().
#
# Soulbound reality check: Bitcoin has NO native soulbound primitive (that needs
# covenants like OP_CTV/OP_CAT, which are not live). We implement soulbound
# **by convention + on-chain provenance**: the verifier trusts a credential only
# for its original earner. A transfer does NOT destroy the earned credit — it
# just makes provenance explicit and lets us re-issue to a safe wallet. See
# docs/RUNES.md for the full model.
# =============================================================================
"""bitcoin-bridge/runes.py — soulbound class-certificate runes. COLD, :8085.

SCAFFOLDING / STUB. The safety guard is REAL and mandatory (reused from vault.py).
The ord / bitcoin-cli bodies are TODOs; the DB shape, the guard calls, and the
rune-naming convention are real.

A class certificate is one *unit* of a per-class rune etched to a student's
wallet when the Oracle confirms mastery (a guardrail-passed competency_node).
Because the issuing transaction naturally records the confirming block (height +
time) and the recipient address, the credential carries — for free, on-chain —
both **when it was earned** and the **original wallet** that earned it. Those two
facts are what make wallet-visibility and compromised-wallet recovery possible.
"""

from __future__ import annotations

import os
import re
from typing import Optional, TypedDict

# --------------------------------------------------------------------------- #
# ██ REUSE THE VAULT'S SAFETY GUARD — do NOT redefine it here ██              #
# --------------------------------------------------------------------------- #
# One guard for the whole bitcoin-bridge service. Importing it (instead of
# copying it) guarantees runes.py and vault.py can never drift out of sync on
# what "safe" means. vault.py is a sibling module in this same directory.
try:
    from vault import (  # type: ignore
        require_safe_network,
        real_value_allowed,
        VaultRefused,
        PA_NETWORK,
    )
except ImportError:  # pragma: no cover - when imported as part of a package
    from .vault import (  # type: ignore
        require_safe_network,
        real_value_allowed,
        VaultRefused,
        PA_NETWORK,
    )


# --------------------------------------------------------------------------- #
# Config (non-secret) — report these env vars to the .env.example owner         #
# --------------------------------------------------------------------------- #
# PA_ORD_URL        — the runes-aware `ord` indexer/server. Runes are invisible
#                     to a plain bitcoin node; ord is what makes them queryable.
# PA_TREASURY_WALLET— the non-profit "Arcade Treasury" wallet (ord/bitcoin-cli
#                     wallet name) that OWNS every class rune and PAYS the etch +
#                     issuance fees. Students never pay to receive a certificate.
# PA_BITCOIN_RPC    — reused from the vault; the regtest bitcoind RPC endpoint.
PA_ORD_URL = os.environ.get("PA_ORD_URL", "http://ord:8080")
PA_TREASURY_WALLET = os.environ.get("PA_TREASURY_WALLET", "arcade-treasury")
PA_BITCOIN_RPC = os.environ.get("PA_BITCOIN_RPC", "http://arcade:change-me@bitcoin:18443")

# Rune names are display-uppercase A-Z with a "spacer" character (•, U+2022) that
# is purely cosmetic — ord stores the letters, the spacer is how a wallet renders
# them. Convention: PACS•<CLASS>, e.g. PACS•BITCOIN•BASICS. One rune per class.
RUNE_SPACER = "•"  # •
RUNE_PREFIX = "PACS"
_RUNE_LETTERS = re.compile(r"[^A-Za-z]+")


# --------------------------------------------------------------------------- #
# The certificate record — the shape verify/list/etch return and the DB mirrors #
# (see infra/postgres/03-class-runes.sql :: class_certificates)                 #
# --------------------------------------------------------------------------- #
class ClassCertificate(TypedDict, total=False):
    class_id: str            # FK -> class_catalog.class_id (the class slug)
    rune_name: str           # PACS•<CLASS> display name
    rune_id: str             # ord rune id "block:tx" (e.g. "101:1"); stable handle
    student_pubkey: str      # learner identity (corresponds to users.pubkey)
    original_wallet: str     # the address the certificate was FIRST etched to (provenance root)
    current_wallet: str      # where the rune unit lives now (differs iff moved)
    competency_ref: str      # pointer to the guardrail-passed competency_node
    mint_txid: str           # the issuing (rune-mint) transaction
    block_height: Optional[int]   # confirming block — set after confirmation
    block_time: Optional[int]     # unix time of that block == "earned at" (from the header)
    soulbound: bool          # always true by convention
    superseded_by: Optional[int]  # id of the reissued cert, if this one was recovered-from
    revoked: bool            # operator revocation (fraud/error), distinct from superseded
    moved: bool              # convenience: current_wallet != original_wallet
    network: str             # regtest | testnet | mainnet (mainnet gated)


# --------------------------------------------------------------------------- #
# Pure helper — the rune naming convention (no value, no guard needed)          #
# --------------------------------------------------------------------------- #
def rune_name_for_class(class_id: str) -> str:
    """Derive the canonical rune name for a class id. Pure; safe to call anywhere.

    'bitcoin-basics' -> 'PACS•BITCOIN•BASICS'. Runes are A-Z only; the spacer (•)
    is display-only. One rune per class, so this mapping must be stable.
    """
    parts = [p for p in _RUNE_LETTERS.split(class_id.upper()) if p]
    if not parts:
        raise ValueError(f"class_id {class_id!r} has no letters to build a rune name from")
    return RUNE_SPACER.join([RUNE_PREFIX, *parts])


def _assert_rune_name(rune_name: str) -> None:
    """Guardrail on the naming convention: must be PACS-prefixed, A-Z + spacer only."""
    letters = rune_name.replace(RUNE_SPACER, "")
    if not rune_name.startswith(RUNE_PREFIX) or not letters.isalpha() or not letters.isupper():
        raise ValueError(
            f"rune_name {rune_name!r} is not a valid class rune "
            f"(expected e.g. 'PACS{RUNE_SPACER}BITCOIN{RUNE_SPACER}BASICS')"
        )


# --------------------------------------------------------------------------- #
# 1. Etch — the Arcade Treasury creates the per-class rune (idempotent)         #
# --------------------------------------------------------------------------- #
def etch_class_rune(class_id: str, rune_name: str) -> dict:
    """Etch ONE rune for a class. Idempotent: re-etching a known class is a no-op
    that returns the existing registry row. Fees paid by the non-profit treasury.

    VALUE OPERATION — gated. The etch transaction pays an on-chain fee from
    PA_TREASURY_WALLET, so the vault guard runs first.

    Flow (regtest + ord):
      1. require_safe_network — refuse unless regtest/testnet (or fully-unlocked mainnet).
      2. Look up class_catalog by class_id. If already etched (etch_txid set), return it.
      3. Build the etch via ord using PA_TREASURY_WALLET (the treasury owns the supply and
         pays the fee). Runestone: rune=rune_name, symbol, divisibility=0 (whole certs),
         premine=0, terms open so the treasury can mint units on demand as students pass.
      4. Record etch_txid + etched_at into class_catalog.
    Returns the class_catalog row.
    """
    require_safe_network("etch_class_rune")
    _assert_rune_name(rune_name)
    # TODO(ord): POST the etch to PA_ORD_URL / `ord wallet etch --rune <rune_name>
    #            --fee-rate ... --divisibility 0 --supply <open>` using PA_TREASURY_WALLET.
    #            Note: pre-`ord`-reservation rules apply to short names on mainnet; regtest
    #            is relaxed. Persist (class_id, title, rune_name, etch_txid, etched_at) into
    #            DB-2 class_catalog (idempotent upsert on class_id).
    raise NotImplementedError("TODO: ord etch of the per-class rune (regtest); idempotent upsert")


# --------------------------------------------------------------------------- #
# 2. Etch — issue 1 unit of the class rune to a student as their certificate    #
# --------------------------------------------------------------------------- #
def etch_class_certificate(class_id: str, student_wallet: str, competency_ref: str) -> ClassCertificate:
    """Etch exactly ONE unit of the class rune to `student_wallet` — the student's
    class certificate. Called when the Oracle confirms mastery (a guardrail-passed
    competency_node). Fees paid by the Arcade Treasury.

    VALUE OPERATION — gated. Issuance broadcasts a funded transaction.

    Flow (regtest + ord):
      1. require_safe_network — refuse under an unsafe posture.
      2. Resolve the class rune from class_catalog (etch it first if missing — one rune/class).
      3. `ord wallet mint --rune <rune_name>` for amount=1, recipient=student_wallet, paid by
         PA_TREASURY_WALLET; capture mint_txid immediately.
      4. AFTER the tx confirms, read the confirming block from ord/bitcoin-cli and record:
           - block_height, block_time  (block_time == "earned at", straight from the header)
           - original_wallet = student_wallet  (the provenance root; never changes)
           - current_wallet  = student_wallet  (equal at issuance; diverges only if moved)
      5. INSERT into DB-2 class_certificates (soulbound=true, network=PA_NETWORK).
    Returns the certificate record. `original_wallet` + `block_time` are the two facts that
    make wallet-visibility and compromised-wallet recovery work — both come free from the tx.
    """
    require_safe_network("etch_class_certificate")
    if not student_wallet:
        raise ValueError("student_wallet is required to etch a certificate")
    # TODO(ord): resolve/etch rune for class_id; `ord wallet mint` amount=1 to student_wallet
    #            funded by PA_TREASURY_WALLET; capture mint_txid; wait for 1 confirmation; read
    #            confirming block height+time; INSERT class_certificates(..., original_wallet=
    #            student_wallet, current_wallet=student_wallet, soulbound=true, network=PA_NETWORK).
    raise NotImplementedError("TODO: ord mint 1 unit to student + record on-chain provenance")


# --------------------------------------------------------------------------- #
# 3. Verify — the soulbound check (READ-ONLY, not gated — no funds move)        #
# --------------------------------------------------------------------------- #
def verify_certificate(rune_id: str, wallet: str) -> dict:
    """Soulbound verification. A certificate is VALID for the wallet that EARNED it.

    READ-ONLY — no funds move, so (like vault.scan_realm_directory) this is NOT gated;
    verification must work on any node, even one that would refuse to issue.

    Rules (soulbound-by-convention + provenance):
      - valid  == (wallet == original_wallet), OR wallet is a treasury-attested reissue target
        whose provenance traces back to original_wallet (see reissue_certificate).
      - moved  == (current_wallet != original_wallet). A move does NOT invalidate the credit;
        it only sets moved=true so the provenance is explicit. The earned fact is immutable —
        it happened at block_time, to original_wallet, and no later transfer rewrites history.
      - revoked/superseded certs report valid=false with the reason.
    Returns e.g. {valid, moved, reason, original_wallet, current_wallet, block_time, superseded_by}.
    """
    # TODO(ord): fetch the rune unit's current holder + its class_certificates row by rune_id;
    #            compare wallet against original_wallet (and any reissue chain); compute moved;
    #            surface revoked/superseded. Pure read; do NOT gate. No treasury funds involved.
    raise NotImplementedError("TODO: soulbound verification against on-chain + class_certificates")


# --------------------------------------------------------------------------- #
# 4. Reissue — compromised-wallet recovery (VALUE OP — gated)                   #
# --------------------------------------------------------------------------- #
def reissue_certificate(rune_id: str, new_wallet: str, proof: str) -> ClassCertificate:
    """Recover a certificate to a NEW wallet when the original is compromised/lost.

    The whole reason runes work here: the earned credit lives on-chain (original_wallet +
    block_time), so losing the wallet does NOT lose the education. The treasury re-issues /
    re-attributes to `new_wallet`, explicitly CITING the original provenance. The old record
    is marked SUPERSEDED, never destroyed — history is preserved, credit is portable.

    VALUE OPERATION — gated. Re-issuance broadcasts a funded transaction.

    Flow:
      1. require_safe_network — refuse under an unsafe posture.
      2. Load the original class_certificates row by rune_id; establish original_wallet + block_time.
      3. Verify `proof` — the operator/Oracle's attestation that new_wallet belongs to the same
         learner (e.g. re-passed identity check, signed statement). Do NOT reissue on unproven claims.
      4. `ord wallet mint` 1 unit to new_wallet from PA_TREASURY_WALLET; capture new mint_txid + block.
      5. INSERT the new cert (original_wallet carried forward = the ORIGINAL earner's address; a
         `reissued_from`/provenance link cites the old rune_id) and set superseded_by on the old row.
         The old cert stays valid-as-history (superseded, not revoked).
    Returns the new certificate record.
    """
    require_safe_network("reissue_certificate")
    if not new_wallet:
        raise ValueError("new_wallet is required to reissue a certificate")
    if not proof:
        # Recovery must be attested — never re-attribute a credential on an unproven claim.
        raise ValueError("reissue requires proof the new_wallet belongs to the original earner")
    # TODO(ord): validate proof; re-issue 1 unit to new_wallet from PA_TREASURY_WALLET; carry
    #            original_wallet + block_time forward; mark the prior row superseded_by=<new id>.
    raise NotImplementedError("TODO: attested re-issue to new wallet, supersede-not-destroy the old")


# --------------------------------------------------------------------------- #
# 5. List — what a wallet displays (READ-ONLY, not gated)                       #
# --------------------------------------------------------------------------- #
def list_wallet_certificates(wallet: str) -> list[ClassCertificate]:
    """List the class certificates a wallet displays. READ-ONLY — not gated.

    Each entry surfaces exactly what the student sees in their wallet:
      - class (class_id + title) and rune_name
      - block_time_earned  (when they earned it — from the confirming block header)
      - original_wallet    (who earned it — provenance root)
      - moved?             (current_wallet != original_wallet)
    Includes reissued certs (as the live ones) and marks superseded/revoked entries so a
    student can always see their full, honest history.
    """
    # TODO(ord): query PA_ORD_URL for rune balances held by `wallet`, join class_certificates
    #            by rune_id to enrich with class/title/block_time/original_wallet/moved. Pure read.
    raise NotImplementedError("TODO: join ord holdings with class_certificates for wallet display")


if __name__ == "__main__":
    # Read-only status line — mirrors vault.py. No value op runs here.
    print(f"[runes] PA_NETWORK={PA_NETWORK} real_value_allowed={real_value_allowed()} "
          f"ord={PA_ORD_URL} treasury={PA_TREASURY_WALLET!r}")
    print(f"[runes] example rune name: {rune_name_for_class('bitcoin-basics')}")
    raise SystemExit("TODO: wire a regtest-only CLI/self-test for class runes (etch→issue→verify)")
