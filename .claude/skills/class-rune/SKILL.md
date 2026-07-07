---
name: class-rune
description: Mint a class-certificate rune when a student completes a class — a soulbound, non-transferable Bitcoin credential (one rune per class, bitcoin POAP-equivalent). Use to mint a class certificate rune, prove class completion, verify a soulbound credential, or recover compromised education certs by re-issuing to a new wallet. Regtest-only by default; etch fees paid by the non-profit Arcade Treasury. Complements issue-node-cert (which certifies OPERATORS) — this one is for STUDENT class completion.
---

# Class-Rune 🎓⛓️ — soulbound class certificates on Bitcoin

When a *fren* completes a class — the Oracle runs the Socratic interview, scores mastery, and
writes a **guardrail-passed `competency_node`** — the node mints them a **class certificate as a
Bitcoin rune**. One rune per class (Pac's Arcade "bitcoin POAP-equivalent" model). It lives in the
student's own wallet, forever, as proof they did the work. 💜

> Complements **`issue-node-cert`**, which certifies the *operator* who stands up a Verse
> (self-signed identity). **This** skill is for the *student* who finishes a class. Different
> earner, different credential.

> **REGTEST BY DEFAULT. READ `docs/RUNES.md` and `docs/SECURITY.md` first.** Runes need a
> runes-aware indexer (`ord`); assume regtest + ord for dev.

## The soulbound reality (say it plainly)

Bitcoin has **no native soulbound primitive** — true non-transferability needs covenants
(OP_CTV / OP_CAT) that are not live. So we do **soulbound-by-convention + on-chain provenance**:

- The **verifier** trusts a certificate only for the wallet that **earned** it.
- A transfer does **not** destroy the credit. It just makes provenance explicit: the cert is
  flagged `moved`, but the earned fact — *this wallet, at this block time* — is immutable on-chain.
- That same immutability is what powers **recovery**: lose your wallet, keep your education.

## The regtest gate (non-negotiable)

All value operations (etch, mint, reissue) go through `services/bitcoin-bridge/runes.py`, which
**reuses the vault's guard** — `require_safe_network()` from `vault.py`. One guard for the whole
bitcoin-bridge service, so nothing drifts. It **refuses** real-value ops unless:

- `PA_NETWORK` is `regtest` or `testnet`, **OR**
- `PA_NETWORK=mainnet` **AND** `PA_MAINNET_ACK=true` **AND** `PA_SEED_LOOT_ENABLED=true`
  (and a passing `security-auditor` review — see `docs/SECURITY.md`).

Read-only ops (`verify`, `list`) move no funds and are intentionally **not** gated — a certificate
must be verifiable on any node. Never invent a mainnet path that skips the guard.

## Env it uses (regtest + ord)

- `PA_ORD_URL` — the `ord` indexer/server (runes are invisible to a plain node; ord makes them queryable).
- `PA_TREASURY_WALLET` — the non-profit **Arcade Treasury** wallet that OWNS every class rune and
  **pays the etch + mint fees**. Students never pay to receive a certificate.
- `PA_BITCOIN_RPC` — the regtest bitcoind RPC (reused from the vault).
- Certificates are recorded in DB-2 `class_catalog` + `class_certificates` (`infra/postgres/03-class-runes.sql`).

## Lifecycle: etch → mint → provenance → verify → reissue

1. **Etch** (once per class, idempotent) — `etch_class_rune(class_id, rune_name)`. The Treasury
   etches ONE rune per class. Naming convention **`PACS•<CLASS>`** (e.g. `PACS•BITCOIN•BASICS`);
   the `•` is a display spacer, ord stores the A-Z letters. Fees from the non-profit wallet.
2. **Mint** — `mint_class_certificate(class_id, student_wallet, competency_ref)`. Only after a
   guardrail-passed `competency_node`. Mints **1 unit** of the class rune to the student's wallet;
   captures `mint_txid`; after confirmation records `block_height`, `block_time`, `original_wallet`.
3. **Provenance comes free.** The mint tx *naturally* records the **recipient address**
   (`original_wallet`) and the **confirming block** (`block_height` + `block_time`). Those two
   facts — *who earned it* and *when* — are exactly what the wallet shows and what recovery needs.
4. **Verify** — `verify_certificate(rune_id, wallet)`. Valid iff `wallet == original_wallet` (or a
   treasury-attested reissue tracing back to it). `moved = current_wallet != original_wallet`; a
   move flags provenance but preserves credit. Read-only; not gated.
5. **Reissue** (compromised-wallet recovery) — `reissue_certificate(rune_id, new_wallet, proof)`.
   Re-mints/re-attributes to `new_wallet`, **citing the original provenance**, and marks the old
   row `superseded_by` — **superseded, never destroyed**. Requires `proof` the new wallet belongs
   to the original earner; never reissue on an unproven claim.

## What the student's wallet shows

`list_wallet_certificates(wallet)` returns, per certificate:

- **class** (class_id + title) and **rune** (`PACS•<CLASS>`)
- **block_time earned** — when they earned it (from the confirming block header)
- **original_wallet** — who earned it (the provenance root)
- **moved?** — whether the rune has left its original wallet

## Compromised-wallet recovery (the reason this is on-chain)

A student's wallet gets compromised, or they simply move the rune. **They do not lose their
education.** Because `original_wallet` + `block_time` are on-chain, the node verifies the original
provenance and re-issues to a fresh, safe wallet:

1. Confirm identity → produce `proof` (re-passed check / signed attestation from the Oracle/operator).
2. `reissue_certificate(rune_id, new_wallet, proof)` — Treasury re-mints 1 unit to `new_wallet`.
3. Original provenance is carried forward; the old cert is marked superseded (kept as history).

The credit is portable; the history is honest. That's the whole point. 💜

## Rules

- Regtest by default; mainnet obeys `docs/SECURITY.md`. Never weaken or bypass the vault guard.
- Etch/mint fees are paid by the **non-profit Arcade Treasury** — students pay nothing.
- One rune per class; one live certificate per (student, class). Recovery supersedes, never deletes.
- Soulbound is enforced by the **verifier**, not the chain — be honest that a transfer is possible
  and that we handle it with provenance, not by pretending it can't happen.
