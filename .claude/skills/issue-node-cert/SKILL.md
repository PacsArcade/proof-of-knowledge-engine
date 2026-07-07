---
name: issue-node-cert
description: Mint a "Certified Education Node" credential for a server operator who has stood up a healthy Verse and passed the operator quiz. Use at the end of node-wizard onboarding, or when an operator asks to (re)issue their node certificate or publish their Verse to the federated map. Signs the credential with the node's own key and optionally publishes it as a nostr badge and/or an OP_RETURN discovery announce.
---

# Issue Node Certificate 🎓

A **Certified Education Node** credential is proof that a *fren* stood up a real Verse and
knows their subject. It is self-sovereign: signed by the node's **own** key — there is no
central authority handing out blessings. It doubles as the node's entry on the federated
discovery map.

## Preconditions (do not skip)
1. **The node is healthy** — `scripts/bootstrap.sh` reports state-sync, MUD, inference,
   guardrail, and Matrix all up. A certificate for a broken node helps nobody.
2. **The operator passed the expertise quiz** in `node-wizard` — a certified operator can
   teach their declared subject. This is proof of *play*, arcade-style: you earn the badge.

## What the certificate contains
```json
{
  "type": "pacs-arcade/certified-education-node",
  "node_name": "<PA_NODE_NAME>",
  "node_pubkey": "<PA_NODE_PUBKEY>",
  "operator_subject": "<what they teach>",
  "matrix_server": "<PA_MATRIX_SERVER_NAME>",
  "corpus": "<PA_CORPUS>",
  "network": "<PA_NETWORK>",
  "issued_at": "<iso8601>",
  "issued_by": "self",
  "signature": "<node-key signature over the above>"
}
```

## Steps
1. Ensure the node identity exists — `PA_NODE_PUBKEY` in `.env`. If missing, generate the
   node keypair (this is also the discovery key) via `scripts/issue-cert.sh` and write the
   pubkey back to `.env`. Keep the private half out of git (see `.gitignore`).
2. Run `scripts/issue-cert.sh` to assemble the JSON above and **sign it with the node key**.
   Write the public certificate to `certs/<node_name>.cert.json` and keep the private material
   in `certs/<node_name>.private.json` (git-ignored).
3. **Optional publications** (ask the operator; both are COLD-tier and opt-in):
   - **nostr badge** — publish as a NIP-58 badge event so it shows on nostr clients. This lines
     up with Pac's Arcade "one rune per class / proof-of-play" credential model.
   - **OP_RETURN discovery** — announce `node_pubkey + matrix_server` to the chain (regtest by
     default) so other Verses scanning the ledger add this node to their in-game realm directory.
     Route this through `services/bitcoin-bridge`; it obeys the same regtest/mainnet gate.
4. Present the credential to the operator warmly — they're on the map now. 💜

## Rules
- Self-signed by design. Never introduce a central issuing authority.
- The private key never leaves the box and never enters git.
- On-chain announce defaults to **regtest**; mainnet obeys `docs/SECURITY.md`.
- Re-issue is fine (config changed, key rotated) — supersede the old cert, keep the same pubkey
  unless the operator is deliberately rotating identity.
