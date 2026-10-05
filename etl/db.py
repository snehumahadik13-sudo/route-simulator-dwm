import sys
from pathlib import Path
from .config import get_connection_string

try:
    import psycopg
    from psycopg import sql
except ImportError:
    psycopg = None

def get_connection():
    if psycopg is None:
        raise RuntimeError("The 'psycopg' library is not installed. Please run: pip install 'psycopg[binary]'")
    conn_str = get_connection_string()
    return psycopg.connect(conn_str)

def inspect_database(conn):
    """
    Inspects existing database schemas and tables to guarantee non-destructive execution.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_schema, table_name, table_type
            FROM information_schema.tables
            WHERE table_schema NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
            ORDER BY table_schema, table_name;
        """)
        tables = cur.fetchall()
        
    print("\n--- Current Database Inspection ---")
    if not tables:
        print("No user tables found in database. Clean slate detected.")
    else:
        print(f"Found {len(tables)} existing table(s):")
        for schema, name, ttype in tables:
            print(f"  [{schema}] {name} ({ttype})")
    print("------------------------------------\n")
    return tables

def execute_sql_file(conn, filepath: Path):
    """
    Safely executes DDL commands from a SQL script file.
    """
    if not filepath.exists():
        raise FileNotFoundError(f"SQL file not found: {filepath}")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        sql_commands = f.read()
    
    with conn.cursor() as cur:
        cur.execute(sql_commands)
    conn.commit()
    print(f"Executed: {filepath.name}")

def batch_insert(conn, insert_sql: str, rows: list):
    """
    Executes an efficient batch insert using psycopg cursor.executemany.
    """
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(insert_sql, rows)
    conn.commit()
