# Interface Desktop PySide6

Esta pasta contem a frente visual desktop do Controle de Producao Industel.

A interface usa PySide6 e consome os dados oficiais pela API REST do sistema.
O banco operacional fica no PostgreSQL do servidor; o desktop nao armazena
dados operacionais em arquivo e nao executa SQL diretamente.

## Como abrir

Use o arquivo da raiz:

```bat
abrir_pyside6.bat
```

Ou execute:

```bat
python -m app.main
```

## Separacao das versoes

- Interface desktop PySide6: `app/`
- Configuracao do desktop: `app/config/controle_producao_config.json`
- Cliente HTTP da API: `app/integrations/api/`
- Adaptador da aplicacao: `app/services/backend_adapter.py`
- Icones do desktop: `app/assets/icons/`

## Estrutura

- `app/main.py`: ponto de entrada da nova interface.
- `app/ui/main_window.py`: janela principal, topbar, sidebar e troca de paginas.
- `app/ui/sidebar.py`: menu lateral recolhivel.
- `app/ui/dashboard_page.py`: painel inicial com cards KPI e graficos simples.
- `app/ui/process_page.py`: paginas por area com filtros, tabela e alteracao de status.
- `app/ui/status_dialog.py`: modal profissional para alterar status.
- `app/ui/components/`: botoes, cards, tabela, toast e dialogos reutilizaveis.
- `app/models/`: modelos Qt para tabelas.
- `app/services/backend_adapter.py`: fachada segura para API/PostgreSQL.
- `app/ui/styles.py`: tema visual baseado nas paletas ja existentes.
- `app/data/`: arquivos operacionais do desktop, como updates, logs e diagnosticos.
- `app/config/`: configuracao isolada da nova versao.

## Observacao

O runtime oficial do desktop e API/PostgreSQL. Modulos legados podem permanecer
temporariamente no repositorio apenas para historico, testes e comparacao durante
a migracao, mas nao sao a fonte oficial dos dados.
