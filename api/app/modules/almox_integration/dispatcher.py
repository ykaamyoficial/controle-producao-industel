"""Envio do webhook ao Almox+. Falha nunca chega à operação que originou o evento: o Almox+ se
corrige pela conciliação (``router.py``). Usa só a biblioteca padrão (sem dependência nova)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from uuid import uuid4

from api.app.modules.almox_integration.signing import sign

log = logging.getLogger("api.almox")

#: A Cloudflare (túnel de api.ykora.com.br e almox.ykora.com.br) bloqueia o User-Agent padrão do
#: urllib com o erro 1010; sem este cabeçalho o webhook seria recusado no caminho público.
USER_AGENT = "Industel-Integracao/1.0 (controle-producao)"


class AlmoxDispatcher:
    def __init__(
        self,
        url: str,
        secret: str,
        *,
        tentativas: int = 3,
        espera_s: float = 1.0,
        timeout_s: float = 5.0,
    ) -> None:
        self.url = url.strip()
        self.secret = secret
        self.tentativas = max(1, tentativas)
        self.espera_s = espera_s
        self.timeout_s = timeout_s

    @property
    def ativo(self) -> bool:
        return bool(self.secret) and urlparse(self.url).scheme in ("http", "https")

    async def enviar_transicao(self, numero: str, estado: str, ocorrido_em: str) -> bool:
        """Envia o evento (mesmo ``event_id`` em todas as tentativas). ``False`` se desistiu."""
        if not self.ativo:
            return False
        corpo = json.dumps(
            {
                "event_id": uuid4().hex,
                "tipo": estado,
                "numero_proposta_nomus": numero,
                "ocorrido_em": ocorrido_em,
            },
            separators=(",", ":"),
        ).encode()
        for tentativa in range(self.tentativas):
            if await asyncio.to_thread(self._post, corpo):
                return True
            if tentativa + 1 < self.tentativas and self.espera_s:
                await asyncio.sleep(self.espera_s * 2**tentativa)
        log.warning("almox_webhook_desistiu numero=%s estado=%s", numero, estado)
        return False

    def _post(self, corpo: bytes) -> bool:
        agora = int(time.time())
        pedido = urllib.request.Request(  # noqa: S310 - esquema validado em ``ativo``
            self.url,
            data=corpo,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "X-Timestamp": str(agora),
                "X-Signature": sign(self.secret, agora, corpo),
            },
        )
        try:
            with urllib.request.urlopen(pedido, timeout=self.timeout_s) as resposta:  # noqa: S310
                return 200 <= resposta.status < 300
        except (urllib.error.URLError, OSError, ValueError) as erro:
            log.info("almox_webhook_falhou erro=%s", erro)
            return False
