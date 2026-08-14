from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: str
    service: str


class ReadyResponse(BaseModel):
    status: str
    database: str
    mode: str


class VersionResponse(BaseModel):
    api_version: str
    api_stage: str
    database_revision: str | None
    database_status: str
    minimum_desktop_version: str | None = None
    maximum_desktop_version: str | None = None
    supported_features: list[str] = Field(default_factory=list)


class MaintenanceInfo(BaseModel):
    """Resumo de manutencao embutido em /system/compatibility (Fase 14,
    Secao 11) -- o suficiente para o Desktop detectar manutencao numa unica
    consulta. Sempre presente (mesmo em OFF), nunca omitido."""

    model_config = ConfigDict(extra="forbid")

    state: str
    maintenance_id: str
    message: str
    expected_end_at: str | None = None
    retry_after_seconds: int | None = None


class MaintenanceStateResponse(BaseModel):
    """GET /system/maintenance (Fase 14, Secao 10) -- estado completo,
    publico e estavel, acessivel mesmo durante ACTIVE/RECOVERY."""

    model_config = ConfigDict(extra="forbid")

    state: str
    maintenance_id: str
    reason_code: str
    message: str
    scheduled_start_at: str | None = None
    started_at: str | None = None
    expected_end_at: str | None = None
    updated_at: str
    retry_after_seconds: int | None = None


class SystemCompatibilityResponse(BaseModel):
    """Contrato de compatibilidade consultado pelo Desktop (fonte central da Fase 01).

    Campos adicionados na Fase 13 (desktop_state, enforcement,
    authorized_update_version, policy_revision, grace_until, message) sao
    aditivos e sempre tem default seguro -- um cliente anterior a Fase 13
    continua funcionando normalmente ignorando-os. `desktop_state` so e
    calculado quando o cliente informa `?desktop_version=`; caso contrario
    fica `null` (o cliente decide localmente, como antes da Fase 13).

    `maintenance_mode` (Fase 01) e preservado tal qual para clientes
    anteriores a Fase 14: True somente quando `maintenance.state` bloqueia
    operacao (ACTIVE/RECOVERY). `maintenance` (Fase 14, Secao 11) e o
    contrato novo e completo -- Maintenance ACTIVE/RECOVERY tem precedencia
    sobre UPDATE_AVAILABLE/RECOMMENDED na experiencia de entrada do Desktop;
    UPDATE_REQUIRED continua informado nos campos da Fase 13 acima, mas a
    tela principal deve refletir primeiro a manutencao ativa.
    """

    model_config = ConfigDict(extra="forbid")

    server_version: str
    api_contract_version: str
    database_revision: str
    minimum_desktop_version: str
    recommended_desktop_version: str
    maintenance_mode: bool
    maintenance: MaintenanceInfo
    desktop_state: str | None = None
    enforcement: str = "NONE"
    authorized_update_version: str | None = None
    policy_revision: int = 0
    grace_until: str | None = None
    message: str = ""
    # Fase 15 (Secao 15) -- aditivos, sempre com default seguro. desktop_channel
    # e o canal resolvido SERVER-SIDE para esta instalacao (nunca escolhido pelo
    # cliente); production_version/pilot_version sao informativos (a versao
    # efetivamente autorizada para cada canal agora, quando houver).
    desktop_channel: str = "PRODUCTION"
    production_version: str | None = None
    pilot_version: str | None = None


class IdentityResponse(BaseModel):
    instance_id: str
    company_id: str | None = None
    company_code: str
    company_name: str
    environment_type: str
    api_name: str
    api_version: str
    api_stage: str
    database_revision: str
    database_status: str
    minimum_desktop_version: str | None = None
    maximum_desktop_version: str | None = None
    supported_features: list[str] = Field(default_factory=list)
