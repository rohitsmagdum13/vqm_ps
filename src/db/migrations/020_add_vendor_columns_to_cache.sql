-- Migration 020: Add dedicated vendor columns to cache.vendor_cache.
--
-- Reason: Auth verification, routing, and analytics need to read
-- vendor_name, vendor_tier, and vendor_category cheaply without
-- parsing the cache_data JSONB blob on every request. Promoting
-- them to top-level columns also makes manual DB inspection and
-- ad-hoc reporting straightforward.
--
-- Backwards compatible: cache_data JSONB column is preserved as
-- the source of truth for the full profile. Code may still read
-- from cache_data; the new columns are a denormalized projection.

ALTER TABLE cache.vendor_cache
    ADD COLUMN IF NOT EXISTS vendor_name     VARCHAR(255),
    ADD COLUMN IF NOT EXISTS vendor_tier     VARCHAR(50),
    ADD COLUMN IF NOT EXISTS vendor_category VARCHAR(100);

-- Indexes to support routing + reporting queries that filter
-- by tier or category without touching the JSONB blob.
CREATE INDEX IF NOT EXISTS idx_vendor_cache_tier
    ON cache.vendor_cache(vendor_tier);
CREATE INDEX IF NOT EXISTS idx_vendor_cache_category
    ON cache.vendor_cache(vendor_category);
