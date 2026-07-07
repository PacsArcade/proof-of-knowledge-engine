"""guardrail/check.py — is this AI-generated content grounded in The Source? 💜

SCAFFOLDING / STUB. The flow is real; the embed call and pgvector query are TODOs.

The guardrail loop (docs/CONVENTIONS.md §3): embed a piece of AI-generated content, KNN
cosine-search it against DB-1 `documents`, and if the best match is too weak, quarantine it.
Quarantined content is NOT shipped — the Warden pings the operator in their encrypted Matrix
admin room to approve or reject. The human is the final guardrail.

Tier: WARM. Embedding is local-GPU via PA_INFERENCE_BASE_URL; the search is a node-local DB-1
query. Nothing here crosses the network.

Port (service): 8081.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

# Embedding model + endpoint (pluggable, OpenAI-compatible). See CONVENTIONS §6.
PA_EMBED_MODEL = os.environ.get("PA_EMBED_MODEL", "nomic-embed-text")
PA_INFERENCE_BASE_URL = os.environ.get("PA_INFERENCE_BASE_URL", "http://inference:11434/v1")

# Cosine similarity floor. At/above → pass; below → quarantine.
PA_GUARDRAIL_THRESHOLD = float(os.environ.get("PA_GUARDRAIL_THRESHOLD", "0.78"))

# DB-1, The Source (read-only, pgvector).
PA_DB1_URL = os.environ.get("PA_DB1_URL", "postgresql://arcade:change-me@postgres-source:5433/source")

Verdict = Literal["pass", "quarantine"]


@dataclass
class GuardrailResult:
    verdict: Verdict
    best_similarity: float           # cosine similarity of the nearest DB-1 document
    threshold: float                 # the floor we compared against
    nearest_doc_id: str | None       # which corpus doc it most resembled (for the operator)
    note: str                        # human-facing explanation


async def _embed(text: str) -> list[float]:
    """Embed `text` with PA_EMBED_MODEL via the OpenAI-compatible inference endpoint."""
    # TODO: POST {PA_INFERENCE_BASE_URL}/embeddings  {"model": PA_EMBED_MODEL, "input": text}
    #       and return the embedding vector. Keep it on the WARM budget (first token < 300 ms).
    raise NotImplementedError("TODO: call PA_EMBED_MODEL via PA_INFERENCE_BASE_URL")


async def _nearest_document(embedding: list[float]) -> tuple[str | None, float]:
    """KNN cosine search against DB-1 `documents`; return (doc_id, best_similarity)."""
    # TODO: pgvector query, e.g.
    #   SELECT id, 1 - (embedding <=> $1) AS similarity
    #   FROM documents ORDER BY embedding <=> $1 LIMIT 1;
    #   ( <=> is cosine distance; 1 - distance = cosine similarity )
    raise NotImplementedError("TODO: pgvector KNN cosine search against DB-1 documents")


async def check_content(text: str, threshold: float = PA_GUARDRAIL_THRESHOLD) -> GuardrailResult:
    """Embed → KNN cosine vs DB-1 → pass or quarantine.

    Returns `quarantine` when the best corpus match is below `threshold`. On quarantine the
    Warden pings the operator's Matrix admin room (via matrix-bridge) — the human decides.
    """
    embedding = await _embed(text)
    nearest_id, best_similarity = await _nearest_document(embedding)

    if best_similarity >= threshold:
        return GuardrailResult(
            verdict="pass",
            best_similarity=best_similarity,
            threshold=threshold,
            nearest_doc_id=nearest_id,
            note="Grounded in The Source — clear to ship.",
        )

    # Below the floor: hold it for a human.
    return GuardrailResult(
        verdict="quarantine",
        best_similarity=best_similarity,
        threshold=threshold,
        nearest_doc_id=nearest_id,
        note=(
            "Below the corpus similarity floor — possible hallucination. "
            "The Warden will ping the operator's Matrix admin room to approve or reject. "
            "Human is the final guardrail, fren."
        ),
    )


# TODO: wrap check_content in a FastAPI POST /check endpoint on port 8081 so the Warden can
#       call it over HTTP, and add a demo() for local smoke-testing.
