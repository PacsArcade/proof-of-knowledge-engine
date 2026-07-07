# Building a class on demand

For "make me a course/class/workshop/lesson on X." Output is a complete, runnable lesson
plan an instructor can teach from tomorrow — not a topic list.

## Before writing, settle three things

1. **Audience & level** — from the request or one quick question. Default: complete
   beginner, zero jargon assumed.
2. **Length & format** — default: 45-minute live-streamed class with live chat.
3. **Voice** — arcade (Pac's Arcade classes) or neutral (material for other groups).

Seed content to draw from (real, teachable material):
- The Pac's Arcade meetup library:
  https://github.com/Reeds-Agent-Team/Bitcoin-Meetups/blob/main/meetup-content.md
  ("My First Bitcoin" ch. 1–7, Self-Custody Security Fundamentals, Lightning workshop,
  node builder, and more)
- The whitepaper teaching notes in [whitepaper.md](whitepaper.md)
- Anything the requester provides (fact-check outside material first — see
  [fact-check.md](fact-check.md))

## Course document format

ALWAYS use this structure:

```
# <CLASS TITLE>
**Audience:** <who + assumed knowledge>   **Length:** <minutes>   **Format:** <live stream / in person / self-paced>
**Cert earned:** <cert name> — etched as a rune to the learner's wallet after verified
attendance; the Pac's Arcade non-profit pays the network fee.

## What you'll be able to do after this class
- <3-5 outcomes, each observable — "explain X to a friend," "set up Y," not "understand Z">

## Modules
### Module 1 — <name> (<minutes>)
**The idea:** <2-4 sentences of the actual content, not a placeholder>
**Socratic beat:** "<the question the instructor asks and lets the room answer>"
**Watch for:** <the misconception that surfaces here and how to catch it>

### Module 2 — ...

## ✦ CHECK-IN (place mid-session, inside a module)
<The attendance moment: the instructor reveals a code word on stream; learners enter it
to record attendance. The check-in is the proof behind the cert — the rune is the trophy,
the attestation is the certificate. Write the actual moment: when it happens and what the
instructor says.>

## Try it before next time
- <1-3 small homework actions with zero cost and zero risk>

## Instructor notes
- <timing risks, demo prerequisites, what to have open, hard questions to expect with
  suggested answers>
```

## Where classes live, and who teaches

Classes are **Pac's Arcade** classes: they live on pacsarcade.org and speak in @pacsarcade
voice. frens.earth is the registration door; the interlinking (wallets, certs, campaigns)
is taught at the arcade — invite frens over rather than duplicating classes there.
Every plan must be runnable by a **human instructor or an AI attendant** (see
[agent-mode.md](agent-mode.md)) — that's why the ANSWER BANK below is required, not optional.

## Attendance & cert issuance (the attestation menu)

The cert is honest only if attendance is verifiable. v1 mechanic: the **code word**
revealed once mid-stream — and the fren **enters the code in the cert-issuance flow**
(the code is the key that starts their rune etching, not a trivia moment). Design the
class so the code lands right after the material the cert vouches for.

Nostr-native options to design toward (note them in instructor notes where relevant):
- **Relay-scoped poll/note:** publish the check-in as a nostr poll or note ONLY to the
  pacsarcade relay (not public relays) — responses are signed by each fren's key, arriving
  on infrastructure we run: automatable attestation with no new accounts.
- **Zap-receipt pairing:** zap receipts name the recipient's pubkey, so an instructor zap
  during class pairs a fren's profile to the session. Honest caveat: a zap proves the fren
  was *zappable*, not present — use it to confirm the wallet↔profile link works, combined
  with the code/poll for presence.

A readiness poll (green/yellow/red) is a good *pacing* tool alongside the attendance
code — the two do different jobs; don't merge them.

## Who pays which fee (say it explicitly in course + campaign material)

- **Certs:** the non-profit pays the etch network fee — a learner never pays to receive a cert.
- **Campaign artifacts:** decide and disclose per flow — either the collector's price
  includes the network fee, or the campaign wallet covers it (visible in the campaign's
  public spend ledger either way). Never imply "free, just fees" — a fee IS a cost.

## Visual lessons & etched media (the Imprint standard, arcade edition)

Great classes teach abstract ideas through **powerful visuals, bite-sized** — one strong
image per idea beats a paragraph (study imprintapp.com's style: beautiful visuals doing
the explanatory work, modules digestible in minutes). When building a class, name the
key visual for each module ("the two-slot inventory table", "the chain-of-signatures
diagram") so an artist or agent can produce it.

When lesson cards, certs, or artifacts get etched on bitcoin, **don't litter the chain
with big data**:
- Format: **WebP** — high resolution at low bytes is the whole game.
- Cost intuition: inscription data rides in the witness (4x discount), so
  **cost ≈ (file bytes ÷ 4 + ~200 vB overhead) × fee rate (sats/vB) + postage (~330–546
  sats)**. A 40 KB WebP ≈ ~10,200 vB — at 2 sats/vB that's ~20,400 sats plus postage.
  Always compute at the current fee rate (label it LIVE); a cost calculator like
  buidlersbtc.com's inscription calculator is a good cross-check.
- Conversion: the arcade tools include a self-hosted converter (ConvertX,
  github.com/C4illin/ConvertX) — convert to WebP and check the byte size *before* any
  etch order.

## Course document format additions

The "Instructor notes" section must include an **ANSWER BANK**: the predetermined
answers to the hard questions this class always gets, written out fully enough that a
substitute instructor — human or AI — answers them the arcade way. Grow the bank after
every run of the class (log new questions from the check-in and chat).

## Design rules

- **Every module teaches, then asks.** Content first, Socratic beat second — a course of
  pure questions frustrates; a course of pure lecture evaporates.
- **One demo beats three slides.** Wallet classes: create a real wallet live (throwaway,
  labeled as such). Node classes: a live mempool view. Say in instructor notes what to
  have open.
- **Security content follows the guardrails** everywhere: consequences not prohibitions,
  seed-phrase handling taught with the chest-in-the-attic frame (arcade voice) or plainly
  (neutral), and never an exercise that involves typing a real seed anywhere.
- **Free and low-stakes homework.** Nothing that requires buying bitcoin; sats amounts in
  examples stay small and are labeled examples.
- **Honest numbers.** Live figures labeled LIVE with a date; teaching figures labeled as
  examples (see SKILL.md guardrail 6).
- **The foundation series context:** WHAT IS BITCOIN, WHAT IS NOSTR, and YOUR WALLET are
  the three foundation classes; all three certs together open the artist gate (campaign
  creation). When building one of these, say where it sits in the series and what the
  next class is.
