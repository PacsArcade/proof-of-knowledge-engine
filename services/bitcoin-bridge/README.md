# bitcoin-bridge — the Vault: SSS seed loot, tipping, OP_RETURN discovery 💜

> Part of **Pac's Arcade — Proof of Knowledge Engine (P.O.K.E.)**.
> See the canonical contract in [`docs/CONVENTIONS.md`](../../docs/CONVENTIONS.md)
> and **`docs/SECURITY.md`** before touching anything here.

## Role

`bitcoin-bridge` is **the Vault** — the node's bitcoin surface. It backs the **Custodian** agent
and does three jobs:

1. **Seed-loot (Shamir's Secret Sharing).** Split a 24-word seed into SSS shares scattered as
   loot across the world; recombine transiently when enough shares are recovered. **The full
   phrase is never stored in one place, ever.**
2. **Tipping.** Lightning / regtest tips to a node operator.
3. **Discovery via OP_RETURN.** Announce this node's pubkey + Matrix address to the chain, and
   scan the chain to populate the realm directory (how federated verses find each other).

## ⚠️⚠️ MONEY SAFETY — read this first

**Regtest is the default and the Vault refuses real-value operations by default.** The very first
thing in `vault.py` is a hard guard that **refuses** any real-value op unless:

- `PA_NETWORK` is `regtest` or `testnet`, **OR**
- `PA_MAINNET_ACK=true` **AND** `PA_SEED_LOOT_ENABLED=true` (and a passing `security-auditor`
  review — see `docs/SECURITY.md`).

Default posture is **refuse**. The Custodian mirrors this: regtest-only until security sign-off.

## Tier

**COLD.** On-chain and Lightning operations are async, network-crossing, and never on a gameplay
hot path.

## Port

**8085** (docker-compose service name: `bitcoin-bridge`). Talks to the `bitcoin` node at
`PA_BITCOIN_RPC` (regtest RPC `:18443`).

## How it fits the whole

```
 Custodian ──► bitcoin-bridge (COLD, GUARDED) ──► bitcoin node (regtest :18443)
                     ├── SSS split/combine (shares scattered as loot; phrase never whole)
                     ├── Lightning/regtest tipping
                     └── OP_RETURN announce + scan ──► realm directory (federation discovery)
```

## How to run it

```bash
docker compose up bitcoin-bridge
# or, local dev (regtest only!):
cd services/bitcoin-bridge
pip install shamir-mnemonic python-bitcoinlib httpx   # TODO: pin in requirements.txt
PA_NETWORK=regtest python vault.py --selftest          # TODO: add a regtest self-test
```

Required env: `PA_NETWORK`, `PA_MAINNET_ACK`, `PA_SEED_LOOT_ENABLED`, `PA_BITCOIN_RPC`,
`PA_NODE_PUBKEY`, `PA_MATRIX_SERVER_NAME`.

> ⚠️ **Scaffolding.** `vault.py` is a commented stub. The regtest safety guard at the top is
> **real and mandatory**; the SSS/tipping/OP_RETURN bodies are `TODO`s.
