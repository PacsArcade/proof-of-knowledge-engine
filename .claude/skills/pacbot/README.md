# pacBOT — the arcade's forever attendant 🕹️

A whitepaper-fluent, Socratic **bitcoin & nostr educator skill** for
[Claude Code](https://claude.com/claude-code), built by the
[Pac's Arcade](https://pacsarcade.org) non-profit on one belief:

> Nobody should have to trust; everybody should get to verify.

pacBOT answers the thousandth *"what even IS bitcoin?"* with the same care as
the first. It teaches self-custody in game language (the seed phrase is the
chest in the attic where Link keeps what matters — nobody legitimate ever asks
you to open the chest), fact-checks decks and curricula against the bitcoin
whitepaper, and builds full classes on any bitcoin or nostr topic.

Think of where this is going as **the Curator from Ready Player One**: a
patient, ever-present steward of the archive who meets every player at their
level and never lets a false fact onto the shelf.

## What it does

- **Socratic teaching** — questions before answers; learners arrive at
  understanding instead of receiving it. Every concept re-explainable simpler,
  differently, or in pure game language.
- **Whitepaper-anchored** — protocol claims ground in Satoshi's paper
  (`references/whitepaper.md` carries section-level substance).
- **Fact-checking** — scrubs presentations, articles, and curricula for
  errors, hype, and banned marketing verbiage (`references/fact-check.md`).
- **Course building** — turns a topic into a session-by-session class with
  code-word attendance checks (`references/course-builder.md`).
- **Agent mode** — runs as the live attendant on the arcade floor
  (`references/agent-mode.md`).

Benchmarked at **100%** on its eval suite (`evals/evals.json`) against an
84% no-skill baseline.

## Install

Copy this folder into your Claude Code skills directory:

```
git clone https://github.com/PacsArcade/pacbot ~/.claude/skills/pacbot
```

Then ask Claude anything about bitcoin, nostr, wallets, seed phrases, mining,
Lightning, ordinals, or runes — or just address it as "pacBOT".

## Where it's headed

See [ROADMAP.md](ROADMAP.md): configurable personality (match the learner's
style), configurable knowledge sources beyond the whitepaper, and
**node sync** — pacBOT instances cross-verifying facts with each other over
nostr so accurate knowledge propagates and bad facts get caught. A separate
track builds the game side of the arcade; pacBOT is its attendant.

## Voice

The community word is **fren** — never "friend" 💜. Sign-offs are **GG's** —
good gameS, plural, because we never play just one.

## License

MIT — education wants to be free. See [LICENSE](LICENSE).

---

A project of the Pac's Arcade non-profit · zero fees, no jargon, no wrong
questions · [pacsarcade.org](https://pacsarcade.org) ·
[frens.earth](https://frens.earth)
