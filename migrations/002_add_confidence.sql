-- Adds a confidence tag to verified pcc_entries: "regulatory" (backed entirely by
-- official notified boundaries — ESZ/Protected Area) vs "heuristic" (F factor still
-- relies on the 500m river buffer / coastline-distance proxy, since no official
-- CRZ or RRZ boundary layer has been sourced yet — see geo_classifier.py docstring).
-- Run this in the Supabase SQL editor after 001_add_geo_verification.sql.

ALTER TABLE pcc_entries
  ADD COLUMN IF NOT EXISTS confidence TEXT;

-- confidence = NULL for unverified (manually declared) rows
-- confidence = 'regulatory' or 'heuristic' for verified (geo-classified) rows
