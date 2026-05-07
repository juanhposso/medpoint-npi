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
    license_number          TEXT    PRIMARY KEY,

    -- Name fields — match DCAResult exactly
    last_name               TEXT    NOT NULL,
    first_name              TEXT    NOT NULL,
    middle_name             TEXT,   -- nullable: Optional[str] in DCAResult

    -- License metadata
    license_type            TEXT    NOT NULL,
    license_status          TEXT    NOT NULL,

    -- Dates — stored as DATE, matches Python date type in DCAResult
    original_issue_date     DATE            NOT NULL,
    expiration_date         DATE            NOT NULL

    -- is_valid is NOT stored in the database.
    -- It depends on CURRENT_DATE which changes daily — cannot be a generated column.
    -- Computed in Python by _row_to_dca_result() in dca_reader.py.

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