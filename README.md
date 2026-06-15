# Controle de Producao Industel 2.0

Aplicacao desktop para acompanhamento do fluxo industrial de propostas, producao, galvanizacao, expedicao, almoxarifado, cargas, entregas parciais e remanejamentos.

## Tecnologias

- Python 3.11
- PySide6
- SQLite
- PyInstaller

## Executar localmente

1. Instale as dependencias com `pip install -r requirements.txt`.
2. Crie `app/config/controle_producao_config.json` a partir do arquivo de exemplo.
3. Execute `python -m app.main`.

O banco de dados, backups e configuracoes locais nao sao enviados ao GitHub.

## Gerar o executavel

Execute `gerar_exe_pyside6.bat`. O resultado sera criado na pasta `dist`.
