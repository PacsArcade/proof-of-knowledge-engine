-- ============================================================================
-- DB-2 — CLASS-CERTIFICATE RUNES (soulbound, bitcoin POAP-equivalent)
--        (postgres-gamestate, host port 5432, HOT-tier DB / COLD-tier writer)
-- ============================================================================
-- When the Oracle confirms a learner has mastered a class (a guardrail-passed
-- competency_node), the node mints them a **class certificate as a Bitcoin
-- rune** — Pac's Arcade "one rune per class" / bitcoin-POAP model. This script
-- registers the per-class runes and records the certificates.
--
-- The service that fills these tables is services/bitcoin-bridge/runes.py; it
-- is REGTEST-ONLY by default and reuses vault.py's safety guard. See
-- docs/RUNES.md (design) and docs/SECURITY.md (money gate).
--
-- SOULBOUND-BY-CONVENTION: Bitcoin has no native soulbound primitive, so the
-- credential is trusted only for the wallet that EARNED it. A transfer does not
-- destroy the credit — `current_wallet` diverges from `original_wallet` and the
-- verifier flags it "moved", but the earned fact (block_time + original_wallet)
-- is immutable on-chain.
--
-- COMPROMISED-WALLET RECOVERY: because the original wallet + earn time live
-- on-chain, a student who loses/moves their wallet does NOT lose their certs —
-- the node re-issues to a new wallet citing the original provenance and marks
-- the old row `superseded_by` (superseded, never destroyed).
--
-- Conventions match 02-db2-gamestate.sql: snake_case, real foreign keys,
-- timestamps on everything, `set_updated_at()` touch trigger on mutable tables,
-- `network` defaults to 'regtest'. This script runs after 02 on first boot
-- (Postgres /docker-entrypoint-initdb.d convention), so set_updated_at() and the
-- users table already exist.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 1. class_catalog — the per-class rune registry (one rune per class)
-- ----------------------------------------------------------------------------
-- One row per class that can award a certificate. The Arcade Treasury etches
-- exactly ONE rune per class (naming convention PACS•<CLASS>, e.g.
-- 'PACS•BITCOIN•BASICS'); etch_txid/etched_at are filled once that etch lands.
-- Both are NULL between "class registered" and "rune etched" (etch is idempotent).
CREATE TABLE IF NOT EXISTS class_catalog (
    class_id    text         PRIMARY KEY,             -- class slug, e.g. 'bitcoin-basics'
    title       text         NOT NULL,                -- human title, e.g. 'Bitcoin Basics'
    rune_name   text         NOT NULL UNIQUE,         -- PACS•<CLASS> display name; one per class
    etch_txid   text,                                 -- the etch transaction (NULL until etched)
    etched_at   timestamptz,                          -- when the rune was etched (NULL until etched)
    created_at  timestamptz  NOT NULL DEFAULT now(),
    updated_at  timestamptz  NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS class_catalog_touch ON class_catalog;
CREATE TRIGGER class_catalog_touch BEFORE UPDATE ON class_catalog
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE  class_catalog IS 'Per-class rune registry. One rune per class, etched by the Arcade Treasury (fees paid by the non-profit). PACS•<CLASS> naming.';
COMMENT ON COLUMN class_catalog.rune_name IS 'Display rune name PACS•<CLASS>; UNIQUE — exactly one rune per class.';
COMMENT ON COLUMN class_catalog.etch_txid IS 'Etch transaction id; NULL until the rune is etched (idempotent etch).';


-- ----------------------------------------------------------------------------
-- 2. class_certificates — a minted soulbound certificate (1 rune unit / student)
-- ----------------------------------------------------------------------------
-- One row per certificate minted to a learner. Provenance is the point:
--   * original_wallet + block_time come FREE from the mint transaction (the
--     recipient address and the confirming block header) and are IMMUTABLE —
--     they record who earned it and exactly when.
--   * current_wallet tracks where the rune unit lives now; when it differs from
--     original_wallet the credential is "moved" (still valid for the earner).
--   * superseded_by points at a reissued cert (compromised-wallet recovery):
--     the old row is kept as history, never deleted.
--   * revoked is a separate, deliberate operator action (fraud/mistake), NOT the
--     same as superseded.
--
-- ⚠ MONEY SAFETY: `network` defaults to 'regtest'. Minting on 'mainnet' is only
-- legal once the operator has opted into the vault's mainnet gate (PA_MAINNET_ACK
-- + security-auditor review — see docs/SECURITY.md). The app enforces the gate
-- (runes.py reuses vault.require_safe_network); the DB defaults you to safety.
CREATE TABLE IF NOT EXISTS class_certificates (
    id             bigserial    PRIMARY KEY,
    class_id       text         NOT NULL REFERENCES class_catalog(class_id) ON DELETE RESTRICT,
    rune_name      text         NOT NULL,                -- denormalized PACS•<CLASS> for display
    rune_id        text,                                 -- ord rune id "block:tx" (NULL until confirmed)
    student_pubkey text         NOT NULL,                -- learner identity; corresponds to users.pubkey
    original_wallet text        NOT NULL,                -- address first minted to — PROVENANCE ROOT (immutable)
    current_wallet text         NOT NULL,                -- where the unit lives now (== original at mint)
    competency_ref text         NOT NULL,                -- pointer to the guardrail-passed competency_node
    mint_txid      text         NOT NULL,                -- the mint transaction
    block_height   bigint,                               -- confirming block height (NULL until confirmed)
    block_time     timestamptz,                          -- confirming block time == "earned at" (from the header)
    soulbound      boolean      NOT NULL DEFAULT true,   -- non-transferable BY CONVENTION (see docs/RUNES.md)
    superseded_by  bigint       REFERENCES class_certificates(id) ON DELETE SET NULL,  -- reissue target; NULL = live
    revoked        boolean      NOT NULL DEFAULT false,  -- deliberate operator revocation (distinct from superseded)
    network        text         NOT NULL DEFAULT 'regtest'
                   CHECK (network IN ('regtest', 'testnet', 'mainnet')),  -- mainnet gated (see above)
    created_at     timestamptz  NOT NULL DEFAULT now(),
    updated_at     timestamptz  NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS class_certificates_touch ON class_certificates;
CREATE TRIGGER class_certificates_touch BEFORE UPDATE ON class_certificates
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- What a wallet displays: certs currently held by an address.
CREATE INDEX IF NOT EXISTS class_certificates_current_wallet_idx  ON class_certificates (current_wallet);
-- Provenance / recovery lookups: everything a given earner ever earned.
CREATE INDEX IF NOT EXISTS class_certificates_original_wallet_idx ON class_certificates (original_wallet);
CREATE INDEX IF NOT EXISTS class_certificates_student_idx         ON class_certificates (student_pubkey);
CREATE INDEX IF NOT EXISTS class_certificates_class_idx           ON class_certificates (class_id);
-- Resolve a certificate by its on-chain rune id.
CREATE INDEX IF NOT EXISTS class_certificates_rune_id_idx         ON class_certificates (rune_id);
-- One live certificate per (student, class): a student holds a class's rune once.
-- Superseded/revoked rows are excluded so recovery can re-mint without collision.
CREATE UNIQUE INDEX IF NOT EXISTS class_certificates_live_uniq
    ON class_certificates (student_pubkey, class_id)
    WHERE superseded_by IS NULL AND revoked = false;

COMMENT ON TABLE  class_certificates IS 'Soulbound class-certificate runes (1 unit/student). REGTEST by default; mainnet gated. Provenance (original_wallet + block_time) is immutable and enables compromised-wallet recovery.';
COMMENT ON COLUMN class_certificates.original_wallet IS 'Address the cert was FIRST minted to — the immutable provenance root the soulbound check trusts.';
COMMENT ON COLUMN class_certificates.current_wallet  IS 'Current holder; differs from original_wallet iff the rune was moved (still valid for the earner).';
COMMENT ON COLUMN class_certificates.block_time      IS '"Earned at" — the confirming block header time; comes free from the mint tx.';
COMMENT ON COLUMN class_certificates.soulbound       IS 'True by convention. Bitcoin has no native soulbound primitive; the verifier enforces it (docs/RUNES.md).';
COMMENT ON COLUMN class_certificates.superseded_by   IS 'Points at the reissued cert on compromised-wallet recovery. The old row is kept (superseded, not destroyed).';
COMMENT ON COLUMN class_certificates.revoked         IS 'Deliberate operator revocation (fraud/error) — NOT the same as superseded.';
COMMENT ON COLUMN class_certificates.network         IS 'regtest|testnet|mainnet — mainnet is GATED; the default keeps you safe.';
