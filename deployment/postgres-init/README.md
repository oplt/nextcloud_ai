# Postgres init scripts

Mounted into Postgres as `/docker-entrypoint-initdb.d` on **fresh** volumes only.

- `01-vector.sql` — `CREATE EXTENSION IF NOT EXISTS vector`

Alembic also ensures the extension (`00c7539a7dcd`, `a1b2c3d4e5f6`) for existing volumes and production starts. The root-owned `deployment/postgres/init` path is unused; prefer this directory.
