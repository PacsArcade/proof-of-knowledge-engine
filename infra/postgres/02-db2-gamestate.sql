-- ============================================================================
-- DB-2 — "The Game State" / the BLACKBOARD
--        (postgres-gamestate, host port 5432, HOT tier)
-- ============================================================================
-- The live world AND the shared memory of the agent swarm. Two jobs in one DB:
--
--   1. Game state: users, topics, rooms, world objects, competency.
--   2. The Blackboard: a persistent node/edge graph the agents (Oracle,
--      Architect, Custodian, Archivist, Warden) read and write. Agents do NOT
--      rely on context windows alone — durable state lives HERE, so any agent
--      can pick up where another left off.
--
-- Conventions: snake_case identifiers, real foreign keys, timestamps on
-- everything. This script runs ONCE on first boot (Postgres init convention),
-- as the superuser, against PA_DB2_NAME (default `gamestate`).
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 0. Shared helper: auto-touch `updated_at` on UPDATE
-- ----------------------------------------------------------------------------
-- Attached to mutable tables below so the app never has to remember to set it.
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- ----------------------------------------------------------------------------
-- 1. users — a learner (identified by their node/nostr pubkey)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id             bigserial    PRIMARY KEY,
    pubkey         text         UNIQUE,               -- nostr/discovery identity; NULL for guests
    display_name   text         NOT NULL,
    learning_style jsonb        NOT NULL DEFAULT '{}',-- honcho tracks per-user style/progress here
    created_at     timestamptz  NOT NULL DEFAULT now(),
    updated_at     timestamptz  NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS users_touch ON users;
CREATE TRIGGER users_touch BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE users IS 'Learners in this verse. pubkey is the portable, offline-first identity.';


-- ----------------------------------------------------------------------------
-- 2. topics — the skill tree (self-referential hierarchy)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS topics (
    id          bigserial    PRIMARY KEY,
    slug        text         NOT NULL UNIQUE,         -- e.g. 'bitcoin-seed-phrases'
    title       text         NOT NULL,
    description text,
    parent_id   bigint       REFERENCES topics(id) ON DELETE SET NULL,  -- NULL = root topic
    created_at  timestamptz  NOT NULL DEFAULT now()
);
COMMENT ON TABLE topics IS 'The knowledge/skill tree. parent_id builds the prerequisite hierarchy.';


-- ----------------------------------------------------------------------------
-- 3. competency_node — what a user has mastered (the Oracle writes this)
-- ----------------------------------------------------------------------------
-- The Oracle (Interview Bot) runs Socratic dialogue, scores mastery, and
-- records it here. The Architect reads it to target Training Dungeon rooms at
-- the user's actual gaps.
CREATE TABLE IF NOT EXISTS competency_node (
    id                 bigserial    PRIMARY KEY,
    user_id            bigint       NOT NULL REFERENCES users(id)  ON DELETE CASCADE,
    topic_id           bigint       NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    mastery_score      numeric(5,4) NOT NULL DEFAULT 0            -- 0.0000 .. 1.0000
                       CHECK (mastery_score >= 0 AND mastery_score <= 1),
    transcript_summary text,                                       -- condensed evidence for the score
    updated_at         timestamptz  NOT NULL DEFAULT now(),
    UNIQUE (user_id, topic_id)                                     -- one competency per user+topic
);
DROP TRIGGER IF EXISTS competency_node_touch ON competency_node;
CREATE TRIGGER competency_node_touch BEFORE UPDATE ON competency_node
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE competency_node IS 'Per-user, per-topic mastery. Written by the Oracle, read by the Architect.';


-- ----------------------------------------------------------------------------
-- 4. rooms — dynamically generated dungeon rooms (the guardrail gate lives here)
-- ----------------------------------------------------------------------------
-- The Architect generates a room to teach a gap. Before players see it, the
-- guardrail embeds it and checks similarity vs DB-1. Its verdict lands in
-- `guardrail_status`:
--   pending      → generated, not yet checked (never shown to players)
--   approved     → passed the similarity floor; live
--   quarantined  → below PA_GUARDRAIL_THRESHOLD; the Warden pings the operator
--                  in their encrypted Matrix admin room to approve or reject.
--                  The human is the final guardrail.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'guardrail_status') THEN
        CREATE TYPE guardrail_status AS ENUM ('pending', 'approved', 'quarantined');
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS rooms (
    id               bigserial        PRIMARY KEY,
    topic_id         bigint           REFERENCES topics(id) ON DELETE SET NULL,
    generated_by     text             NOT NULL DEFAULT 'architect',  -- which agent authored it
    guardrail_status guardrail_status NOT NULL DEFAULT 'pending',
    similarity_score numeric(5,4),                                   -- cosine vs DB-1 at check time
    content          jsonb            NOT NULL DEFAULT '{}',         -- room description, puzzles, exits
    created_at       timestamptz      NOT NULL DEFAULT now(),
    updated_at       timestamptz      NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS rooms_touch ON rooms;
CREATE TRIGGER rooms_touch BEFORE UPDATE ON rooms
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Fast lookup of the quarantine queue the Warden works through.
CREATE INDEX IF NOT EXISTS rooms_guardrail_status_idx ON rooms (guardrail_status);

COMMENT ON TABLE rooms IS 'AI-generated dungeon rooms. Not shown to players until guardrail_status = approved.';


-- ----------------------------------------------------------------------------
-- 5. world_objects — the furniture of the verse
-- ----------------------------------------------------------------------------
-- Items, props, and interactables inside a room. Shared by BOTH interfaces:
-- state-sync renders the same object as ANSI text in the MUD and as a voxel in
-- Luanti.
CREATE TABLE IF NOT EXISTS world_objects (
    id          bigserial    PRIMARY KEY,
    room_id     bigint       REFERENCES rooms(id) ON DELETE CASCADE,
    object_type text         NOT NULL,               -- 'chest', 'npc', 'terminal', ...
    name        text         NOT NULL,
    data        jsonb        NOT NULL DEFAULT '{}',  -- type-specific state
    created_at  timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS world_objects_room_idx ON world_objects (room_id);
COMMENT ON TABLE world_objects IS 'Interactables in a room; rendered as text (MUD) or voxels (Luanti).';


-- ----------------------------------------------------------------------------
-- 6. The Blackboard graph — memory_node + memory_edge
-- ----------------------------------------------------------------------------
-- The agents' shared, durable working memory as a typed graph. A node points
-- at any row in the DB via (node_type, ref_id) and carries free-form jsonb;
-- edges are typed relations between nodes. This is how the swarm reasons over
-- state that outlives any single context window.
CREATE TABLE IF NOT EXISTS memory_node (
    id         bigserial    PRIMARY KEY,
    node_type  text         NOT NULL,                -- 'user' | 'topic' | 'room' | 'goal' | ...
    ref_id     bigint,                                -- optional FK-by-convention into node_type's table
    data       jsonb        NOT NULL DEFAULT '{}',
    created_at timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS memory_node_type_ref_idx ON memory_node (node_type, ref_id);

CREATE TABLE IF NOT EXISTS memory_edge (
    id         bigserial    PRIMARY KEY,
    from_node  bigint       NOT NULL REFERENCES memory_node(id) ON DELETE CASCADE,
    to_node    bigint       NOT NULL REFERENCES memory_node(id) ON DELETE CASCADE,
    relation   text         NOT NULL,                -- 'blocks' | 'teaches' | 'mastered' | ...
    created_at timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS memory_edge_from_idx ON memory_edge (from_node);
CREATE INDEX IF NOT EXISTS memory_edge_to_idx   ON memory_edge (to_node);

COMMENT ON TABLE memory_node IS 'Blackboard graph node: durable agent memory, addressable by (node_type, ref_id).';
COMMENT ON TABLE memory_edge IS 'Typed relation between two Blackboard nodes.';


-- ----------------------------------------------------------------------------
-- 7. seed_fragments — the seed-loot ledger (REGTEST BY DEFAULT)
-- ----------------------------------------------------------------------------
-- The Custodian splits a wallet seed into Shamir Secret Sharing shares and
-- scatters them as loot. Each row is one share/fragment in the world.
--
-- ⚠ MONEY SAFETY: `network` defaults to 'regtest' — a private chain with NO
-- real funds. The CHECK below permits testnet/mainnet as VALUES, but writing a
-- 'mainnet' row is only legal when the operator has set PA_MAINNET_ACK=true AND
-- passed a security-auditor review (docs/SECURITY.md). The app enforces that
-- gate; the DB defaults you to safety. Custodian stays regtest-only until
-- security sign-off.
CREATE TABLE IF NOT EXISTS seed_fragments (
    id             bigserial    PRIMARY KEY,
    fragment_index int          NOT NULL,                -- share number (k-of-n SSS)
    item_id        text         NOT NULL,                -- the in-world item carrying this share
    sss_share_ref  text         NOT NULL,                -- pointer/handle to the encrypted SSS share
    network        text         NOT NULL DEFAULT 'regtest'
                   CHECK (network IN ('regtest', 'testnet', 'mainnet')),  -- mainnet gated (see above)
    minted         boolean      NOT NULL DEFAULT false,  -- has the on-chain artifact been created?
    holder_user_id bigint       REFERENCES users(id) ON DELETE SET NULL,  -- who currently holds it (NULL = in the world)
    created_at     timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS seed_fragments_holder_idx ON seed_fragments (holder_user_id);

COMMENT ON TABLE seed_fragments IS 'SSS seed-loot ledger. REGTEST by default; mainnet requires PA_MAINNET_ACK + security review.';
COMMENT ON COLUMN seed_fragments.network IS 'regtest|testnet|mainnet — mainnet is GATED; the default keeps you safe.';


-- ----------------------------------------------------------------------------
-- 8. tips — sats sent from a learner to a node operator
-- ----------------------------------------------------------------------------
-- Value flows to the humans running nodes and teaching. Regtest sats by
-- default, same money-safety gate as above.
CREATE TABLE IF NOT EXISTS tips (
    id                bigserial    PRIMARY KEY,
    from_user         bigint       REFERENCES users(id) ON DELETE SET NULL,
    to_node_operator  text         NOT NULL,                -- operator pubkey / payout identity
    amount_sats       bigint       NOT NULL CHECK (amount_sats > 0),
    network           text         NOT NULL DEFAULT 'regtest'
                      CHECK (network IN ('regtest', 'testnet', 'mainnet')),
    created_at        timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS tips_operator_idx ON tips (to_node_operator);

COMMENT ON TABLE tips IS 'Learner → node-operator sats tips. REGTEST by default; mainnet is gated.';
