-- =============================================================
-- Migration 009: Auth Tables Documentation + KV Store
-- =============================================================
-- The user/role tables ALREADY EXIST in the RDS public schema,
-- created by the local_vqm backend. This migration documents
-- their schema for developer reference and uses CREATE TABLE
-- IF NOT EXISTS so it is safe to run but will NOT modify
-- existing data.
--
-- Also creates cache.kv_store — a generic key-value cache table
-- used for JWT token blacklisting and other short-lived data.
-- =============================================================

-- --- Auth tables (documentation — already exist in RDS) ---

CREATE TABLE IF NOT EXISTS public.tbl_users (
    id              SERIAL PRIMARY KEY,
    user_name       VARCHAR(255) UNIQUE NOT NULL,
    email_id        VARCHAR(255) UNIQUE NOT NULL,
    tenant          VARCHAR(255) NOT NULL,
    password        VARCHAR(512) NOT NULL,
    status          VARCHAR(50) DEFAULT 'ACTIVE',
    security_q1     VARCHAR(512),
    security_a1     VARCHAR(512),
    security_q2     VARCHAR(512),
    security_a2     VARCHAR(512),
    security_q3     VARCHAR(512),
    security_a3     VARCHAR(512)
);

CREATE TABLE IF NOT EXISTS public.tbl_user_roles (
    slno            SERIAL PRIMARY KEY,
    first_name      VARCHAR(255),
    last_name       VARCHAR(255),
    email_id        VARCHAR(255),
    user_name       VARCHAR(255),
    tenant          VARCHAR(255),
    role            VARCHAR(100),
    created_by      VARCHAR(255),
    created_date    TIMESTAMP,
    modified_by     VARCHAR(255),
    modified_date   TIMESTAMP,
    deleted_by      VARCHAR(255),
    deleted_date    TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tbl_users_email ON public.tbl_users (email_id);
CREATE INDEX IF NOT EXISTS idx_tbl_users_status ON public.tbl_users (status);
CREATE INDEX IF NOT EXISTS idx_tbl_user_roles_username ON public.tbl_user_roles (user_name);
CREATE INDEX IF NOT EXISTS idx_tbl_user_roles_tenant ON public.tbl_user_roles (tenant);

-- --- Generic KV cache table (new — for token blacklist) ---

CREATE TABLE IF NOT EXISTS cache.kv_store (
    id              SERIAL PRIMARY KEY,
    key             VARCHAR(512) NOT NULL UNIQUE,
    value           TEXT NOT NULL DEFAULT '',
    cached_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_kv_store_key ON cache.kv_store (key);
CREATE INDEX IF NOT EXISTS idx_kv_store_expires ON cache.kv_store (expires_at);
