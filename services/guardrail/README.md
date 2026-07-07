# guardrail — the hallucination check vs The Source 💜

> Part of **Pac's Arcade — The Federated Knowledge Engine**.
> See the canonical contract in [`docs/CONVENTIONS.md`](../../docs/CONVENTIONS.md).

## Role

`guardrail` is the semantic-similarity gate that stands between AI-generated content and your
frens. Any AI-generated room / course / puzzle / dialogue is embedded and compared against
**The Source** (DB-1 `postgres-source`, the read-only vectorized corpus). If the generated
content doesn't look enough like anything in the corpus, it's probably a hallucination — so it
gets **quarantined** instead of shipped.

This is the WARM half of the **guardrail loop** described in CONVENTIONS §3. The Warden agent
calls this service; on a `quarantine` verdict the Warden pings the operator in their encrypted
**Matrix admin room** (via `matrix-bridge`) to approve or reject. **The human is the final
guardrail.**

## Tier

**WARM.** Embedding runs on the local GPU through the pluggable inference endpoint; first token
< 300 ms. The KNN search is a node-local DB-1 query. No content leaves the box.

## Port

**8081** (docker-compose service name: `guardrail`).

## The check

1. Embed the candidate text with `PA_EMBED_MODEL` via `PA_INFERENCE_BASE_URL`.
2. KNN **cosine** search against DB-1 `documents` (pgvector).
3. Compare best similarity to `PA_GUARDRAIL_THRESHOLD` (default **0.78**):
   - `best_similarity >= threshold` → **`pass`**.
   - `best_similarity <  threshold` → **`quarantine`** (Warden → operator's Matrix admin room).

## How it fits the whole

```
 Architect gen ──► Warden ──► guardrail (WARM) ──embed──► inference
                                   │
                                   └──KNN cosine──► DB-1 documents (pgvector)
                                   │
                    pass ◄─────────┴─────────► quarantine ──► matrix-bridge → operator
```

## How to run it

```bash
docker compose up guardrail
# or, local dev:
cd services/guardrail
pip install httpx asyncpg pgvector   # TODO: pin in requirements.txt
python -c "import asyncio, check; asyncio.run(check.demo())"   # TODO: add a demo()/CLI
```

Required env: `PA_EMBED_MODEL`, `PA_INFERENCE_BASE_URL`, `PA_GUARDRAIL_THRESHOLD`, `PA_DB1_URL`.

> ⚠️ **Scaffolding.** `check.py` is a commented stub with `TODO`s where the embed call and the
> pgvector KNN query go.
