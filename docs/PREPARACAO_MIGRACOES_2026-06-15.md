# Relatorio de preparacao segura do banco

Data da validacao: 15/06/2026

## Git e GitHub

- Repositorio Git local encontrado na branch `main`.
- Remoto configurado para `ykaamyoficial/controle-producao-industel`.
- Repositorio confirmado como privado no GitHub.
- Banco real, backups, logs, configuracoes locais, builds e executaveis nao
  estao rastreados.

## Backup anterior as alteracoes

Foi criado um pacote em `backups/pre_migrations_20260615_143827/`, ignorado
pelo Git, contendo:

- copia consistente do banco SQLite;
- arquivo ZIP do codigo e arquivos do projeto;
- bundle com o historico completo do repositorio Git;
- relatorio JSON da validacao do banco.

Validacao da copia do banco:

- `PRAGMA integrity_check`: `ok`;
- `PRAGMA quick_check`: `ok`;
- `PRAGMA foreign_key_check`: nenhuma violacao;
- tamanho da copia SQLite: 102400 bytes;
- tabelas operacionais encontradas: 12;
- resultado final: integro.

## Migracoes registradas

| Versao | Nome | Situacao |
| --- | --- | --- |
| 001 | initial_schema | Aplicada |
| 002 | prepare_versioning | Aplicada |

A segunda execucao do executor nao reaplicou nenhuma migracao. O banco
continuou com a mesma quantidade de processos antes e depois da inicializacao
do servico.

## Testes executados

- compilacao dos modulos Python;
- migracao de um banco vazio;
- inicializacao completa do esquema em banco vazio;
- migracao de uma copia do banco real;
- preservacao da quantidade de processos;
- idempotencia da segunda execucao;
- validacao do backup;
- integridade e chaves estrangeiras;
- inicializacao do `BackendService` apos a migracao.

Todos os testes foram aprovados.

## Como repetir a validacao

No PowerShell, na raiz do projeto:

```powershell
C:\Users\Industel\AppData\Local\Programs\Python\Python311\python.exe -m unittest discover -s tests -v
```

Para conferir os arquivos protegidos pelo Git:

```powershell
& 'C:\Program Files\Git\cmd\git.exe' status --short
& 'C:\Program Files\Git\cmd\git.exe' check-ignore -v app\data\controle_producao.db
```

## Regra para futuras alteracoes

Toda mudanca estrutural deve receber um novo arquivo SQL numerado. Migracoes
ja aplicadas nunca devem ser editadas, pois o checksum SHA-256 detectara a
alteracao e impedira uma inicializacao insegura.
