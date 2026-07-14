-- Controle granular de retorno da galvanizacao por carga, proposta e item.
-- Mantem cargas antigas compatíveis e registra novas operacoes sem alterar o fluxo historico.

CREATE TABLE IF NOT EXISTS cargas_galvanizacao_item_detalhes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    carga_id INTEGER NOT NULL,
    carga_item_id INTEGER NOT NULL,
    processo_id INTEGER NOT NULL,
    proposta_item_id INTEGER NOT NULL,
    numero_item TEXT,
    codigo_produto TEXT,
    descricao TEXT,
    quantidade_enviada REAL NOT NULL DEFAULT 0 CHECK (quantidade_enviada >= 0),
    quantidade_retornada REAL NOT NULL DEFAULT 0 CHECK (quantidade_retornada >= 0),
    peso_unitario REAL NOT NULL DEFAULT 0 CHECK (peso_unitario >= 0),
    peso_enviado REAL NOT NULL DEFAULT 0 CHECK (peso_enviado >= 0),
    peso_retornado REAL NOT NULL DEFAULT 0 CHECK (peso_retornado >= 0),
    status_retorno TEXT NOT NULL DEFAULT 'AGUARDANDO_RETORNO'
        CHECK (status_retorno IN ('AGUARDANDO_RETORNO', 'RETORNO_PARCIAL', 'RETORNADO')),
    legado INTEGER NOT NULL DEFAULT 0 CHECK (legado IN (0, 1)),
    criado_em TEXT,
    atualizado_em TEXT,
    UNIQUE(carga_id, processo_id, proposta_item_id),
    FOREIGN KEY(carga_id) REFERENCES cargas_galvanizacao(id) ON DELETE CASCADE,
    FOREIGN KEY(carga_item_id) REFERENCES cargas_galvanizacao_itens(id) ON DELETE CASCADE,
    FOREIGN KEY(processo_id) REFERENCES processos(id) ON DELETE CASCADE,
    FOREIGN KEY(proposta_item_id) REFERENCES proposta_itens(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS retornos_galvanizacao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    carga_id INTEGER NOT NULL,
    data_retorno TEXT NOT NULL,
    registrado_por TEXT NOT NULL,
    computador TEXT,
    observacao TEXT,
    criado_em TEXT NOT NULL,
    FOREIGN KEY(carga_id) REFERENCES cargas_galvanizacao(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS retornos_galvanizacao_itens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    retorno_id INTEGER NOT NULL,
    carga_id INTEGER NOT NULL,
    carga_item_id INTEGER NOT NULL,
    processo_id INTEGER NOT NULL,
    proposta_item_id INTEGER NOT NULL,
    quantidade_retornada REAL NOT NULL DEFAULT 0 CHECK (quantidade_retornada > 0),
    peso_retornado REAL NOT NULL DEFAULT 0 CHECK (peso_retornado >= 0),
    retorno_total_item INTEGER NOT NULL DEFAULT 0 CHECK (retorno_total_item IN (0, 1)),
    criado_em TEXT NOT NULL,
    FOREIGN KEY(retorno_id) REFERENCES retornos_galvanizacao(id) ON DELETE CASCADE,
    FOREIGN KEY(carga_id) REFERENCES cargas_galvanizacao(id) ON DELETE CASCADE,
    FOREIGN KEY(carga_item_id) REFERENCES cargas_galvanizacao_itens(id) ON DELETE CASCADE,
    FOREIGN KEY(processo_id) REFERENCES processos(id) ON DELETE CASCADE,
    FOREIGN KEY(proposta_item_id) REFERENCES proposta_itens(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_carga_galv_detalhes_carga
    ON cargas_galvanizacao_item_detalhes(carga_id);

CREATE INDEX IF NOT EXISTS ix_carga_galv_detalhes_processo
    ON cargas_galvanizacao_item_detalhes(processo_id);

CREATE INDEX IF NOT EXISTS ix_carga_galv_detalhes_item
    ON cargas_galvanizacao_item_detalhes(proposta_item_id);

CREATE INDEX IF NOT EXISTS ix_carga_galv_detalhes_status
    ON cargas_galvanizacao_item_detalhes(status_retorno);

CREATE INDEX IF NOT EXISTS ix_retornos_galvanizacao_carga
    ON retornos_galvanizacao(carga_id);

CREATE INDEX IF NOT EXISTS ix_retornos_galvanizacao_itens_retorno
    ON retornos_galvanizacao_itens(retorno_id);

CREATE INDEX IF NOT EXISTS ix_retornos_galvanizacao_itens_processo
    ON retornos_galvanizacao_itens(processo_id);
