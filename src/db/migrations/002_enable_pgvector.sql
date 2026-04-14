-- Migration 002: Enable pgvector extension for vector similarity search
-- Required for KB article embedding storage and cosine similarity queries
-- Note: RDS may not have a public schema, so we create it if needed

CREATE SCHEMA IF NOT EXISTS public;
CREATE EXTENSION IF NOT EXISTS vector SCHEMA public;
