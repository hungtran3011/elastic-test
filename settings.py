import os

try:
    from dotenv import load_dotenv

    # Make local .env the single source of truth for dev runs.
    # This avoids surprises when ELASTICSEARCH_URL or other vars are set globally.
    load_dotenv(override=True)
except Exception:
    # dotenv is optional at runtime; environment variables may be provided by the shell instead.
    pass


def getenv_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def getenv_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


ELASTICSEARCH_URL = os.getenv("ELASTICSEARCH_URL", "http://localhost:9201")

# Cốc Cốc Tokenizer microservice URL (Docker Compose runs at tokenizer:1880)
TOKENIZER_URL = os.getenv("TOKENIZER_URL", "http://localhost:1880")
USE_COCCOC_TOKENIZER = getenv_bool("USE_COCCOC_TOKENIZER", True)  # Enable for better Vietnamese search

# Single source of truth for the index used by both scraper + web app.
INDEX_NAME = os.getenv("INDEX_NAME", "demonstration-2")
INDEX_CONFIG_JSON = os.getenv("INDEX_CONFIG_JSON", "index-config.json")

SCRAPE_BASE_URL = os.getenv("SCRAPE_BASE_URL", "https://truyenfull.vision")
SCRAPE_LIST_FILE = os.getenv("SCRAPE_LIST_FILE", "list.txt")

# Scheduler cadence (minutes). Keep conservative by default.
SCRAPE_INTERVAL_MINUTES = getenv_int("SCRAPE_INTERVAL_MINUTES", 60)

# If you run crawling as a separate process, set this to false.
ENABLE_WEB_SCHEDULER = getenv_bool("ENABLE_WEB_SCHEDULER", True)

# Optional Supabase persistence.
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Table names (override if your Supabase schema differs)
SUPABASE_STORIES_TABLE = os.getenv("SUPABASE_STORIES_TABLE", "stories")
SUPABASE_CHAPTERS_TABLE = os.getenv("SUPABASE_CHAPTERS_TABLE", "chapters")
