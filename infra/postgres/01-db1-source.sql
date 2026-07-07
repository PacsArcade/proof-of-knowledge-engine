-- ============================================================================
-- DB-1 — "The Source"  (postgres-source, host port 5433, WARM/COLD tier)
-- ============================================================================
-- The read-only, vectorized knowledge corpus. This is the ground truth every
-- generated room/course/puzzle is checked against by the guardrail. The exact
-- Markdown of the corpus (Simple English Wikipedia first — see connectors/),
-- chunked and embedded with `nomic-embed-text` (768 dims).
--
-- IRON RULE: nothing writes here except the corpus ingest pipeline (the
-- Archivist). Everyone else connects as the `readonly` role defined at the
-- bottom of this file. A read-only Source is what makes the guardrail loop
-- trustworthy — the thing you check against can't be poisoned by the thing
-- you're checking.
--
-- This script runs ONCE, automatically, the first time the container boots on
-- an empty data directory (Postgres' /docker-entrypoint-initdb.d convention).
-- It runs as the superuser against the PA_DB1_NAME database (default `source`).
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 1. The pgvector extension
-- ----------------------------------------------------------------------------
-- Provides the `vector` column type plus the HNSW / IVFFlat index access
-- methods and the distance operators (<=> cosine, <-> L2, <#> inner product).
-- The image (pgvector/pgvector) already has the shared library installed; this
-- just registers it inside THIS database.
CREATE EXTENSION IF NOT EXISTS vector;


-- ----------------------------------------------------------------------------
-- 2. The `documents` table — one row per corpus CHUNK
-- ----------------------------------------------------------------------------
-- We store chunks, not whole articles: a chunk is a retrieval-sized slice of
-- source text with its own embedding. `chunk_index` lets us stitch a document
-- back together in order and cite "part 3 of 7".
CREATE TABLE IF NOT EXISTS documents (
    id           bigserial     PRIMARY KEY,          -- stable chunk id
    source       text          NOT NULL,             -- corpus name, e.g. 'simple-wikipedia'
    source_url   text,                                -- canonical URL of the article
    title        text,                                -- article / section title
    chunk_index  int           NOT NULL DEFAULT 0,   -- 0-based position within the document
    content      text          NOT NULL,             -- the exact Markdown of this chunk
    embedding    vector(768),                         -- nomic-embed-text output (768 dims)
    tsv          tsvector,                            -- lexical index for hybrid search (see §5)
    created_at   timestamptz   NOT NULL DEFAULT now()
);

COMMENT ON TABLE  documents            IS 'DB-1 read-only corpus, one row per embedded chunk.';
COMMENT ON COLUMN documents.embedding  IS '768-dim nomic-embed-text vector; queried with <=> (cosine).';
COMMENT ON COLUMN documents.tsv        IS 'Full-text vector over title+content; kept current by trigger.';


-- ----------------------------------------------------------------------------
-- 3. Vector (semantic) index — HNSW for cosine distance
-- ----------------------------------------------------------------------------
-- HNSW gives fast approximate nearest-neighbour search with high recall and no
-- "training" step (unlike IVFFlat, which needs data present before you build a
-- good index). We index for COSINE distance (`vector_cosine_ops`) because
-- nomic embeddings are compared by cosine similarity — the same metric the
-- guardrail's PA_GUARDRAIL_THRESHOLD (default 0.78) is expressed in.
--
--   Query pattern:  ORDER BY embedding <=> $query_vec  LIMIT k;
--
-- Tuning knobs (defaults are sane to start): m = graph connectivity,
-- ef_construction = build-time accuracy. Raise them for better recall at the
-- cost of build time / memory.
CREATE INDEX IF NOT EXISTS documents_embedding_hnsw
    ON documents
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ALTERNATIVE (smaller RAM footprint, needs data loaded first, then a rebuild):
--   CREATE INDEX documents_embedding_ivfflat
--     ON documents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
-- Pick ONE. HNSW is the better default for a corpus that grows incrementally.


-- ----------------------------------------------------------------------------
-- 4. Lexical index — GIN over the tsvector (the other half of hybrid search)
-- ----------------------------------------------------------------------------
-- Semantic search finds "things that mean the same"; keyword search finds
-- "things that say the exact word" (names, numbers, `OP_RETURN`, `21000000`).
-- Hybrid retrieval fuses both. GIN is the index type for tsvector containment
-- (@@) queries.
CREATE INDEX IF NOT EXISTS documents_tsv_gin
    ON documents
    USING gin (tsv);


-- ----------------------------------------------------------------------------
-- 5. Keep `tsv` in sync with the text
-- ----------------------------------------------------------------------------
-- A trigger recomputes the tsvector on every insert/update so the GIN index is
-- always current. We weight the title ('A') above the body ('B') so a keyword
-- in the heading ranks higher. (A GENERATED column is the modern alternative;
-- a trigger is used here so the ingest pipeline can override weighting later.)
CREATE OR REPLACE FUNCTION documents_tsv_refresh() RETURNS trigger AS $$
BEGIN
    NEW.tsv :=
        setweight(to_tsvector('english', coalesce(NEW.title,   '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.content, '')), 'B');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS documents_tsv_trg ON documents;
CREATE TRIGGER documents_tsv_trg
    BEFORE INSERT OR UPDATE OF title, content ON documents
    FOR EACH ROW EXECUTE FUNCTION documents_tsv_refresh();


-- ----------------------------------------------------------------------------
-- 6. The `readonly` role — enforce "read-only except the ingest pipeline"
-- ----------------------------------------------------------------------------
-- Everyone who QUERIES the Source (the guardrail, the orchestrator's retrieval)
-- connects as this role. It can SELECT and nothing else — no INSERT/UPDATE/
-- DELETE, no DDL. The ingest pipeline (the Archivist) connects as the owner
-- (PA_DB1_USER) instead. Postgres has no `CREATE ROLE IF NOT EXISTS`, so we
-- guard it in a DO block for idempotency.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'readonly') THEN
        -- LOGIN + a password so services can actually connect. CHANGE this
        -- password (or template it from .env) before exposing the port.
        CREATE ROLE readonly LOGIN PASSWORD 'change-me-readonly';
    END IF;
END
$$;

-- Grant exactly SELECT, and make it stick for tables the ingest pipeline
-- creates LATER (ALTER DEFAULT PRIVILEGES) so we never have to re-grant.
GRANT CONNECT ON DATABASE source            TO readonly;   -- matches PA_DB1_NAME
GRANT USAGE   ON SCHEMA   public            TO readonly;
GRANT SELECT  ON ALL TABLES IN SCHEMA public TO readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO readonly;

-- Belt and suspenders: explicitly deny write on the one table we know exists.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON documents FROM readonly;

COMMENT ON ROLE readonly IS 'SELECT-only consumer of DB-1. The Source is read-only except the Archivist ingest pipeline.';
