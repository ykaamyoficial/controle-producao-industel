from __future__ import annotations

APP_NAME = "Controle de Producao Industel"
APP_VERSION = "2.6.1"
APP_BUILD = "2026.09.04"
APP_PUBLISHER = "Industel"
APP_CHANNEL = "stable"
APP_EXECUTABLE_NAME = "ControleProducao.exe"
# Contrato publico da API que este build do Desktop foi construido para consumir
# (comparado com api_contract_version retornado por GET /system/compatibility).
# So muda quando o Desktop e adaptado deliberadamente a um novo contrato — nunca
# acompanha automaticamente APP_VERSION.
APP_API_CONTRACT_VERSION = "v1"
# Fase 6 - Compatibilidade de Versoes (Secao 3): menor versao semantica da API
# que este build sabe operar com seguranca -- complementa APP_API_CONTRACT_VERSION
# (que so muda em ruptura de contrato) protegendo contra o caso simetrico: um
# Desktop novo apontando para uma API mais antiga que ainda declara o mesmo
# contrato "v1", mas nao tem uma correcao/campo do qual este build depende.
# So sobe quando o Desktop passa a depender de verdade de um comportamento
# novo da API -- nunca acompanha APP_VERSION automaticamente.
MINIMUM_API_VERSION = "0.8.1"
