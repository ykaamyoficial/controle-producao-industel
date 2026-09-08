from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

from app.services.app_logging import get_logger


log = get_logger("configuration_service")


class ConfigurationService:
    """Unico ponto de leitura/gravacao de um arquivo de configuracao JSON.

    Cada instancia e dona de UM arquivo (`path`) e garante: cache em memoria
    (evita reabrir o arquivo a cada leitura), escrita atomica (grava em um
    arquivo temporario no mesmo diretorio, faz flush/fsync e so entao
    substitui o arquivo original via os.replace — se qualquer etapa falhar
    antes do replace, o arquivo original permanece intacto) e exclusao mutua
    entre leituras/gravacoes concorrentes dentro do processo, via RLock.

    Esta classe e agnostica de dominio: ela nao sabe o que "company",
    "desktop_api" ou "nomus_api" significam, nem quais sao seus valores
    padrao — isso continua sendo responsabilidade de cada consumidor
    (DesktopApiConfigStore, NomusApiConfigStore, backend_adapter). O que ela
    garante e a integridade do arquivo em si: a raiz sempre volta como um
    dicionario valido, nunca None/lista/string, e nunca corrompida por uma
    gravacao concorrente ou incompleta.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._cache: dict[str, Any] | None = None

    def exists(self) -> bool:
        return self.path.exists()

    def load(self, *, force_reload: bool = False) -> dict[str, Any]:
        with self._lock:
            if self._cache is None or force_reload:
                self._cache = self._read_or_create()
            return copy.deepcopy(self._cache)

    def save(self, data: dict[str, Any]) -> dict[str, Any]:
        """Sobrescreve o arquivo inteiro com `data`. Prefira `update(...)`
        quando a intencao for alterar apenas alguns campos — `save` nao
        protege contra um chamador que carregou um snapshot desatualizado."""
        if not isinstance(data, dict):
            raise TypeError("Configuracao deve ser um dicionario.")
        with self._lock:
            snapshot = copy.deepcopy(data)
            self._write_atomic(snapshot)
            self._cache = snapshot
            log.info("Config atualizada (gravacao completa) | arquivo=%s", self.path)
            return copy.deepcopy(self._cache)

    def update(self, mutator: Callable[[dict[str, Any]], dict[str, Any] | None]) -> dict[str, Any]:
        """Atualizacao parcial atomica: le o estado atual, aplica `mutator`
        (que pode alterar o dicionario recebido em memoria e/ou retornar um
        novo dicionario) e grava — tudo dentro da mesma secao critica.

        Substitui o padrao inseguro `config = load(); config[x] = y;
        save(config)`, no qual outra thread poderia gravar uma mudanca entre
        o load e o save e te-la silenciosamente descartada.
        """
        with self._lock:
            current = self._cache if self._cache is not None else self._read_or_create()
            working = copy.deepcopy(current)
            result = mutator(working)
            new_data = result if result is not None else working
            if not isinstance(new_data, dict):
                raise TypeError("Configuracao resultante deve ser um dicionario.")
            self._write_atomic(new_data)
            self._cache = copy.deepcopy(new_data)
            log.info("Config atualizada (atualizacao parcial) | arquivo=%s", self.path)
            return copy.deepcopy(self._cache)

    def _read_or_create(self) -> dict[str, Any]:
        if not self.path.exists():
            log.info("Arquivo de configuracao nao encontrado, criando automaticamente | arquivo=%s", self.path)
            self._write_atomic({})
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, ValueError) as exc:
            log.warning(
                "Falha ao validar configuracao (arquivo corrompido ou ilegivel) — arquivo original preservado no "
                "disco, valores padrao usados apenas em memoria | arquivo=%s | detalhe=%s",
                self.path,
                exc,
            )
            return {}
        if not isinstance(data, dict):
            log.warning(
                "Falha ao validar configuracao (raiz do JSON nao e um objeto) — arquivo original preservado no "
                "disco, valores padrao usados apenas em memoria | arquivo=%s",
                self.path,
            )
            return {}
        log.info("Config carregada | arquivo=%s", self.path)
        return data

    def _write_atomic(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(tmp_name, self.path)
        except Exception:
            log.exception("Erro durante gravacao da configuracao — arquivo original preservado | arquivo=%s", self.path)
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise


_registry: dict[str, ConfigurationService] = {}
_registry_lock = threading.Lock()


def get_configuration_service(path: Path) -> ConfigurationService:
    """Fabrica com registro por caminho: o mesmo arquivo real sempre recebe a
    mesma instancia de ConfigurationService, entao todos os consumidores que
    apontam para o mesmo config.json compartilham cache e lock — inclusive
    quando cada um resolve o path de forma independente (ex.: cada um chama
    o proprio get_config_path()). Caminhos diferentes (ex.: arquivos
    temporarios usados em testes) recebem instancias independentes."""
    key = str(Path(path).expanduser().resolve(strict=False))
    with _registry_lock:
        service = _registry.get(key)
        if service is None:
            service = ConfigurationService(Path(path))
            _registry[key] = service
        return service
