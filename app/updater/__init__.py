"""Updater do Desktop (Fase 10) -- componente SEPARADO do aplicativo principal.

Regra de ouro: o Desktop nunca substitui os proprios arquivos. Este pacote e
executado como um processo independente (ver app/updater/__main__.py),
recebendo um UpdateRequest ja autorizado (a decisao de qual versao instalar
continua do lado do Desktop/API, Fases 02/03 -- este pacote nunca consulta
"latest" de forma alguma para decidir por conta propria).
"""
