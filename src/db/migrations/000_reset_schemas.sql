-- Migration 000: Reset all VQMS schemas for clean Phase 1 setup
-- WARNING: This drops all existing tables in VQMS schemas
-- Only run this during initial development setup

DROP SCHEMA IF EXISTS intake CASCADE;
DROP SCHEMA IF EXISTS workflow CASCADE;
DROP SCHEMA IF EXISTS audit CASCADE;
DROP SCHEMA IF EXISTS memory CASCADE;
DROP SCHEMA IF EXISTS reporting CASCADE;
DROP SCHEMA IF EXISTS cache CASCADE;
