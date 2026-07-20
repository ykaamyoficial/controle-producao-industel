ALTER TABLE fiscal_processos
ADD COLUMN situacao_fiscal TEXT NOT NULL DEFAULT 'AGUARDANDO_NF';

ALTER TABLE fiscal_processos
ADD COLUMN data_retirada_nf TEXT;

ALTER TABLE fiscal_processos
ADD COLUMN retirada_por TEXT;

ALTER TABLE fiscal_processos
ADD COLUMN observacao_retirada_nf TEXT;

UPDATE fiscal_processos
SET situacao_fiscal = CASE
    WHEN status_fiscal = 'NOTA_FISCAL_EMITIDA' THEN 'NF_EMITIDA'
    WHEN status_fiscal = 'NOTA_FISCAL_PARCIAL' THEN 'NF_PARCIAL'
    WHEN status_fiscal = 'FISCAL_CANCELADO' THEN 'FISCAL_CANCELADO'
    ELSE 'AGUARDANDO_NF'
END;

CREATE INDEX IF NOT EXISTS ix_fiscal_processos_situacao_fiscal
ON fiscal_processos(situacao_fiscal);

CREATE INDEX IF NOT EXISTS ix_fiscal_processos_data_retirada_nf
ON fiscal_processos(data_retirada_nf);
