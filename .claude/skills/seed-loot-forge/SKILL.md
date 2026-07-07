---
name: seed-loot-forge
description: Design and wire the Bitcoin seed-phrase-as-loot reward mechanic — splitting a 24-word seed with Shamir's Secret Sharing, scattering shares as high-tier loot behind knowledge checks, and the "teach to mint the 24th word" twist. SAFETY-CRITICAL and REGTEST-ONLY by default. Use when building or changing any seed-loot, reward, or vault behavior. Always coordinate with the security-auditor.
---

# Seed-Loot Forge ⛓️🗝️

The headline reward: complete real educational milestones and you earn fragments of a **real
Bitcoin wallet**. It is thrilling *because* the stakes are real — which is exactly why we build
it with both hands on the wheel.

> **READ `docs/SECURITY.md` FIRST. This mechanic can destroy real money if done wrong.**

## Hard rules (non-negotiable)
1. **Regtest is the default. Testnet is opt-in. Mainnet is GATED** behind BOTH
   `PA_MAINNET_ACK=true` AND a passing `security-auditor` review. `services/bitcoin-bridge/vault.py`
   refuses real-value operations otherwise, and that guard is the first code in the file.
2. **`PA_SEED_LOOT_ENABLED=false` by default.** The operator opts in deliberately.
3. **Never store the full 24-word phrase in one place, ever.** That is the whole design.

## The mechanic
- **Shamir's Secret Sharing:** split the seed into shares with a threshold (e.g. **15 of 24**),
  so a player reconstructs the wallet only after collecting enough — redundancy plus difficulty.
- **Loot placement:** each share/word is a drop from a "Boss" that is really a **final exam** in
  a subject (the Calculus Golem drops word #4). Getting a word *requires proving domain knowledge*.
  Placement lives in DB-2 `seed_fragments` (fragment_index, item_id, sss_share_ref, network,
  minted, holder). Guardrail must pass before a fragment mints (see `hallucination-guardrail`).
- **The 24th-word twist:** the final word / checksum only mints when the player **teaches** the
  concept to an NPC or another fren — verifying true understanding, and blocking brute-force.

## Player safety (consequences, not prohibitions)
- Teach plainly: the word is written on an in-game **scroll** — lose the scroll, lose the sats.
  This is the Zelda-chest lesson: the seed phrase *is* the treasure, guard it like one. 💜
- Offer **"Bank Vault" NPCs** — secure storage requiring multi-factor access.
- Route all of this through `services/bitcoin-bridge`; defer key handling to the Custodian.

## Before you ship anything here
Invoke the **security-auditor** skill and get sign-off. Do not self-approve a value path.
Prove the mainnet guard is un-bypassable (grep every path that can move funds).
