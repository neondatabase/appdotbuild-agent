-- Database initialization script
-- This file runs when the PostgreSQL container starts for the first time

-- Enable UUID extension for generating UUIDs
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create the application database if it doesn't exist
-- (Note: This is not needed if POSTGRES_DB is set, but good for reference)
-- CREATE DATABASE app_db;

-- You can add initial data or additional configuration here
-- For example:
-- INSERT INTO some_table (column1, column2) VALUES ('value1', 'value2');