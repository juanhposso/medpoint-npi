-- =============================================================================
-- medpoint-npi  |  db/schema.sql
-- Runs automatically on first docker-compose up (postgres initdb.d mechanism).
-- To re-run: docker-compose down -v && docker-compose up postgres
-- =============================================================================


-- ─── physicians ──────────────────────────────────────────────────────────────
-- One row per DCA license record.
-- Column names mirror DCAResult fields exactly so dca_reader.py can map
-- query results directly to the Pydantic model with zero transformation.
-- =============================================================================

CREATE TABLE IF NOT EXISTS physicians (

    -- Primary key — DCA license numbers are unique per physician
    license_number          VARCHAR(50)     PRIMARY KEY,

    -- Name fields — match DCAResult exactly
    last_name               VARCHAR(100)    NOT NULL,
    first_name              VARCHAR(100)    NOT NULL,
    middle_name             VARCHAR(100),   -- nullable: Optional[str] in DCAResult

    -- License metadata
    license_type            VARCHAR(100)    NOT NULL,
    license_status          VARCHAR(50)     NOT NULL,

    -- Dates — stored as DATE, matches Python date type in DCAResult
    original_issue_date     DATE            NOT NULL,
    expiration_date         DATE            NOT NULL,

    -- Derived field — Postgres computes this automatically on every read.
    -- Mirrors DCAResult.is_valid: status == "Current" and not expired.
    -- STORED means it's physically saved and can be indexed (Phase 6+).
    is_valid                BOOLEAN         GENERATED ALWAYS AS (
                                license_status = 'Current'
                                AND expiration_date >= CURRENT_DATE
                            ) STORED

);


-- ─── Indexes ─────────────────────────────────────────────────────────────────
-- The query in dca_reader.py looks up by last_name + first_name.
-- Without an index this is a full table scan O(n) on 300k+ rows.
-- With this index Postgres uses a B-tree lookup O(log n).
-- This is exactly what EXPLAIN ANALYZE will prove in ticket 3H.

CREATE INDEX IF NOT EXISTS idx_physicians_name
    ON physicians (last_name, first_name);

-- Secondary index on license_status for fast is_valid filtering
CREATE INDEX IF NOT EXISTS idx_physicians_status
    ON physicians (license_status);