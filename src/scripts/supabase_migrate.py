"""Apply Supabase SQL migrations.

Reads `supabase/migrations/*.sql` in lexical order and applies any not
yet recorded in the `_schema_migrations` tracking table. Idempotent.
The actual runner lives in
`ai_platform.workspace.storage.structured.supabase.apply_migrations`
so the integration-test fixture can reuse it.

Run via the bash wrapper, which loads `.env` and sets `PYTHONPATH=src`:

    ./scripts/supabase-migrate.sh
    ./scripts/supabase-migrate.sh --schema test   # for an isolated test schema

Or directly (e.g. inside docker), assuming env + PYTHONPATH are set:

    python -m scripts.supabase_migrate

Reads `SUPABASE_CONNECTION_STRING` from `.env`.
"""
from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

from ai_platform.workspace.storage.structured.supabase import apply_migrations

load_dotenv()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--schema",
        default=None,
        help="Apply migrations into a named schema instead of public. "
             "Creates the schema if missing. Used by integration tests.",
    )
    args = parser.parse_args()

    conn_str = os.environ["SUPABASE_CONNECTION_STRING"]
    where = f"schema {args.schema!r}" if args.schema else "schema 'public'"
    print(f"[supabase-migrate] applying to {where}")

    applied = apply_migrations(conn_str, schema=args.schema)
    if applied == 0:
        print("Up to date.")
    else:
        print(f"Done — {applied} migration(s) applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
