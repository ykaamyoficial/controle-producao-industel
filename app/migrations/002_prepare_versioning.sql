-- A tabela tambem e criada pelo bootstrap do executor para que a primeira
-- migracao possa ser registrada. O IF NOT EXISTS torna a operacao segura.

CREATE TABLE IF NOT EXISTS schema_migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version INTEGER NOT NULL UNIQUE,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    checksum TEXT NOT NULL
);
