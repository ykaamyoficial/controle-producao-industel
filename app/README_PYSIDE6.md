# Nova interface PySide6

Esta pasta contem a nova frente visual do Controle de Producao Industel.

O sistema antigo em Tkinter foi preservado em `desktop/controle_producao.py`.
A nova interface usa PySide6 e acessa o mesmo banco SQLite pelo adaptador em
`app/services/backend_adapter.py`, reaproveitando as regras de negocio atuais.

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

- Versao nova PySide6: `app/`
- Banco da versao nova: `app/data/controle_producao.db`
- Configuracao da versao nova: `app/config/controle_producao_config.json`
- Icones da versao nova: `app/assets/icons/`
- Nucleo de regras da versao 2.0: `app/services/production_core.py`

## Estrutura

- `app/main.py`: ponto de entrada da nova interface.
- `app/ui/main_window.py`: janela principal, topbar, sidebar e troca de paginas.
- `app/ui/sidebar.py`: menu lateral recolhivel.
- `app/ui/dashboard_page.py`: painel inicial com cards KPI e graficos simples.
- `app/ui/process_page.py`: paginas por area com filtros, tabela e alteracao de status.
- `app/ui/status_dialog.py`: modal profissional para alterar status.
- `app/ui/components/`: botoes, cards, tabela, toast e dialogos reutilizaveis.
- `app/models/`: modelos Qt para tabelas.
- `app/services/backend_adapter.py`: ponte segura com o backend existente.
- `app/ui/styles.py`: tema visual baseado nas paletas ja existentes.
- `app/data/`: banco e backups da nova versao.
- `app/config/`: configuracao isolada da nova versao.

## Observacao

Esta etapa entrega uma nova camada visual moderna e funcional sem remover o
sistema antigo. As regras de status, banco SQLite, permissoes e validacoes
continuam vindo do backend atual.
