-- Splits PPC's single "weight" field into gross fed-in weight and processing loss,
-- matching the report's formula: PPC = (M_processed - M_wasted) x W(t) x P x G.
-- Previously the dashboard had one "Weight Processed" field, which is ambiguous —
-- a user could reasonably enter the gross mass fed into the process rather than
-- the net mass converted, overstating credits (e.g. entering 250 instead of the
-- correct 200 in the worked example overstates the PPC by 25%).
--
-- `weight` keeps its existing meaning (net PET converted to product) so every
-- downstream calculation (PPC formula, CO2 savings, summaries, reports) is
-- unaffected. The two new columns are additive, for transparency/audit only.
-- Run this in the Supabase SQL editor after 001 and 002.

ALTER TABLE ppc_entries
  ADD COLUMN IF NOT EXISTS weight_gross DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS weight_wasted DOUBLE PRECISION;

-- weight_gross  = PET mass fed into the processing unit (tonnes)
-- weight_wasted = sorting/processing loss (tonnes)
-- weight        = weight_gross - weight_wasted (net PET converted — what PPC is computed on)
-- Both new columns are NULL for entries created before this migration.
