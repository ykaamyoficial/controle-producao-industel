-- Define fluxo operacional por item da proposta.
-- Mantem registros antigos como indefinidos para exigir conferencia humana.

ALTER TABLE proposta_itens
    ADD COLUMN produzir_internamente TEXT NOT NULL DEFAULT 'indefinido'
    CHECK (produzir_internamente IN ('sim', 'nao', 'indefinido'));

ALTER TABLE proposta_itens
    ADD COLUMN motivo_nao_produzir TEXT
    CHECK (
        motivo_nao_produzir IS NULL
        OR motivo_nao_produzir = ''
        OR motivo_nao_produzir IN ('pronta_entrega', 'comprado_terceiro', 'terceirizado', 'outro')
    );

ALTER TABLE proposta_itens
    ADD COLUMN precisa_galvanizacao TEXT NOT NULL DEFAULT 'indefinido'
    CHECK (precisa_galvanizacao IN ('sim', 'nao', 'indefinido'));

ALTER TABLE proposta_itens ADD COLUMN observacao_fluxo_item TEXT;
ALTER TABLE proposta_itens ADD COLUMN fluxo_definido_por TEXT;
ALTER TABLE proposta_itens ADD COLUMN fluxo_definido_em TEXT;

CREATE INDEX IF NOT EXISTS ix_proposta_itens_fluxo_producao
    ON proposta_itens(produzir_internamente);

CREATE INDEX IF NOT EXISTS ix_proposta_itens_fluxo_galvanizacao
    ON proposta_itens(precisa_galvanizacao);
