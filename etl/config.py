import os
from pathlib import Path

# Load environment variables if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR)))
SQL_DIR = BASE_DIR / "sql"

# Source File Names
FILES = {
    "traffic": "vanet_traffic_data.csv",
    "weather": "india_2000_2024_daily_weather.csv",
    "accidents_roads": "indian_roads_dataset.csv",
    "accidents_roads_dup": "indian_roads_dataset (2).csv",
    "hospital": "PMC Hospital Infrastructure (1).csv",
    "ems": "ems_events_20000.csv"
}

# =============================================================================
# Supabase / PostgreSQL Configuration
# =============================================================================
# Example Supabase pooled connection string:
# postgresql://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
# Direct connection string:
# postgresql://postgres:[password]@db.[project-ref].supabase.co:5432/postgres
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL")

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "postgres")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

def get_connection_string():
    if DATABASE_URL:
        return DATABASE_URL
    if DB_PASSWORD:
        return f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    return f"postgresql://{DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# =============================================================================
# Supabase API Configuration
# =============================================================================
# Project REST API base URL
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://cnfzuamfilxppnmdmfce.supabase.co")

# Publishable key  — safe for client-side / public use
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")

# Secret key  — server-side only; never expose in client code
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "")

# Service Role JWT — bypasses RLS; server-side only
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

# Anon / Public JWT — respects RLS; safe for client-side use
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")

# Batch sizes for ingestion
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "5000"))
