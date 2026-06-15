# Migracoes SQLite

As alteracoes estruturais do banco devem ser feitas somente por arquivos SQL
numerados nesta pasta.

## Convencao

- Nome: `NNN_descricao_curta.sql`.
- Versoes nunca devem ser reutilizadas.
- Uma migracao aplicada nunca deve ser editada. Crie uma nova migracao.
- Cada arquivo e executado em uma transacao exclusiva.
- Em caso de erro, a transacao sofre rollback e o aplicativo nao inicia.
- O checksum SHA-256 impede que uma migracao aplicada seja alterada em silencio.

## Fluxo

1. O executor cria `schema_migrations`, se necessario.
2. Le os arquivos em ordem numerica.
3. Compara versao e checksum com o banco.
4. Aplica somente arquivos pendentes.
5. Registra versao, nome, data UTC e checksum.

`001_initial_schema.sql` representa o esquema existente no inicio do
versionamento. `002_prepare_versioning.sql` documenta formalmente a tabela de
controle criada durante o bootstrap.
