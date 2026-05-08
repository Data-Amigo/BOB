from __future__ import annotations

import os
from dataclasses import dataclass

import psycopg
from psycopg import Connection


# =============================================================================
# PostgreSQL Connection Configuration
# =============================================================================
# This module keeps database connection details in one place so the rest of the
# app can ask for a connection without repeating host, port, and credential
# logic everywhere.
@dataclass(frozen=True, slots=True)
class PostgresConfig:
    """Simple PostgreSQL connection settings for the local Docker database."""

    host: str = "localhost"
    port: int = 5432
    database: str = "ganji_mtaani"
    user: str = "postgres"
    password: str = "postgres"

    @classmethod
    def from_env(cls) -> "PostgresConfig":
        """Build configuration from environment variables when available."""

        return cls(
            host=os.getenv("GANJI_POSTGRES_HOST", "localhost"),
            port=int(os.getenv("GANJI_POSTGRES_PORT", "5432")),
            database=os.getenv("GANJI_POSTGRES_DB", "ganji_mtaani"),
            user=os.getenv("GANJI_POSTGRES_USER", "postgres"),
            password=os.getenv("GANJI_POSTGRES_PASSWORD", "postgres"),
        )

    def dsn(self) -> str:
        """Return a psycopg-compatible DSN string."""

        return (
            f"host={self.host} port={self.port} dbname={self.database} "
            f"user={self.user} password={self.password}"
        )


def get_postgres_connection(
    config: PostgresConfig | None = None,
    *,
    autocommit: bool = False,
) -> Connection:
    """Open a PostgreSQL connection using repo defaults or env overrides."""

    selected_config = config or PostgresConfig.from_env()
    connection = psycopg.connect(selected_config.dsn())
    connection.autocommit = autocommit
    return connection
