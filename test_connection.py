"""
test_connection.py
------------------
Location : C:\\Users\\harsh\\Downloads\\data\\test_connection.py
Purpose  : READ-ONLY Supabase / PostgreSQL connection test.

What this script does:
  1. Load SUPABASE_DB_URL from the .env file in the same directory.
  2. Connect to PostgreSQL.
  3. Print whether the connection succeeded.
  4. If connected, list existing schemas and tables.

What this script does NOT do:
  - No CREATE, INSERT, UPDATE, DELETE, ALTER, DROP, or TRUNCATE.
  - No schema or data modifications of any kind.
"""

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. Load .env from the same directory as this script
# ---------------------------------------------------------------------------
ENV_PATH = Path(__file__).parent / ".env"

if not ENV_PATH.exists():
    print(f"ERROR: .env file not found at {ENV_PATH}")
    sys.exit(1)

env_vars = {}
with open(ENV_PATH, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env_vars[key.strip()] = value.strip()

for k, v in env_vars.items():
    os.environ.setdefault(k, v)

DB_URL = env_vars.get("SUPABASE_DB_URL") or env_vars.get("DATABASE_URL")

if not DB_URL:
    print("ERROR: SUPABASE_DB_URL not found in .env")
    sys.exit(1)

# Mask password for display
try:
    pwd_part = DB_URL.split(":")[2].split("@")[0]
    masked_url = DB_URL.replace(pwd_part, "****")
except Exception:
    masked_url = "<could not mask>"

print("=" * 60)
print("Supabase / PostgreSQL Connection Test")
print("=" * 60)
print(f"  .env path : {ENV_PATH}")
print(f"  URL       : {masked_url}")
print()

# ---------------------------------------------------------------------------
# 2. Import driver (psycopg v3 preferred, psycopg2 as fallback)
# ---------------------------------------------------------------------------
psycopg = None
driver = None

try:
    import psycopg as psycopg
    driver = "psycopg (v3)"
except ImportError:
    try:
        import psycopg2 as psycopg
        driver = "psycopg2 (v2)"
    except ImportError:
        print("ERROR: Neither 'psycopg' (v3) nor 'psycopg2' is installed.")
        print('  Fix: pip install "psycopg[binary]"')
        sys.exit(1)

print(f"  Driver    : {driver}")
print()

# ---------------------------------------------------------------------------
# 3. Connect
# ---------------------------------------------------------------------------
print("Connecting ...", end=" ", flush=True)
try:
    conn = psycopg.connect(DB_URL, connect_timeout=15)
    print("SUCCESS\n")
except Exception as exc:
    print("FAILED")
    print(f"  Error: {exc}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# 4. Verify — server version (read-only SELECT)
# ---------------------------------------------------------------------------
with conn.cursor() as cur:
    cur.execute("SELECT version();")
    server_version = cur.fetchone()[0]

print(f"Server version:\n  {server_version}\n")

# ---------------------------------------------------------------------------
# 5. List all user-visible schemas and tables (read-only catalog query)
# ---------------------------------------------------------------------------
with conn.cursor() as cur:
    cur.execute("""
        SELECT
            table_schema,
            table_name,
            table_type
        FROM information_schema.tables
        WHERE table_schema NOT IN (
            'information_schema', 'pg_catalog', 'pg_toast'
        )
        ORDER BY table_schema, table_name;
    """)
    rows = cur.fetchall()

print("Schemas / Tables visible to this user:")
print("-" * 45)
if rows:
    current_schema = None
    for schema, table_name, table_type in rows:
        if schema != current_schema:
            print(f"\n  Schema: {schema}")
            current_schema = schema
        label = "VIEW" if table_type == "VIEW" else "TABLE"
        print(f"    [{label}]  {table_name}")
else:
    print("  (none — no user tables found; clean slate)")

print()

# ---------------------------------------------------------------------------
# Safety confirmation
# ---------------------------------------------------------------------------
print("=" * 60)
print("SAFETY CONFIRMATION")
print("  No CREATE, ALTER, DROP executed.")
print("  No INSERT, UPDATE, DELETE executed.")
print("  Database and schema are untouched.")
print("=" * 60)

conn.close()
print("\nConnection closed. Test complete.")
