-- Migration 001: Create all database schemas
-- VQMS uses 6 schema namespaces to organize tables by domain

CREATE SCHEMA IF NOT EXISTS intake;
CREATE SCHEMA IF NOT EXISTS workflow;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS memory;
CREATE SCHEMA IF NOT EXISTS reporting;
CREATE SCHEMA IF NOT EXISTS cache;
