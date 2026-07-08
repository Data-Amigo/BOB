from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import Connection

# Load .env from the project root (3 levels up from this file: db/ → ganji_mtaani_agent/ → src/ → root)
load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=True)


def _connection_string() -> str:
    """Return the best available connection string.

    Priority:
      1. DATABASE_URL        — Railway / any hosted provider (single URL)
      2. POSTGRES_*          — vars actually present in .env
      3. GANJI_POSTGRES_*    — legacy naming kept for backwards compat
    """
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        # psycopg3 accepts postgresql:// and postgres:// URIs directly.
        # Railway sometimes emits 'postgres://' — normalise to 'postgresql://'
        return url.replace("postgres://", "postgresql://", 1)

    # Try POSTGRES_* first (matches the actual .env variable names)
    host     = (os.getenv("POSTGRES_HOST")     or os.getenv("GANJI_POSTGRES_HOST")     or "localhost")
    port     = (os.getenv("POSTGRES_PORT")     or os.getenv("GANJI_POSTGRES_PORT")     or "5432")
    database = (os.getenv("POSTGRES_DB")       or os.getenv("GANJI_POSTGRES_DB")       or "ganji_mtaani")
    user     = (os.getenv("POSTGRES_USER")     or os.getenv("GANJI_POSTGRES_USER")     or "postgres")
    password = (os.getenv("POSTGRES_PASSWORD") or os.getenv("GANJI_POSTGRES_PASSWORD") or "postgres")
    return f"host={host} port={port} dbname={database} user={user} password={password}"


def get_postgres_connection(
    config=None,   # kept for backwards-compatibility; ignored when DATABASE_URL is set
    *,
    autocommit: bool = False,
) -> Connection:
    """Open a PostgreSQL connection.

    Uses DATABASE_URL from the environment when available (Railway, etc.),
    otherwise falls back to individual GANJI_POSTGRES_* variables.
    """
    if config is not None and not os.getenv("DATABASE_URL", "").strip():
        # Legacy path: explicit PostgresConfig passed in and no DATABASE_URL
        connstr = config.dsn()
    else:
        connstr = _connection_string()

    connection = psycopg.connect(connstr)
    connection.autocommit = autocommit
    return connection


# ---------------------------------------------------------------------------
# Keep PostgresConfig for any code that still imports it directly
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PostgresConfig:
    host: str = "localhost"
    port: int = 5432
    database: str = "ganji_mtaani"
    user: str = "postgres"
    password: str = "postgres"

    @classmethod
    def from_env(cls) -> "PostgresConfig":
        return cls(
            host=os.getenv("GANJI_POSTGRES_HOST", "localhost"),
            port=int(os.getenv("GANJI_POSTGRES_PORT", "5432")),
            database=os.getenv("GANJI_POSTGRES_DB", "ganji_mtaani"),
            user=os.getenv("GANJI_POSTGRES_USER", "postgres"),
            password=os.getenv("GANJI_POSTGRES_PASSWORD", "postgres"),
        )

    def dsn(self) -> str:
        return (
            f"host={self.host} port={self.port} dbname={self.database} "
            f"user={self.user} password={self.password}"
        )
