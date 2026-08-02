# Migracoes Legadas do Desktop

Esta pasta registra as migrations historicas do antigo banco local do desktop.
No runtime oficial atual, alteracoes estruturais do banco devem ser feitas na
API com Alembic/PostgreSQL.

Estes arquivos permanecem apenas para testes legados e referencia historica
durante a migracao.

## Convencao

- Nome: `NNN_descricao_curta.sql`.
- Versoes nunca devem ser reutilizadas.
- Uma migracao aplicada nunca deve ser editada. Crie uma nova migracao.
- Cada arquivo era executado em uma transacao exclusiva pelo runtime legado.
- Em caso de erro, a transacao sofria rollback e o aplicativo nao iniciava.
- O checksum SHA-256 impedia que uma migracao aplicada fosse alterada em silencio.

## Fluxo

1. O executor legado cria `schema_migrations`, se necessario.
2. Le os arquivos em ordem numerica.
3. Compara versao e checksum com o banco legado.
4. Aplica somente arquivos pendentes.
5. Registra versao, nome, data UTC e checksum.

`001_initial_schema.sql` representa o esquema existente no inicio do
versionamento. `002_prepare_versioning.sql` documenta formalmente a tabela de
controle criada durante o bootstrap. `003_nomus_pdf_import_metadata.sql`
armazena somente a origem operacional, o nome e o SHA-256 do PDF Nomus quando
o processo e efetivamente salvo; o arquivo e seu texto integral nao sao copiados.
`004_fiscal_base.sql` prepara as tabelas vazias do modulo Fiscal, sem criar
registros, telas ou mudancas de fluxo.
