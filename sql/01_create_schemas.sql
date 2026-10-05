-- =============================================================================
-- Emergency Route Intelligence Warehouse (DWM Project)
-- Script 01: Schema Setup
-- Database Target: PostgreSQL / Cloud Supabase
-- =============================================================================

-- Create dedicated schemas to strictly separate raw staging from the warehouse
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS warehouse;

COMMENT ON SCHEMA staging IS 'Staging area for raw, untransformed CSV ingestion';
COMMENT ON SCHEMA warehouse IS 'Dimensional model star schema containing conformed dimensions and fact tables';
