---
name: hallucination-guardrail
description: Check AI-generated educational content (rooms, courses, puzzles, Oracle answers) against DB-1 for factual grounding before it goes live, and route failures to the operator for review. Use when wiring or tuning the guardrail, when generated content needs validation, or when someone asks "how do we stop the AI from making things up?".
---

# Hallucination Guardrail 🛡️

Local LLMs generate the world. Left unchecked, they invent facts. This is the seam that keeps
a *knowledge* engine honest: nothing enters the curriculum unless it is grounded in **The
Source (DB-1)** or a human operator has approved it.

## The loop
1. An agent (usually the Architect) produces content — a room description, a course module, a
   puzzle, an Oracle answer.
2. Embed it via `PA_EMBED_MODEL` and run a **KNN cosine search** against DB-1 `documents`.
3. **Best similarity ≥ `PA_GUARDRAIL_THRESHOLD`** (default 0.78) → **pass**. Content goes live.
4. **Below threshold** → **quarantine**. The Warden posts it to the operator's **encrypted
   Matrix admin room** with its nearest DB-1 neighbors, so the human sees *why* it was flagged
   and can approve or reject. The operator is the final guardrail.

## Where speed and rigor split
- **Prose can stream first, verify after.** Flavor text is low-stakes; let it scroll.
- **Anything that reveals value must pass before it reveals.** A puzzle that unlocks a **seed-loot
  fragment** cannot award the fragment until the content has passed the guardrail (and the
  operator, if quarantined). Fail **closed** on money paths. See `docs/SECURITY.md`.

## Implementation notes (`services/guardrail/check.py`)
- One embed + one pgvector ANN query — keep it inside the WARM latency budget.
- Log every quarantine with score + neighbors; make the threshold configurable, never a magic
  constant. Tune it empirically against known-good and known-bad samples.
- Provide a fast "explain" that shows the operator the supporting DB-1 passages on approve.

## Rules
- **DB-1 is the node's own verified ground truth — grounding *is* the citation.** Content that
  can't be grounded is **unverified**: it never ships as fact, it goes to the operator.
- No value-bearing content goes live having skipped the check.
- Every quarantine is explainable (score + sources), never a silent drop.
- The human operator, in their encrypted room, is the ultimate authority.
