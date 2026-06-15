CREATE TABLE IF NOT EXISTS proposta_importacoes_pdf (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    processo_id INTEGER NOT NULL UNIQUE,
    origem TEXT NOT NULL,
    nome_arquivo TEXT NOT NULL,
    hash_sha256 TEXT NOT NULL UNIQUE,
    importado_em TEXT NOT NULL,
    importado_por TEXT NOT NULL,
    observacao TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(processo_id) REFERENCES processos(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_proposta_importacoes_pdf_hash
ON proposta_importacoes_pdf(hash_sha256);
