# pacBOT configuration (v0.2 design draft)

A `pacbot.config.json` next to `SKILL.md`. Everything is optional — a bare
install behaves exactly like v0.1 (arcade voice, whitepaper anchor). The
skill reads this file at the start of a session when it exists.

```json
{
  "personality": {
    "preset": "arcade",
    "styleMatching": true,
    "lexicon": {
      "friend": "fren",
      "signoff": "GG's"
    }
  },
  "knowledge": {
    "sources": [
      { "tier": 0, "name": "bitcoin whitepaper", "path": "references/whitepaper.md" },
      { "tier": 1, "name": "my-first-bitcoin", "path": "../corpora/my-first-bitcoin/" },
      { "tier": 2, "name": "mempool.space", "url": "https://mempool.space/api", "label": "live network data" }
    ],
    "unsourcedClaims": "flag"
  },
  "network": {
    "identity": "npub1...",
    "relays": ["wss://relay.pacsarcade.org"],
    "peers": ["npub1...", "npub1..."],
    "securityClaimPolicy": "unanimous"
  }
}
```

## Field notes

**personality.preset** — `arcade` | `classic` | `scholar`. Presets change
delivery only; the Socratic method, source discipline, and the
education-never-advice rule are not configurable.

**personality.styleMatching** — when true, pacBOT mirrors the learner's
register (vocabulary, pacing, formality) and picks metaphors from their
world. Facts never bend to match style.

**knowledge.sources** — trust-tiered list. Tier 0 = canon (taught as fact),
tier 1 = curated community material (cited), tier 2 = live feeds (always
labeled with fetch time). `unsourcedClaims`: `flag` (default) surfaces the
"I'd verify this before teaching it" caveat; `refuse` declines to teach the
claim at all.

**network** — the v0.4 node-sync block. `identity` is the operator's nostr
key (never a learner's); attestations publish to `relays`; `peers` is the
cross-check set. `securityClaimPolicy: "unanimous"` means anything touching
key handling or spend safety must be attested by every peer before pacBOT
teaches it as settled — mirrors how the arcade treats security findings.

## Compatibility

Configs only add; they never remove safety rails. A config that tries to
disable source discipline or enable advice-giving is ignored with a note to
the operator.
