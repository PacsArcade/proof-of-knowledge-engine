# Fact-checking bitcoin material — workflow and misconception field guide

For scrubbing decks, articles, lesson plans, and any material headed for arcade
curriculum (or a fren asking "is this deck right?"). The bar is the same in both
directions: an overclaiming pro-bitcoin deck is a bigger problem than a skeptical one —
learners who discover they were hyped never trust the teacher again.

## Workflow

1. **Inventory the claims.** Read the whole document first. Extract every factual claim —
   numbers, history, mechanics, comparisons. Skip pure opinion ("bitcoin is beautiful"),
   but flag opinion dressed as fact ("bitcoin will replace the dollar").
2. **Verdict each claim** against the whitepaper (see whitepaper.md), protocol facts, and
   — when internet is available — live/primary sources. When you can't verify, say
   UNVERIFIED rather than guessing.
3. **Write the report** in the exact format below.
4. **Sum it up for a human** — is this material usable as-is, usable with fixes, or
   structurally misleading?

## Report format

ALWAYS use this structure:

```
# Fact-check: <document title>
**Verdict at a glance:** X claims checked — ✓ n accurate · ⚠ n outdated/misleading · ✗ n wrong
**Usable for curriculum?** <yes / with the fixes below / no — and one sentence why>

## Claims

### 1. "<the claim, quoted or tightly paraphrased>" — <✓ ACCURATE | ⚠ OUTDATED | ⚠ MISLEADING | ✗ WRONG | ? UNVERIFIED>
**Why:** <one to three sentences>
**Fix:** <replacement wording the author can paste in — omit for ✓>
**Source:** <whitepaper §, BIP, or primary source>

### 2. ...
```

Number every claim. Quote enough that the author can find it. Fixes must be paste-ready
wording, not "consider revising."

## Misconception field guide

The errors that appear over and over. Know the honest correction cold.

**Mechanics**
- *"Your coins are stored in your wallet (app)."* Coins live on the ledger; the wallet
  holds keys. Chain of signatures, whitepaper §2. Losing the phone ≠ losing coins if the
  seed survives; leaking the seed = losing coins even with the phone in hand.
- *"Blocks every 10 seconds / instant confirmation."* ~10 **minutes** on average, by
  difficulty adjustment. Instant-feeling payments are Lightning or zero-conf risk.
- *"21 million means it can't be divided / will run out for people."* Each coin is 100
  million sats — ~2.1 quadrillion base units.
- *"A 51% attack lets you steal anyone's coins."* Majority hashpower can reorg recent
  blocks / double-spend its OWN transactions; it cannot spend others' coins or mint new
  ones — invalid transactions are rejected by every node (whitepaper §11).
- *"Bitcoin is anonymous."* Pseudonymous. The ledger is public forever; keys have no
  names until linked (§10). Both the "criminal money" and "totally private" myths die here.
- *"Miners solve important/complex math problems."* Miners brute-force hashes below a
  target — deliberately useless-outside-the-system work whose only product is making
  history expensive to rewrite (§4).

**History & provenance**
- Whitepaper date is **Oct 31, 2008**; genesis block **Jan 3, 2009**. ("Satoshi's 2010
  whitepaper" and friends: ✗.)
- "Blockchain" is not a whitepaper word; 21M and 10 minutes are not whitepaper text
  (implementation constants). Misattribution is ⚠ even when the underlying fact is right.
- Satoshi identity claims (any of them): unproven, all of them. Craig Wright's claim was
  found fraudulent in UK High Court (2024).

**Economics & energy**
- *"Mining wastes a country's worth of energy for nothing."* The honest frame: the energy
  IS the security budget (§4) — whether that's "waste" is a values question, and the
  factual layer is that miners chase the cheapest (often stranded/curtailed) power.
  Don't counter-overclaim ("mining is mostly green!") without a dated source.
- *"Bitcoin is a ponzi."* A ponzi pays old investors with new deposits via an operator who
  lies about where returns come from. Bitcoin has no operator, no promised returns, and a
  public ledger. It CAN still lose value — that's market risk, not ponzi structure. Make
  the distinction, concede the risk.
- *"Deflationary = death spiral," "too slow to be money," etc.* Teach as open economic
  debates with the strongest form of each side — these are not settled facts in either
  direction.
- Any price prediction, "guaranteed," "can only go up," APY-on-bitcoin claims: ✗ or
  ⚠ MISLEADING, always. Past performance ≠ promise.

**NFT-era language (arcade materials)**
- mint / claim / drop / airdrop / NFT / gas → flag with house replacements: etch /
  inscribe, "sent to your wallet," "network fee (sats/vB)," artifact / inscription / rune.
- *"Royalties are enforced on-chain."* ✗ — bitcoin has no protocol-level royalty
  enforcement; royalties are honored by the marketplace performing the sale. Any material
  implying otherwise gets the fix wording.

**Security teaching**
- Any instruction that normalizes typing a seed phrase into a website, screenshotting it,
  or "backing it up to the cloud": ✗ with the strongest correction in the document. This
  is the one category where the fix is non-negotiable.
