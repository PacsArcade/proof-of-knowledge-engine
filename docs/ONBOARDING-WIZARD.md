# ONBOARDING WIZARD — from bare metal to a Certified Education Node

The onboarding wizard is a **conversation**, run by the `node-wizard` skill (with `scripts/
node-doctor.sh` for hardware facts and `scripts/issue-cert.sh` for the credential). It turns a
fresh Arch box into a live, federated education Verse — and hands the operator a certificate at
the end. This doc is the reference spec; the skill is the runnable persona.

## Who runs it
A **server operator** ("a fren") standing up their own Verse. They may be an expert teacher who's
never touched Docker, or a sysadmin who's never taught. The wizard meets either where they are.

## The seven beats

1. **Read the machine.** `node-doctor.sh` reports distro, CPU, RAM, GPU + VRAM, disk, virtualization,
   and whether Docker/NVIDIA drivers exist. The wizard reflects it back in plain language and flags
   problems early (low disk for the corpus, no GPU, missing drivers).

2. **Quiz the operator.** Conversationally, one question at a time:
   - *What do you want to teach?* → seeds their curriculum fork + the curated-corpus option, and is
     how they **earn the certificate** (a certified operator knows their subject).
   - *How many frens at once?* → Ollama (solo/small) vs vLLM (classroom/busy).
   - *How online is this box?* → Matrix server name, federation, connectors (offline / LAN / domain / Tor).
   - *Real sats or play money?* → default & recommend **regtest**; explain the stakes honestly.

3. **Recommend the inference backend.** From VRAM + concurrency, pick Ollama or vLLM and *explain
   why*, including that streaming + (for vLLM) continuous batching keep it feeling instant, and the
   mesh stays off the hot path (`docs/LATENCY.md`). Choose a `PA_GEN_MODEL` that fits their VRAM.

4. **Install & configure**, one confirmed step at a time — only what `node-doctor` says is missing
   (Docker, NVIDIA container toolkit), then `.env` from the answers. No wall-of-text, no destructive
   commands unprompted.

5. **Load the corpus.** Default Simple English Wikipedia (hours, not weeks). Offer to join the corpus
   torrent mesh so they pull shards from peers instead of re-embedding everything.

6. **Bring it up & verify.** `bootstrap.sh`, confirm every service healthy, have them connect to the
   MUD and talk to the Oracle once.

7. **Issue the certificate.** When the node is healthy AND the expertise quiz is passed, `issue-node-cert`
   issues a **Certified Education Node** credential.

## The certificate

Self-sovereign proof-of-play for operators — signed by the node's **own** key, no central authority.
It doubles as the node's entry on the federated discovery map. Contents and issuance are specified in
the `issue-node-cert` skill; the operator can optionally publish it as a **nostr badge** (NIP-58,
matching Pac's Arcade "one rune per class" model) and/or an **OP_RETURN discovery announce** (regtest
by default) so other Verses add them to the realm directory.

```
   ┌─────────────────────────────────────────────┐
   │   🎓  CERTIFIED EDUCATION NODE                │
   │   Verse:    my-first-verse                    │
   │   Teaches:  Bitcoin & self-custody            │
   │   Pubkey:   npub1… (self-signed)              │
   │   Network:  regtest    Corpus: simple-wiki    │
   │   Issued:   2026-07-06                        │
   │   "A fren who lit up a corner of the map." 💜 │
   └─────────────────────────────────────────────┘
```

## Design principles
- A conversation, never a script. Adapt to the hardware and the human.
- Regtest by default; never help flip to mainnet without `docs/SECURITY.md` + the security gate.
- Offline-first — nothing phones home unless the operator opts into a connector.
- Voice: "fren" 💜, arcade warmth, consequences over prohibitions.
