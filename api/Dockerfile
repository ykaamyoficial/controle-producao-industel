# Imagem de release do backend (Fase 07 - imagens Docker versionadas).
#
# server_version/api_contract_version continuam vindo exclusivamente de
# api/app/core/config.py (Fase 01) -- os ARGs abaixo sao METADADOS de build
# (tag/labels/log de identidade), nunca uma segunda fonte de verdade da versao
# funcional. scripts/build_release_image.py e quem calcula e valida esses
# valores antes de chamar "docker build"; nao os digite manualmente.
#
# Uso tipico (via script, nao diretamente):
#   python scripts/build_release_image.py
#
# Build manual equivalente (para diagnostico):
#   docker build -f api/Dockerfile \
#     --build-arg SERVER_VERSION=0.8.0 --build-arg COMMIT_SHA=abc1234 \
#     --build-arg BUILD_TIME=2026-08-11T00:00:00Z \
#     -t controle-producao-api:0.8.0 .

# Base pinada por tag E digest -- protege contra o mesmo "python:3.12-slim"
# passar a apontar para uma imagem diferente no futuro (Secao 11). Para
# atualizar deliberadamente: `docker pull python:3.12-slim`, copiar o novo
# digest aqui, validar compatibilidade e rodar a suite completa (nao trocar
# a MINOR version do Python nesta fase).
FROM python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36 AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Dependencias deterministicas (Secao 12): instala exatamente o que
# requirements*.txt fixa, sem tocar codigo da aplicacao ainda -- cache de
# camada so invalida quando os proprios requirements mudam, nao a cada commit.
COPY api/requirements.txt api/requirements-dev.txt ./
RUN pip install --prefix=/install -r requirements-dev.txt


FROM python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36 AS runtime

# Metadados de build (Secao 13/21) -- nunca secrets. Sem default para
# SERVER_VERSION: uma imagem construida sem passar o ARG fica com a label
# vazia, o que scripts/build_release_image.py trata como falha explicita.
ARG SERVER_VERSION
ARG COMMIT_SHA=unknown
ARG BUILD_TIME

LABEL org.opencontainers.image.title="controle-producao-api" \
      org.opencontainers.image.version="${SERVER_VERSION}" \
      org.opencontainers.image.revision="${COMMIT_SHA}" \
      org.opencontainers.image.created="${BUILD_TIME}" \
      org.opencontainers.image.description="API do Sistema de Controle de Producao Industel."

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BUILD_COMMIT_SHA=${COMMIT_SHA} \
    BUILD_TIME_UTC=${BUILD_TIME}

WORKDIR /app

RUN addgroup --system apiuser && adduser --system --ingroup apiuser apiuser
RUN mkdir -p /app/data && chown -R apiuser:apiuser /app/data

# So as dependencias ja resolvidas pelo estagio builder -- nenhuma ferramenta
# de build (gcc, headers) nem os arquivos requirements*.txt chegam ao runtime.
COPY --from=builder /install /usr/local

# Codigo da aplicacao (api/tests/ e excluido via .dockerignore -- Secao 10).
COPY --chown=apiuser:apiuser api/__init__.py /app/api/__init__.py
COPY --chown=apiuser:apiuser api/app /app/api/app
COPY --chown=apiuser:apiuser api/alembic /app/api/alembic
COPY --chown=apiuser:apiuser api/alembic.ini /app/api/alembic.ini

USER apiuser

EXPOSE 8000

# Reaproveita o /health/ready da Fase 06 -- so a biblioteca padrao (urllib),
# sem curl/wget novo (Secao 23/18 da Fase 06). timeout/start_period coerentes
# com DATABASE_CONNECT_TIMEOUT (10s default); ver docker-compose.prod.yml para
# a config real usada (interval/timeout/retries/start_period sao definidos no
# compose, nao aqui, para poderem variar por ambiente sem rebuild de imagem).
HEALTHCHECK --interval=30s --timeout=12s --retries=5 --start-period=20s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready', timeout=8)"]

# CMD simples e previsivel (Secao 10): so sobe o processo. Migrations,
# backup e verificacoes pertencem ao fluxo de deployment explicito das fases
# anteriores/futuras -- o startup em si nunca roda migration (Secao 20).
CMD ["python", "-m", "uvicorn", "api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
