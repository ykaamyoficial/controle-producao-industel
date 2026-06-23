# Publicar Release no GitHub

Este documento descreve o processo manual para publicar uma versao instalavel do Controle de Producao Industel.

## Objetivo

Publicar os arquivos de distribuicao em um repositorio publico separado, sem expor codigo-fonte, banco de dados real, configuracoes locais ou dados da empresa.

Repositorio publico recomendado:

`ykaamyoficial/controle-producao-industel-releases`

## Arquivos publicados

Cada release publica deve conter somente:

- `ControleProducaoSetup-2.4.0.exe`
- `ControleProducaoSetup-2.4.0.sha256`
- `latest.json`
- Notas da versao no proprio GitHub Release

Nao publicar:

- Banco SQLite real
- Banco demo
- Arquivos `.db-wal` ou `.db-shm`
- Backups
- Configuracao real `controle_producao_config.json`
- Codigo-fonte do repositorio privado

## Passo a passo

1. Gerar o build do PyInstaller:

```powershell
py -3.11 -m PyInstaller ControleProducao.spec --clean --noconfirm
```

2. Gerar o instalador com Inno Setup:

```powershell
& "C:\Program Files\Inno Setup 7\ISCC.exe" installer\ControleProducao.iss
```

3. Confirmar que o instalador foi criado:

```text
release\ControleProducaoSetup-2.4.0.exe
```

4. Gerar hash e metadados da release:

```powershell
py scripts/create_release_files.py
```

5. Conferir os arquivos gerados:

```text
release\ControleProducaoSetup-2.4.0.exe
release\ControleProducaoSetup-2.4.0.sha256
release\latest.json
```

6. Criar uma release publica no GitHub:

```text
Tag: v2.4.0
Titulo: Controle de Producao Industel 2.4.0
```

7. Anexar os arquivos:

- `ControleProducaoSetup-2.4.0.exe`
- `ControleProducaoSetup-2.4.0.sha256`
- `latest.json`

## Validacao do hash

O arquivo `.sha256` deve conter o hash SHA-256 do instalador e o nome do arquivo:

```text
HASH  ControleProducaoSetup-2.4.0.exe
```

O campo `sha256` do `latest.json` deve ser igual ao hash do instalador.

## Uso futuro

Em uma etapa futura, o sistema podera consultar a ultima release publica no GitHub, comparar a versao instalada, baixar o instalador, validar o SHA-256, fazer backup do banco SQLite e iniciar a atualizacao com seguranca.
