-- Migration: Add directory column to projects table
-- Date: 2026-03-29
-- Purpose: Store the filesystem directory path for each project,
--          enabling the file tree endpoint to resolve where project files live.

ALTER TABLE projects ADD COLUMN directory TEXT DEFAULT NULL;
