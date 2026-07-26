-- Adds coordinate-based verification to pcc_entries.
-- Run once in the Supabase SQL editor (or via psql against DATABASE_URL) before
-- deploying the updated app.py / dashboard.html.

ALTER TABLE pcc_entries
  ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS lon DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS verified BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS evidence TEXT;

-- verified   = TRUE  when category was assigned by geo_classifier.classify() from lat/lon
--            = FALSE when the company used the manual category dropdown (no coordinates)
-- evidence   = newline-joined evidence trail returned by the classifier (NULL for unverified rows)
-- lat/lon    = NULL for unverified rows
