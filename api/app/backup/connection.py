from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse


class InvalidDatabaseUrlError(ValueError):
    pass


@dataclass(frozen=True)
class PgConnectionParams:
    """Parametros libpq extraidos de DATABASE_URL (asyncpg), para uso por
    pg_dump/pg_restore (processos externos que nao entendem 'postgresql+asyncpg://').

    A senha nunca e exposta via __str__/__repr__ default do dataclass -- ver
    sanitize_for_log() e env(), os unicos jeitos seguros de usar self.password.
    """

    host: str
    port: int
    user: str
    password: str
    dbname: str

    def as_args(self) -> list[str]:
        """Argumentos de conexao seguros para linha de comando (nunca inclui a senha)."""
        return ["-h", self.host, "-p", str(self.port), "-U", self.user]

    def env(self, *, base: dict[str, str] | None = None) -> dict[str, str]:
        """Ambiente do subprocesso com PGPASSWORD -- nunca em argv, nunca em log."""
        merged = dict(base if base is not None else os.environ)
        merged["PGPASSWORD"] = self.password
        return merged

    def sanitize_for_log(self, text: str) -> str:
        """Remove qualquer ocorrencia literal da senha de uma string antes de logar."""
        if not self.password:
            return text
        return text.replace(self.password, "[redigido]")


def parse_database_url(database_url: str) -> PgConnectionParams:
    """Converte DATABASE_URL (postgresql+asyncpg://user:pass@host:port/db) em
    parametros libpq. Nao loga a URL de entrada em caso de erro (pode conter senha)."""
    if not database_url or not database_url.strip():
        raise InvalidDatabaseUrlError("DATABASE_URL nao configurada.")
    normalized = re.sub(r"^postgresql\+[a-z0-9_]+://", "postgresql://", database_url.strip())
    parsed = urlparse(normalized)
    if parsed.scheme != "postgresql":
        raise InvalidDatabaseUrlError("DATABASE_URL deve ser uma URL postgresql://.")
    dbname = parsed.path.lstrip("/")
    if not parsed.hostname or not dbname:
        raise InvalidDatabaseUrlError("DATABASE_URL sem host ou nome de banco.")
    return PgConnectionParams(
        host=parsed.hostname,
        port=parsed.port or 5432,
        user=parsed.username or "",
        password=parsed.password or "",
        dbname=dbname,
    )
