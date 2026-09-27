# Database migrations

`001_initial_schema.sql` defines the normalized core schema and internal/member-safe FTS5 indexes. Migrations use an ascending numeric filename prefix and are tracked by SHA-256 checksum. Applied migration files are immutable; make schema changes in a new higher-numbered migration.