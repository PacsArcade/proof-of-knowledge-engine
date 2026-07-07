"""corpus/ingest.py — ZIM → articles → chunks → embeddings → DB-1 `documents`. 💜

SCAFFOLDING / STUB. The pipeline shape is real; ZIM parsing, embedding, and inserts are TODOs.

This is the ONLY writer to The Source (DB-1, postgres-source). It reads a ZIM archive
(Kiwix/Wikipedia), extracts each article, chunks it, embeds every chunk with PA_EMBED_MODEL
via the pluggable inference endpoint, and inserts the vectors into DB-1 `documents` (pgvector).

Tier: COLD. This is a background/offline job — it never runs on a gameplay hot path.

See CONVENTIONS §3 (the two databases) and §6 (env).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import AsyncIterator, Iterator

PA_CORPUS = os.environ.get("PA_CORPUS", "simple-wikipedia")
PA_EMBED_MODEL = os.environ.get("PA_EMBED_MODEL", "nomic-embed-text")
PA_INFERENCE_BASE_URL = os.environ.get("PA_INFERENCE_BASE_URL", "http://inference:11434/v1")
PA_DB1_URL = os.environ.get("PA_DB1_URL", "postgresql://arcade:change-me@postgres-source:5433/source")

# Chunking knobs (tune per embedding model's context window).
CHUNK_TOKENS = 512
CHUNK_OVERLAP = 64


@dataclass
class Article:
    source_url: str        # canonical URL / ZIM path of the article
    title: str
    content: str           # plain text / markdown body


@dataclass
class Chunk:
    source_url: str
    title: str
    ordinal: int           # chunk index within the article
    text: str


@dataclass
class Document:
    """One row destined for DB-1 `documents`."""
    source_url: str
    title: str
    ordinal: int
    text: str
    embedding: list[float]


# --------------------------------------------------------------------------- #
# Stage 1 — extract articles from the ZIM archive                             #
# --------------------------------------------------------------------------- #

def read_zim(zim_path: str) -> Iterator[Article]:
    """Yield every article in a ZIM file as (source_url, title, content)."""
    # TODO: use `libzim` to open zim_path, iterate entries, skip non-article namespaces,
    #       strip HTML to clean text/markdown, and yield Article(...) for each.
    raise NotImplementedError("TODO: parse ZIM with libzim and yield Articles")


# --------------------------------------------------------------------------- #
# Stage 2 — chunk each article                                                #
# --------------------------------------------------------------------------- #

def chunk_article(article: Article) -> Iterator[Chunk]:
    """Split an article into overlapping, embed-sized chunks."""
    # TODO: token-aware splitter honoring CHUNK_TOKENS / CHUNK_OVERLAP; keep sentence bounds.
    raise NotImplementedError("TODO: chunk article into ~CHUNK_TOKENS windows")


# --------------------------------------------------------------------------- #
# Stage 3 — embed each chunk                                                   #
# --------------------------------------------------------------------------- #

async def embed_chunk(chunk: Chunk) -> Document:
    """Embed one chunk with PA_EMBED_MODEL via the OpenAI-compatible endpoint."""
    # TODO: POST {PA_INFERENCE_BASE_URL}/embeddings {"model": PA_EMBED_MODEL, "input": chunk.text}
    #       Batch these in the real impl — one HTTP call per chunk is slow for a whole corpus.
    raise NotImplementedError("TODO: embed chunk via PA_EMBED_MODEL")


# --------------------------------------------------------------------------- #
# Stage 4 — insert into DB-1 `documents`                                       #
# --------------------------------------------------------------------------- #

async def insert_documents(docs: list[Document]) -> int:
    """Bulk-insert embedded chunks into DB-1 `documents` (pgvector). Returns rows written."""
    # TODO: asyncpg COPY / executemany into documents(source_url, title, ordinal, text, embedding).
    #       DB-1 is read-only to the rest of the system; this pipeline is its sole writer.
    raise NotImplementedError("TODO: insert Documents into DB-1 `documents`")


# --------------------------------------------------------------------------- #
# Orchestration                                                                #
# --------------------------------------------------------------------------- #

async def ingest_zim(zim_path: str, batch_size: int = 256) -> int:
    """Full pipeline: ZIM → chunk → embed → DB-1. Returns total rows written."""
    total = 0
    batch: list[Document] = []
    for article in read_zim(zim_path):
        for chunk in chunk_article(article):
            batch.append(await embed_chunk(chunk))
            if len(batch) >= batch_size:
                total += await insert_documents(batch)
                batch.clear()
    if batch:
        total += await insert_documents(batch)
    return total


async def ingest_records(records: AsyncIterator[Article], batch_size: int = 256) -> int:
    """Same pipeline, but fed by a connector's fetch() (see connectors/README.md).

    Connectors yield supplemental {source_url, title, content} records; we chunk/embed/insert
    them into DB-1 exactly like ZIM articles, so every knowledge source lands in one place.
    """
    total = 0
    batch: list[Document] = []
    async for article in records:
        for chunk in chunk_article(article):
            batch.append(await embed_chunk(chunk))
            if len(batch) >= batch_size:
                total += await insert_documents(batch)
                batch.clear()
    if batch:
        total += await insert_documents(batch)
    return total


if __name__ == "__main__":
    # TODO: argparse for `python ingest.py path/to/wikipedia.zim`; run ingest_zim via asyncio.
    raise SystemExit("TODO: wire a CLI entrypoint for corpus ingest")
