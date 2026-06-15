-- Baseline do esquema existente antes do sistema de migracoes numeradas.
-- Esta migracao e idempotente para bancos ja existentes.

CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    login TEXT NOT NULL UNIQUE,
    senha_salt TEXT NOT NULL,
    senha_hash TEXT NOT NULL,
    perfil TEXT NOT NULL DEFAULT 'operador',
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL,
    areas_acesso TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS processos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente TEXT NOT NULL,
    proposta TEXT NOT NULL UNIQUE,
    pedido_compra TEXT,
    obra_site TEXT,
    peso REAL,
    lote TEXT,
    data_entrada TEXT,
    data_cadastro TEXT NOT NULL,
    prazo_entrega TEXT,
    status_geral TEXT,
    status_producao TEXT,
    data_final_producao TEXT,
    status_galvanizacao TEXT,
    data_envio_galv TEXT,
    data_prevista_retorno_galv TEXT,
    data_retorno_galv TEXT,
    status_expedicao TEXT,
    data_separacao TEXT,
    data_retirada TEXT,
    status_almoxarifado TEXT,
    necessita_almoxarifado TEXT NOT NULL DEFAULT 'NAO_DEFINIDO',
    observacoes_gerais TEXT,
    observacoes_producao TEXT,
    observacoes_galvanizacao TEXT,
    observacoes_expedicao TEXT,
    observacoes_almoxarifado TEXT,
    situacao_fluxo TEXT NOT NULL DEFAULT 'NORMAL',
    tem_pendencia_producao INTEGER NOT NULL DEFAULT 0,
    origem_remanejamento TEXT,
    observacao_remanejamento TEXT,
    processo_pai_id INTEGER,
    tipo_processo TEXT NOT NULL DEFAULT 'PRINCIPAL',
    numero_parcial INTEGER NOT NULL DEFAULT 0,
    peso_parcial REAL,
    saldo_pendente REAL,
    descricao_parcial TEXT,
    atualizado_em TEXT,
    atualizado_por TEXT,
    quantidade_itens INTEGER NOT NULL DEFAULT 0,
    peso_produzido REAL NOT NULL DEFAULT 0,
    peso_entregue REAL NOT NULL DEFAULT 0,
    FOREIGN KEY(processo_pai_id) REFERENCES processos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS status_opcoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    area TEXT NOT NULL,
    nome_status TEXT NOT NULL,
    etapa_atual TEXT NOT NULL,
    proxima_etapa TEXT NOT NULL,
    ordem INTEGER NOT NULL DEFAULT 0,
    ativo INTEGER NOT NULL DEFAULT 1,
    UNIQUE(area, nome_status)
);

CREATE TABLE IF NOT EXISTS historico_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    processo_id INTEGER NOT NULL,
    proposta TEXT NOT NULL,
    area TEXT NOT NULL,
    status_anterior TEXT,
    status_novo TEXT NOT NULL,
    data_hora TEXT NOT NULL,
    usuario TEXT NOT NULL,
    computador TEXT NOT NULL,
    observacao TEXT,
    FOREIGN KEY(processo_id) REFERENCES processos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entidade TEXT NOT NULL,
    entidade_id INTEGER,
    acao TEXT NOT NULL,
    campo TEXT,
    valor_anterior TEXT,
    valor_novo TEXT,
    data_hora TEXT NOT NULL,
    usuario TEXT NOT NULL,
    computador TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bloqueios_edicao (
    processo_id INTEGER PRIMARY KEY,
    usuario TEXT NOT NULL,
    computador TEXT NOT NULL,
    bloqueado_em TEXT NOT NULL,
    FOREIGN KEY(processo_id) REFERENCES processos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS configuracoes (
    chave TEXT PRIMARY KEY,
    valor TEXT
);

CREATE TABLE IF NOT EXISTS cargas_galvanizacao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    motorista TEXT NOT NULL,
    peso_maximo REAL,
    peso_total REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'AGUARDANDO_LIBERACAO',
    data_prevista_retorno TEXT,
    data_retorno TEXT,
    criado_em TEXT NOT NULL,
    criado_por TEXT NOT NULL,
    computador TEXT NOT NULL,
    observacao TEXT
);

CREATE TABLE IF NOT EXISTS cargas_galvanizacao_itens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    carga_id INTEGER NOT NULL,
    processo_id INTEGER NOT NULL,
    proposta TEXT NOT NULL,
    cliente TEXT,
    peso_total_proposta REAL,
    peso_enviado REAL,
    parcial INTEGER NOT NULL DEFAULT 0,
    observacao TEXT,
    FOREIGN KEY(carga_id) REFERENCES cargas_galvanizacao(id) ON DELETE CASCADE,
    FOREIGN KEY(processo_id) REFERENCES processos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS proposta_itens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    processo_principal_id INTEGER NOT NULL,
    processo_atual_id INTEGER NOT NULL,
    numero_item TEXT NOT NULL,
    descricao TEXT,
    quantidade INTEGER NOT NULL DEFAULT 1,
    peso REAL NOT NULL DEFAULT 0,
    produzido INTEGER NOT NULL DEFAULT 0,
    galvanizado INTEGER NOT NULL DEFAULT 0,
    entregue INTEGER NOT NULL DEFAULT 0,
    entregue_em TEXT,
    atualizado_em TEXT,
    atualizado_por TEXT,
    UNIQUE(processo_principal_id, numero_item),
    FOREIGN KEY(processo_principal_id) REFERENCES processos(id) ON DELETE CASCADE,
    FOREIGN KEY(processo_atual_id) REFERENCES processos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS entregas_itens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    processo_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    tipo_entrega TEXT NOT NULL,
    data_hora TEXT NOT NULL,
    usuario TEXT NOT NULL,
    observacao TEXT,
    FOREIGN KEY(processo_id) REFERENCES processos(id) ON DELETE CASCADE,
    FOREIGN KEY(item_id) REFERENCES proposta_itens(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS remanejamentos_itens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    processo_destino_id INTEGER NOT NULL,
    processo_origem_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    data_hora TEXT NOT NULL,
    usuario TEXT NOT NULL,
    observacao TEXT,
    FOREIGN KEY(processo_destino_id) REFERENCES processos(id) ON DELETE CASCADE,
    FOREIGN KEY(processo_origem_id) REFERENCES processos(id) ON DELETE CASCADE,
    FOREIGN KEY(item_id) REFERENCES proposta_itens(id) ON DELETE CASCADE
);
