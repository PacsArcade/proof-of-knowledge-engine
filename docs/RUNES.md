# RUNES — soulbound class certificates on Bitcoin 🎓⛓️

> When a *fren* completes a class, we mint them a **class certificate as a Bitcoin rune**. It lives
> in their own wallet, shows *when* they earned it and *which wallet* earned it, and — because that
> lives on-chain — it survives a lost or compromised wallet. One rune per class; the bitcoin
> POAP-equivalent of Pac's Arcade. 💜

See `docs/ARCHITECTURE.md` for the whole system and `docs/CONVENTIONS.md` for the service/port/tier
contract. This doc explains the *why* and the *safety* of the class-rune credential.

- **Code:** `services/bitcoin-bridge/runes.py` (COLD tier, part of `bitcoin-bridge` :8085)
- **Schema:** `infra/postgres/03-class-runes.sql` (DB-2 `class_catalog`, `class_certificates`)
- **Skill:** `.claude/skills/class-rune/SKILL.md`
- **Money gate:** `docs/SECURITY.md` (this feature reuses the vault's guard — see below)

## Why runes for certificates

A certificate should be **the student's**, portable, and verifiable without asking us for
permission. Runes (Bitcoin's fungible-token protocol, indexed by `ord`) give us exactly that:

- The credential lives in the **student's own wallet**, not our database.
- The **mint transaction records the earn — for free**: the recipient address (the *original
  wallet*) and the confirming block (its *height* and *time*). No extra bookkeeping to prove who
  earned what, and when.
- It fits the Arcade model precisely: **one rune per class**, one unit minted per graduate — a
  bitcoin-native POAP that says "this fren completed *this* class."

## The soulbound model — by convention + provenance

We want these credentials **soulbound / non-transferable**: a certificate should mean *you* did the
work, not *someone who bought your token*.

### The honest Bitcoin caveat

**Bitcoin has no native soulbound primitive.** True non-transferability needs covenant opcodes
(**OP_CTV / OP_CAT**) that are **not live** on the network. Anyone who tells you a plain rune is
"unmovable" is wrong. We do not pretend otherwise.

### What we actually do

**Soulbound-by-convention + on-chain provenance**, enforced by the **verifier**, not the chain:

- A certificate is **valid only for the wallet that earned it** (`original_wallet`), or for a
  treasury-attested reissue whose provenance traces back to it.
- A transfer does **not** destroy the credit. The rune *can* move (it's a normal UTXO); if it does,
  the verifier flags the certificate **`moved`** (`current_wallet != original_wallet`) — but the
  **earned fact is immutable**: it happened at `block_time`, to `original_wallet`, and no later
  transfer can rewrite that history.
- So "someone bought the rune" buys nothing: the verifier still attributes the achievement to the
  original earner, and the buyer's wallet fails verification.

This is deliberately the *opposite* of a bearer instrument. The value isn't the token — it's the
provenance the token points at.

## Provenance comes free from the mint tx

Two facts we need for both wallet-visibility and recovery are recorded by the mint transaction
itself — we don't invent them:

| Fact | Where it comes from | Column |
|------|--------------------|--------|
| **When earned** | the confirming block's header time | `class_certificates.block_time` |
| **Original wallet** | the mint tx's recipient address | `class_certificates.original_wallet` |
| Confirming block | the block that mined the mint | `class_certificates.block_height` |
| Which class | the rune etched for that class | `class_catalog.rune_name` (`PACS•<CLASS>`) |

## What the student's wallet shows

`list_wallet_certificates(wallet)` returns, for each certificate:

- **class** (id + title) and **rune** — `PACS•<CLASS>` (e.g. `PACS•BITCOIN•BASICS`; the `•` is a
  display spacer, `ord` stores the A-Z letters)
- **block time earned** — the moment it was mined, from the confirming block
- **original wallet** — the provenance root, who earned it
- **moved?** — whether the rune has left its original wallet

## Compromised-wallet recovery (the payoff)

This is *why* we anchor to the chain. A student's wallet gets compromised, or they just move the
rune — **they do not lose their education.**

Because `original_wallet` + `block_time` are on-chain, the node can prove the original provenance
and re-issue to a fresh, safe wallet:

1. **Prove identity** → produce `proof` (a re-passed identity check or a signed attestation from
   the Oracle/operator that the new wallet belongs to the same learner). No proof, no reissue.
2. **`reissue_certificate(rune_id, new_wallet, proof)`** → the Arcade Treasury re-mints 1 unit to
   `new_wallet`, carrying the **original** provenance forward.
3. **Supersede, don't destroy** → the old certificate row is marked `superseded_by` the new one and
   kept as history. Nothing is deleted; the credit is portable and the record is honest.

## Etch, mint, and who pays

- **Etch** (once per class, idempotent): the **Arcade Treasury** — the non-profit's wallet
  (`PA_TREASURY_WALLET`) — etches ONE rune per class and **pays the etch fee**.
- **Mint** (per graduate): the Treasury mints 1 unit to the student and **pays the mint fee**.
  **Students never pay to receive a certificate.** Fees are a cost the non-profit absorbs so the
  credential is free to earn.
- **Naming:** `PACS•<CLASS>`. One rune per class, stable mapping (`runes.py::rune_name_for_class`).

## Dev setup: regtest + ord

Runes are **invisible to a plain Bitcoin node** — they need a runes-aware indexer. For dev we
assume **regtest + `ord`**:

- `PA_NETWORK=regtest` (default — play money, zero real risk; regtest name rules are relaxed).
- `PA_ORD_URL` — the `ord` server/indexer that etches, mints, and answers rune queries.
- `PA_TREASURY_WALLET` — the ord/bitcoin-cli wallet that owns the runes and pays fees.
- `PA_BITCOIN_RPC` — the regtest bitcoind RPC (reused from the vault).

`etch → mint → verify → reissue` all run against regtest + ord in dev.

## The mainnet gate (safety is paramount)

Class runes move real value on non-regtest networks (etch + mint pay on-chain fees), so
`runes.py` **reuses the vault's single safety guard** — `require_safe_network()` from
`services/bitcoin-bridge/vault.py`. It is **not** a second, drifting copy; it's the same choke
point the seed-loot vault uses. Every value operation (etch, mint, reissue) calls it **first**.

Real-value operations are **refused** unless:

- `PA_NETWORK` is `regtest` or `testnet`, **OR**
- `PA_NETWORK=mainnet` **AND** `PA_MAINNET_ACK=true` **AND** `PA_SEED_LOOT_ENABLED=true` — **and**
  a passing `security-auditor` review, per **`docs/SECURITY.md`**.

Read-only operations (`verify_certificate`, `list_wallet_certificates`) move no funds and are
intentionally **not** gated — a certificate must be verifiable on any node, even one that would
refuse to mint. There is **no** unguarded mainnet mint path, by design. Legal implications of
issuing on-chain credentials from a non-profit are flagged for Pac + counsel in `docs/SECURITY.md`
before any mainnet flip.
