from __future__ import annotations

import socket
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from urllib.parse import urlparse, urlunparse

from app.integrations.api.client import DesktopApiClient
from app.integrations.api.config import (
    DesktopApiConfigError,
    DesktopApiConfigStore,
    DesktopApiSettings,
    normalize_api_base_url,
)
from app.integrations.api.exceptions import ApiClientError, ApiTimeoutError
from app.services.app_logging import get_logger

log = get_logger("diagnostic_service")

HEALTH_PATH = "/api/v1/health/ready"


class DiagnosticStatus(str, Enum):
    OK = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"
    NOT_TESTED = "NOT_TESTED"


class DiagnosticErrorCode(str, Enum):
    """Fase 4, Secao 5: catalogo estavel de causas -- UI/logs/testes nunca
    dependem de texto de excecao de biblioteca."""

    CFG_MISSING = "CFG_MISSING"
    CFG_INVALID = "CFG_INVALID"
    HOST_RESOLUTION_FAILED = "HOST_RESOLUTION_FAILED"
    CONNECT_TIMEOUT = "CONNECT_TIMEOUT"
    CONNECTION_REFUSED = "CONNECTION_REFUSED"
    NETWORK_UNREACHABLE = "NETWORK_UNREACHABLE"
    HTTP_UNEXPECTED = "HTTP_UNEXPECTED"
    API_UNHEALTHY = "API_UNHEALTHY"
    DB_UNAVAILABLE = "DB_UNAVAILABLE"
    # Fase 5 - HTTPS e Seguranca, Secao 7: catalogo TLS, para nunca mascarar
    # um problema de confianca/identidade do certificado como "rede offline"
    # -- todos pressupoem que o servidor FOI alcancado na camada TCP.
    TLS_CERT_UNTRUSTED = "TLS_CERT_UNTRUSTED"
    TLS_HOSTNAME_MISMATCH = "TLS_HOSTNAME_MISMATCH"
    TLS_CERT_EXPIRED = "TLS_CERT_EXPIRED"
    TLS_HANDSHAKE_FAILED = "TLS_HANDSHAKE_FAILED"
    HTTPS_REQUIRED = "HTTPS_REQUIRED"
    # Fase 6 - Compatibilidade de Versoes, Secao 12: catalogo sugerido.
    CLIENT_UPDATE_REQUIRED = "CLIENT_UPDATE_REQUIRED"
    SERVER_UPDATE_REQUIRED = "SERVER_UPDATE_REQUIRED"
    VERSION_METADATA_INVALID = "VERSION_METADATA_INVALID"
    VERSION_ENDPOINT_UNAVAILABLE = "VERSION_ENDPOINT_UNAVAILABLE"


# Fase 4, Secao 3: ordem deterministica da cadeia. Uma etapa que falha marca
# todas as seguintes como NOT_TESTED, sem gerar ruido.
CHECK_LABELS: dict[str, str] = {
    "CONFIG_PRESENT": "Configuracao",
    "URL_VALID": "Endereco valido",
    "HOST_RESOLUTION": "Rede/host",
    "API_REACHABLE": "API",
    "HEALTH_HTTP": "Health",
    "API_HEALTH": "Aplicacao",
    "DATABASE_HEALTH": "PostgreSQL",
    # Fase 6, Secao 12: duas etapas adicionais no mesmo diagnostico -- nao
    # cria uma tela nova, so estende a cadeia existente.
    "VERSION_ENDPOINT": "Endpoint de versao",
    "COMPATIBILITY": "Compatibilidade",
}
CHECK_ORDER: list[str] = list(CHECK_LABELS)

# Fase 4, Secao 8: mensagem principal + orientacao por codigo de erro.
_MESSAGES: dict[DiagnosticErrorCode, tuple[str, str]] = {
    DiagnosticErrorCode.CFG_MISSING: ("Servidor nao configurado.", "Verifique o endereco da API nas configuracoes administrativas."),
    DiagnosticErrorCode.CFG_INVALID: ("Endereco do servidor invalido.", "Corrija o endereco da API nas configuracoes administrativas."),
    DiagnosticErrorCode.HOST_RESOLUTION_FAILED: ("Nome do servidor nao pode ser resolvido.", "Verifique o endereco/nome do servidor e a rede local."),
    DiagnosticErrorCode.CONNECT_TIMEOUT: ("Servidor nao respondeu.", "Verifique a rede local e se o servidor esta ligado."),
    DiagnosticErrorCode.CONNECTION_REFUSED: ("API nao esta aceitando conexoes.", "Verifique o servico da API no servidor e a porta configurada."),
    DiagnosticErrorCode.NETWORK_UNREACHABLE: ("Nao foi possivel alcancar a rede do servidor.", "Verifique a rede local (cabo, Wi-Fi, VLAN) deste computador."),
    DiagnosticErrorCode.HTTP_UNEXPECTED: ("A API respondeu de forma inesperada.", "Verifique se a versao implantada da API possui a rota esperada, ou consulte os logs do servidor."),
    DiagnosticErrorCode.API_UNHEALTHY: ("A API respondeu, mas nao esta pronta.", "Consulte os logs do servidor."),
    DiagnosticErrorCode.DB_UNAVAILABLE: ("API online, PostgreSQL indisponivel.", "Verifique o servico PostgreSQL no servidor."),
    DiagnosticErrorCode.TLS_CERT_UNTRUSTED: ("O certificado do servidor nao e confiavel.", "Verifique a CA/certificado instalado neste computador."),
    DiagnosticErrorCode.TLS_HOSTNAME_MISMATCH: ("O certificado nao corresponde ao endereco do servidor.", "Verifique se a URL oficial confere com o nome (SAN) do certificado."),
    DiagnosticErrorCode.TLS_CERT_EXPIRED: ("O certificado do servidor esta expirado.", "Solicite a renovacao do certificado no servidor."),
    DiagnosticErrorCode.TLS_HANDSHAKE_FAILED: ("Falha ao negociar a conexao segura (TLS) com o servidor.", "Verifique a configuracao do proxy/certificado no servidor."),
    DiagnosticErrorCode.HTTPS_REQUIRED: ("O servidor exige uma conexao segura (HTTPS).", "Atualize o endereco configurado de http:// para https://."),
    DiagnosticErrorCode.CLIENT_UPDATE_REQUIRED: ("Este computador precisa de uma versao mais nova do sistema.", "Atualize o Desktop para uma versao compativel com este servidor."),
    DiagnosticErrorCode.SERVER_UPDATE_REQUIRED: ("O servidor esta com uma versao desatualizada para este Desktop.", "Contate o administrador do sistema para atualizar o servidor."),
    DiagnosticErrorCode.VERSION_METADATA_INVALID: ("O servidor respondeu com dados de versao invalidos.", "Consulte os logs do servidor."),
    DiagnosticErrorCode.VERSION_ENDPOINT_UNAVAILABLE: ("A API respondeu, mas o endpoint de versao falhou.", "Consulte os logs do servidor."),
}
_TLS_ERROR_CODES = {
    DiagnosticErrorCode.TLS_CERT_UNTRUSTED,
    DiagnosticErrorCode.TLS_HOSTNAME_MISMATCH,
    DiagnosticErrorCode.TLS_CERT_EXPIRED,
    DiagnosticErrorCode.TLS_HANDSHAKE_FAILED,
}


@dataclass(frozen=True)
class DiagnosticCheck:
    code: str
    label: str
    status: DiagnosticStatus
    duration_ms: int
    detail: str
    recommendation: str = ""
    error_code: DiagnosticErrorCode | None = None


@dataclass(frozen=True)
class DiagnosticResult:
    overall_status: DiagnosticStatus
    started_at: datetime
    duration_ms: int
    api_base_url_sanitized: str
    checks: list[DiagnosticCheck] = field(default_factory=list)
    user_message: str = ""
    technical_summary: str = ""


def classify_connect_exception(exc: BaseException | None) -> DiagnosticErrorCode:
    """Percorre a cadeia __cause__/__context__ de uma falha de conexao
    procurando o sinal mais especifico disponivel (DNS, recusa de conexao,
    rede inalcancavel). httpx nao expoe um tipo dedicado para cada caso --
    a causa real (socket.gaierror, ConnectionRefusedError, OSError com
    ENETUNREACH/EHOSTUNREACH) fica encadeada via `raise ... from exc`, entao
    inspecionamos tipo e mensagem em vez de comparar strings de uma unica
    excecao. Sem sinal especifico, assume recusa de conexao (caso mais
    comum de 'API nao esta rodando')."""
    seen: set[int] = set()
    node: BaseException | None = exc
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        text = str(node).lower()
        if isinstance(node, socket.gaierror) or "getaddrinfo failed" in text or "11001" in text or "name or service not known" in text or "nodename nor servname" in text:
            return DiagnosticErrorCode.HOST_RESOLUTION_FAILED
        if isinstance(node, ConnectionRefusedError) or "10061" in text or "connection refused" in text:
            return DiagnosticErrorCode.CONNECTION_REFUSED
        if "10051" in text or "10065" in text or "network is unreachable" in text or "no route to host" in text or "enetunreach" in text or "ehostunreach" in text:
            return DiagnosticErrorCode.NETWORK_UNREACHABLE
        node = node.__cause__ or node.__context__
    return DiagnosticErrorCode.CONNECTION_REFUSED


def classify_tls_exception(exc: BaseException | None) -> DiagnosticErrorCode | None:
    """Fase 5, Secao 7: percorre a mesma cadeia de causas procurando um erro
    TLS especifico. Devolve None quando a falha nao e de TLS (o chamador
    entao cai para `classify_connect_exception`) -- um handshake TLS que
    falhou prova que o servidor foi alcancado na camada TCP, entao nunca
    deve virar DNS/timeout/rede."""
    seen: set[int] = set()
    node: BaseException | None = exc
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        text = str(node).lower()
        if isinstance(node, ssl.SSLCertVerificationError):
            # ssl.CertificateError e apenas um alias de SSLCertVerificationError
            # nas versoes atuais do Python -- checar a mensagem, nao o tipo.
            if "certificate has expired" in text or "certificate is not yet valid" in text:
                return DiagnosticErrorCode.TLS_CERT_EXPIRED
            if "hostname mismatch" in text:
                return DiagnosticErrorCode.TLS_HOSTNAME_MISMATCH
            return DiagnosticErrorCode.TLS_CERT_UNTRUSTED
        if "hostname mismatch" in text:
            return DiagnosticErrorCode.TLS_HOSTNAME_MISMATCH
        if "certificate has expired" in text:
            return DiagnosticErrorCode.TLS_CERT_EXPIRED
        if "certificate verify failed" in text or "self-signed certificate" in text or "unable to get local issuer certificate" in text:
            return DiagnosticErrorCode.TLS_CERT_UNTRUSTED
        if isinstance(node, ssl.SSLError) or "ssl" in type(node).__name__.lower():
            return DiagnosticErrorCode.TLS_HANDSHAKE_FAILED
        node = node.__cause__ or node.__context__
    return None


def _sanitize_url(url: str) -> str:
    """Remove eventual userinfo (usuario:senha@) antes de exibir/copiar."""
    parsed = urlparse(url)
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))


def _check_host_resolution(host: str, *, timeout: float = 3.0) -> tuple[bool, str]:
    """Fase 4, Secao 3: 'host pode ser resolvido quando aplicavel' -- um IP
    literal ja esta resolvido, entao so tenta getaddrinfo para nomes DNS."""
    try:
        from ipaddress import ip_address

        ip_address(host)
        return True, "Endereco IP informado diretamente (sem necessidade de DNS)."
    except ValueError:
        pass
    previous_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(timeout)
        socket.getaddrinfo(host, None)
        return True, f"Nome '{host}' resolvido com sucesso."
    except OSError:
        return False, f"Nao foi possivel resolver o nome '{host}'."
    finally:
        socket.setdefaulttimeout(previous_timeout)


def run_diagnostics(
    *,
    config_store: DesktopApiConfigStore | None = None,
    client_factory=DesktopApiClient,
) -> DiagnosticResult:
    """Fase 4 - Diagnostico: executa a cadeia completa e deterministica de
    verificacoes (config -> URL -> host -> rede/HTTP -> health -> app -> DB),
    somente leitura em toda a extensao, sem jamais abrir conexao direta com
    o PostgreSQL a partir do Desktop."""
    store = config_store or DesktopApiConfigStore()
    started_at = datetime.now(timezone.utc)
    started_monotonic = time.monotonic()
    checks: list[DiagnosticCheck] = []

    def add(code: str, status: DiagnosticStatus, duration_ms: int, detail: str, *, error_code: DiagnosticErrorCode | None = None) -> None:
        recommendation = _MESSAGES.get(error_code, ("", ""))[1] if error_code else ""
        checks.append(DiagnosticCheck(code=code, label=CHECK_LABELS[code], status=status, duration_ms=duration_ms, detail=detail, recommendation=recommendation, error_code=error_code))

    def fill_not_tested(from_index: int, reason: str) -> None:
        for code in CHECK_ORDER[from_index:]:
            checks.append(DiagnosticCheck(code=code, label=CHECK_LABELS[code], status=DiagnosticStatus.NOT_TESTED, duration_ms=0, detail=reason))

    def finish(base_url_for_report: str) -> DiagnosticResult:
        overall = _overall_status(checks)
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        failing = next((c for c in checks if c.status == DiagnosticStatus.ERROR), None)
        if failing is not None and failing.error_code is not None:
            user_message = _MESSAGES[failing.error_code][0]
        elif failing is not None:
            user_message = failing.detail
        else:
            user_message = "Conexao com o servidor validada com sucesso."
        technical_summary = "; ".join(f"{c.code}={c.status.value}" for c in checks)
        result = DiagnosticResult(
            overall_status=overall,
            started_at=started_at,
            duration_ms=duration_ms,
            api_base_url_sanitized=_sanitize_url(base_url_for_report) if base_url_for_report else "",
            checks=checks,
            user_message=user_message,
            technical_summary=technical_summary,
        )
        log.info(
            "diagnostic_finished | overall=%s | duration_ms=%s | failing_check=%s",
            overall.value, duration_ms, failing.code if failing else "-",
        )
        return result

    log.info("diagnostic_started")

    if not store.is_configured():
        add("CONFIG_PRESENT", DiagnosticStatus.ERROR, 0, "Nenhum endereco de servidor configurado.", error_code=DiagnosticErrorCode.CFG_MISSING)
        fill_not_tested(1, "Nao verificado: nenhuma configuracao de servidor existe ainda.")
        return finish("")
    add("CONFIG_PRESENT", DiagnosticStatus.OK, 0, "Endereco de servidor configurado.")

    settings = store.load_settings()
    try:
        normalized = normalize_api_base_url(settings.base_url)
    except DesktopApiConfigError as exc:
        add("URL_VALID", DiagnosticStatus.ERROR, 0, str(exc), error_code=DiagnosticErrorCode.CFG_INVALID)
        fill_not_tested(2, "Nao verificado: endereco configurado nao e valido.")
        return finish(settings.base_url)
    add("URL_VALID", DiagnosticStatus.OK, 0, _sanitize_url(normalized))

    host = urlparse(normalized).hostname or ""
    t0 = time.monotonic()
    host_ok, host_detail = _check_host_resolution(host)
    host_duration = int((time.monotonic() - t0) * 1000)
    if not host_ok:
        add("HOST_RESOLUTION", DiagnosticStatus.ERROR, host_duration, host_detail, error_code=DiagnosticErrorCode.HOST_RESOLUTION_FAILED)
        fill_not_tested(3, "Nao verificado: o host do servidor nao pode ser resolvido.")
        return finish(normalized)
    add("HOST_RESOLUTION", DiagnosticStatus.OK, host_duration, host_detail)

    t0 = time.monotonic()
    status_code, payload, exc = _probe_ready(normalized, connect_timeout=settings.connect_timeout, read_timeout=settings.read_timeout, client_factory=client_factory)
    reach_duration = int((time.monotonic() - t0) * 1000)

    if exc is not None:
        if isinstance(exc, ApiTimeoutError):
            error_code = DiagnosticErrorCode.CONNECT_TIMEOUT
        else:
            # TLS classificado primeiro: um handshake que falhou prova que o
            # servidor foi alcancado na camada TCP -- nunca deve virar
            # DNS/timeout/rede (Fase 5, Secao 7: "nao mascarar TLS como
            # rede offline").
            error_code = classify_tls_exception(exc.__cause__ or exc) or classify_connect_exception(exc.__cause__ or exc)
        add("API_REACHABLE", DiagnosticStatus.ERROR, reach_duration, _MESSAGES[error_code][0], error_code=error_code)
        fill_not_tested(4, "Nao verificado: a API nao respondeu.")
        return finish(normalized)
    add("API_REACHABLE", DiagnosticStatus.OK, reach_duration, f"Servidor respondeu em {reach_duration} ms.")

    if urlparse(normalized).scheme == "http" and status_code in {301, 302, 307, 308}:
        add("HEALTH_HTTP", DiagnosticStatus.ERROR, 0, f"O servidor redirecionou a requisicao HTTP (HTTP {status_code}).", error_code=DiagnosticErrorCode.HTTPS_REQUIRED)
        fill_not_tested(5, "Nao verificado: endereco configurado ainda usa HTTP.")
        return finish(normalized)

    if status_code == 404:
        add("HEALTH_HTTP", DiagnosticStatus.ERROR, 0, "Rota de health check nao encontrada (HTTP 404).", error_code=DiagnosticErrorCode.HTTP_UNEXPECTED)
        fill_not_tested(5, "Nao verificado: rota de health inexistente.")
        return finish(normalized)
    if not isinstance(payload, dict) or "overall_status" not in payload:
        add("HEALTH_HTTP", DiagnosticStatus.ERROR, 0, f"Resposta inesperada do health check (HTTP {status_code}).", error_code=DiagnosticErrorCode.HTTP_UNEXPECTED)
        fill_not_tested(5, "Nao verificado: contrato de health inesperado.")
        return finish(normalized)
    add("HEALTH_HTTP", DiagnosticStatus.OK, 0, f"HTTP {status_code}, contrato valido.")

    if status_code == 500:
        add("API_HEALTH", DiagnosticStatus.ERROR, 0, "A API respondeu com erro interno (HTTP 500).", error_code=DiagnosticErrorCode.HTTP_UNEXPECTED)
        fill_not_tested(6, "Nao verificado: falha interna na API.")
        return finish(normalized)
    overall_status_field = str(payload.get("overall_status", "")).upper()
    add("API_HEALTH", DiagnosticStatus.OK, 0, f"Aplicacao respondeu (status={overall_status_field or 'desconhecido'}).")

    db_check = next((c for c in (payload.get("checks") or []) if isinstance(c, dict) and c.get("name") == "database"), None)
    if db_check is None:
        add("DATABASE_HEALTH", DiagnosticStatus.WARNING, 0, "A resposta da API nao informou o estado do PostgreSQL.")
    elif str(db_check.get("status", "")).upper() == "PASS":
        add("DATABASE_HEALTH", DiagnosticStatus.OK, int(db_check.get("duration_ms") or 0), "Banco reportado como disponivel pela API.")
    else:
        add("DATABASE_HEALTH", DiagnosticStatus.ERROR, int(db_check.get("duration_ms") or 0), "API online; PostgreSQL indisponivel.", error_code=DiagnosticErrorCode.DB_UNAVAILABLE)

    _add_compatibility_checks(
        add, fill_not_tested, normalized,
        connect_timeout=settings.connect_timeout, read_timeout=settings.read_timeout,
        client_factory=client_factory,
    )

    return finish(normalized)


def _add_compatibility_checks(
    add,
    fill_not_tested,
    base_url: str,
    *,
    connect_timeout: float,
    read_timeout: float,
    client_factory=DesktopApiClient,
) -> None:
    """Fase 6, Secao 12: estende a mesma cadeia com VERSION_ENDPOINT/
    COMPATIBILITY, reutilizando a avaliacao pura ja usada pelo preflight de
    startup (app.versioning.compatibility) -- nao reimplementa a regra de
    comparacao de versao aqui. Somente leitura: GET /system/compatibility
    sem installation_id, para nunca disparar o heartbeat/registro de canal
    que esse parametro aciona no servidor (Fase 15)."""
    from app.integrations.api.models import SystemCompatibilityDto
    from app.versioning.compatibility import evaluate_startup_compatibility
    from app.versioning.models import CompatibilityStatus
    from app.versioning.versions import get_desktop_version, get_minimum_api_version, get_supported_api_contract_version

    settings = DesktopApiSettings(enabled=True, base_url=base_url, connect_timeout=connect_timeout, read_timeout=read_timeout)
    client = client_factory(settings)
    try:
        status_code, payload = client.get_status_and_payload("/api/v1/system/compatibility")
    except ApiClientError:
        add("VERSION_ENDPOINT", DiagnosticStatus.ERROR, 0, "A API respondeu, mas o endpoint de compatibilidade nao respondeu.", error_code=DiagnosticErrorCode.VERSION_ENDPOINT_UNAVAILABLE)
        fill_not_tested(8, "Nao verificado: endpoint de compatibilidade indisponivel.")
        return
    finally:
        client.close()

    if status_code != 200 or not isinstance(payload, dict):
        add("VERSION_ENDPOINT", DiagnosticStatus.ERROR, 0, f"Resposta inesperada do endpoint de compatibilidade (HTTP {status_code}).", error_code=DiagnosticErrorCode.VERSION_ENDPOINT_UNAVAILABLE)
        fill_not_tested(8, "Nao verificado: endpoint de compatibilidade indisponivel.")
        return

    try:
        dto = SystemCompatibilityDto.from_payload(payload)
    except ValueError:
        add("VERSION_ENDPOINT", DiagnosticStatus.ERROR, 0, "O endpoint de compatibilidade respondeu dados ausentes/malformados.", error_code=DiagnosticErrorCode.VERSION_METADATA_INVALID)
        fill_not_tested(8, "Nao verificado: metadados de versao invalidos.")
        return
    add("VERSION_ENDPOINT", DiagnosticStatus.OK, 0, f"HTTP 200, API {dto.server_version}.")

    desktop_version = get_desktop_version()
    try:
        state = evaluate_startup_compatibility(
            maintenance_mode=dto.maintenance_mode,
            api_contract_version=dto.api_contract_version,
            minimum_desktop_version=dto.minimum_desktop_version,
            recommended_desktop_version=dto.recommended_desktop_version,
            server_version=dto.server_version,
            database_schema_version=dto.database_revision,
            desktop_version=desktop_version,
            supported_api_contract_version=get_supported_api_contract_version(),
            minimum_api_version=get_minimum_api_version(),
            server_desktop_state=dto.desktop_state,
        )
    except ValueError:
        add("COMPATIBILITY", DiagnosticStatus.ERROR, 0, "A politica de compatibilidade recebida do servidor e invalida.", error_code=DiagnosticErrorCode.VERSION_METADATA_INVALID)
        return

    detail = f"Desktop: {desktop_version} | API: {dto.server_version} | Min Desktop: {dto.minimum_desktop_version}"
    if state == CompatibilityStatus.COMPATIBLE:
        add("COMPATIBILITY", DiagnosticStatus.OK, 0, f"{detail} -> compativel.")
    elif state in (CompatibilityStatus.UPDATE_AVAILABLE, CompatibilityStatus.UPDATE_RECOMMENDED):
        add("COMPATIBILITY", DiagnosticStatus.WARNING, 0, f"{detail} -> atualizacao recomendada, sem bloqueio.")
    elif state == CompatibilityStatus.UPDATE_REQUIRED:
        add("COMPATIBILITY", DiagnosticStatus.ERROR, 0, detail, error_code=DiagnosticErrorCode.CLIENT_UPDATE_REQUIRED)
    elif state == CompatibilityStatus.SERVER_UPDATE_REQUIRED:
        add("COMPATIBILITY", DiagnosticStatus.ERROR, 0, detail, error_code=DiagnosticErrorCode.SERVER_UPDATE_REQUIRED)
    elif state == CompatibilityStatus.MAINTENANCE:
        add("COMPATIBILITY", DiagnosticStatus.WARNING, 0, f"{detail} -> servidor em manutencao.")
    else:
        # INCOMPATIBLE ou estado desconhecido deste build: contrato de API
        # divergente -- do ponto de vista do Desktop, e o mesmo tipo de
        # acao (build precisa mudar) que CLIENT_UPDATE_REQUIRED.
        add("COMPATIBILITY", DiagnosticStatus.ERROR, 0, f"{detail} -> contrato de API incompativel ({state.value}).", error_code=DiagnosticErrorCode.CLIENT_UPDATE_REQUIRED)


def _probe_ready(
    base_url: str,
    *,
    connect_timeout: float,
    read_timeout: float,
    client_factory=DesktopApiClient,
) -> tuple[int | None, Any, ApiClientError | None]:
    settings = DesktopApiSettings(enabled=True, base_url=base_url, connect_timeout=connect_timeout, read_timeout=read_timeout)
    client = client_factory(settings)
    try:
        status_code, payload = client.get_status_and_payload(HEALTH_PATH)
        return status_code, payload, None
    except ApiClientError as exc:
        return None, None, exc
    finally:
        client.close()


def _overall_status(checks: list[DiagnosticCheck]) -> DiagnosticStatus:
    if any(check.status == DiagnosticStatus.ERROR for check in checks):
        return DiagnosticStatus.ERROR
    if any(check.status == DiagnosticStatus.WARNING for check in checks):
        return DiagnosticStatus.WARNING
    return DiagnosticStatus.OK


def build_report_text(result: DiagnosticResult) -> str:
    """Fase 4, Secao 9: texto estruturado copiavel. Ja recebe o resultado
    sanitizado (api_base_url_sanitized, mensagens sem segredo) -- nenhum
    dado sensivel passa por aqui."""
    lines = [
        "SISTEMA CONTROLE PRODUCAO - DIAGNOSTICO",
        f"Data: {result.started_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Status geral: {result.overall_status.value}",
        f"API: {result.api_base_url_sanitized or '(nao configurada)'}",
        "",
    ]
    for check in result.checks:
        suffix = f" - {check.detail}" if check.detail else ""
        lines.append(f"{check.code}: {check.status.value}{suffix}")
    lines.append("")
    lines.append(f"Resumo: {result.user_message}")
    return "\n".join(lines)
