CREATE TABLE IF NOT EXISTS fiscal_processos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    processo_id INTEGER NOT NULL UNIQUE,
    proposta TEXT NOT NULL,
    status_fiscal TEXT NOT NULL DEFAULT 'FALTA_EMITIR_NOTA_FISCAL'
        CHECK (status_fiscal IN (
            'FALTA_EMITIR_NOTA_FISCAL',
            'NOTA_FISCAL_PARCIAL',
            'NOTA_FISCAL_EMITIDA',
            'FISCAL_CANCELADO'
        )),
    data_entrada_fiscal TEXT NOT NULL,
    data_ultima_emissao TEXT,
    emitido_por TEXT,
    observacao TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(processo_id) REFERENCES processos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS fiscal_itens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fiscal_processo_id INTEGER NOT NULL,
    processo_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    numero_item TEXT NOT NULL,
    descricao TEXT,
    quantidade_total REAL NOT NULL DEFAULT 0 CHECK (quantidade_total >= 0),
    quantidade_faturada REAL NOT NULL DEFAULT 0 CHECK (quantidade_faturada >= 0),
    peso_total REAL NOT NULL DEFAULT 0 CHECK (peso_total >= 0),
    peso_faturado REAL NOT NULL DEFAULT 0 CHECK (peso_faturado >= 0),
    status_item_fiscal TEXT NOT NULL DEFAULT 'PENDENTE'
        CHECK (status_item_fiscal IN ('PENDENTE', 'PARCIAL', 'FATURADO', 'CANCELADO')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (quantidade_faturada <= quantidade_total),
    CHECK (peso_faturado <= peso_total),
    UNIQUE(fiscal_processo_id, item_id),
    FOREIGN KEY(fiscal_processo_id) REFERENCES fiscal_processos(id) ON DELETE CASCADE,
    FOREIGN KEY(processo_id) REFERENCES processos(id) ON DELETE CASCADE,
    FOREIGN KEY(item_id) REFERENCES proposta_itens(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS fiscal_movimentacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fiscal_processo_id INTEGER NOT NULL,
    processo_id INTEGER NOT NULL,
    tipo_movimento TEXT NOT NULL,
    status_anterior TEXT,
    status_novo TEXT NOT NULL,
    usuario TEXT NOT NULL,
    data_hora TEXT NOT NULL,
    observacao TEXT,
    FOREIGN KEY(fiscal_processo_id) REFERENCES fiscal_processos(id) ON DELETE CASCADE,
    FOREIGN KEY(processo_id) REFERENCES processos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS fiscal_emissoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fiscal_processo_id INTEGER NOT NULL,
    numero_controle TEXT,
    tipo_emissao TEXT NOT NULL,
    data_emissao TEXT NOT NULL,
    usuario TEXT NOT NULL,
    observacao TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(fiscal_processo_id) REFERENCES fiscal_processos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS fiscal_emissao_itens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fiscal_emissao_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    quantidade_emitida REAL NOT NULL DEFAULT 0 CHECK (quantidade_emitida >= 0),
    peso_emitido REAL NOT NULL DEFAULT 0 CHECK (peso_emitido >= 0),
    created_at TEXT NOT NULL,
    FOREIGN KEY(fiscal_emissao_id) REFERENCES fiscal_emissoes(id) ON DELETE CASCADE,
    FOREIGN KEY(item_id) REFERENCES fiscal_itens(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_fiscal_processos_processo_id
ON fiscal_processos(processo_id);

CREATE INDEX IF NOT EXISTS ix_fiscal_processos_status_fiscal
ON fiscal_processos(status_fiscal);

CREATE INDEX IF NOT EXISTS ix_fiscal_processos_data_entrada
ON fiscal_processos(data_entrada_fiscal);

CREATE INDEX IF NOT EXISTS ix_fiscal_itens_fiscal_processo_id
ON fiscal_itens(fiscal_processo_id);

CREATE INDEX IF NOT EXISTS ix_fiscal_itens_processo_id
ON fiscal_itens(processo_id);

CREATE INDEX IF NOT EXISTS ix_fiscal_itens_status_item_fiscal
ON fiscal_itens(status_item_fiscal);

CREATE INDEX IF NOT EXISTS ix_fiscal_movimentacoes_fiscal_processo_id
ON fiscal_movimentacoes(fiscal_processo_id);

CREATE INDEX IF NOT EXISTS ix_fiscal_movimentacoes_processo_id
ON fiscal_movimentacoes(processo_id);

CREATE INDEX IF NOT EXISTS ix_fiscal_emissoes_fiscal_processo_id
ON fiscal_emissoes(fiscal_processo_id);

CREATE INDEX IF NOT EXISTS ix_fiscal_emissao_itens_item_id
ON fiscal_emissao_itens(item_id);
