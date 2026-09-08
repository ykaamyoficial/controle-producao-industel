"""Downloader isolado da UI (Fase 10, Secao 11), com streaming em chunks,
arquivo `.part` enquanto incompleto, limite de tamanho quando conhecido e
retry pequeno somente para erros transitorios. Nao depende de nenhuma classe
de UI do Desktop.

Fonte (Secao 12): aceita um caminho/URI local (`file://` ou caminho absoluto
simples, usado em testes e no modo de recuperacao/desenvolvimento) ou uma URL
http(s) (usada contra um servidor HTTP controlado em testes; a fonte oficial
de producao sera liberada pela Fase 12 -- nunca fixa no codigo, sempre vem do
UpdateRequest.package_url_or_source).
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Callable, ContextManager, Iterator, Protocol
from urllib.parse import urlparse
from urllib.request import url2pathname

from app.version import APP_VERSION

USER_AGENT = f"ControleProducaoUpdater/{APP_VERSION}"
DEFAULT_CHUNK_SIZE = 256 * 1024


class DownloadError(RuntimeError):
    """Falha permanente -- nao deve ser retentada."""


class TransientDownloadError(DownloadError):
    """Falha de rede transitoria -- candidata a retry controlado."""


class StreamingResponse(Protocol):
    status_code: int

    def header(self, name: str) -> str | None: ...
    def iter_bytes(self, chunk_size: int) -> Iterator[bytes]: ...


def _default_stream_opener(url: str, *, connect_timeout: float, read_timeout: float):
    import httpx

    class _HttpxStreamingResponse:
        def __init__(self, response: "httpx.Response"):
            self._response = response
            self.status_code = response.status_code

        def header(self, name: str) -> str | None:
            return self._response.headers.get(name)

        def iter_bytes(self, chunk_size: int) -> Iterator[bytes]:
            yield from self._response.iter_bytes(chunk_size)

    class _Ctx:
        def __enter__(self_inner):
            client = httpx.Client(timeout=httpx.Timeout(connect=connect_timeout, read=read_timeout, write=connect_timeout, pool=connect_timeout))
            self_inner._client = client
            cm = client.stream("GET", url, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
            response = cm.__enter__()
            self_inner._cm = cm
            return _HttpxStreamingResponse(response)

        def __exit__(self_inner, exc_type, exc, tb):
            self_inner._cm.__exit__(exc_type, exc, tb)
            self_inner._client.close()

    return _Ctx()


def _is_http_source(source: str) -> bool:
    return source.startswith("http://") or source.startswith("https://")


def _local_source_path(source: str) -> Path:
    if source.startswith("file://"):
        parsed = urlparse(source)
        return Path(url2pathname(parsed.path))
    return Path(source)


def _derive_filename(source: str) -> str:
    if _is_http_source(source):
        name = Path(urlparse(source).path).name
    else:
        name = _local_source_path(source).name
    return name or "package.bin"


def download_package(
    source: str,
    destination_dir: Path,
    *,
    expected_size: int | None = None,
    connect_timeout: float = 10.0,
    read_timeout: float = 30.0,
    max_retries: int = 2,
    retry_backoff_seconds: float = 1.0,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    stream_opener: Callable[[str], ContextManager[StreamingResponse]] | None = None,
) -> Path:
    """Baixa `source` para `destination_dir`, retornando o caminho final (sem
    `.part`). Levanta DownloadError/TransientDownloadError em falha -- nunca
    retorna um caminho parcial."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    filename = _derive_filename(source)
    final_path = destination_dir / filename
    part_path = destination_dir / f"{filename}.part"

    if not _is_http_source(source):
        return _copy_local_source(source, final_path, part_path, expected_size=expected_size)

    opener = stream_opener or (lambda url: _default_stream_opener(url, connect_timeout=connect_timeout, read_timeout=read_timeout))

    attempt = 0
    last_error: DownloadError | None = None
    while attempt <= max_retries:
        try:
            _stream_to_part(source, part_path, expected_size=expected_size, chunk_size=chunk_size, opener=opener)
            part_path.replace(final_path)
            return final_path
        except TransientDownloadError as exc:
            last_error = exc
            part_path.unlink(missing_ok=True)
            attempt += 1
            if attempt > max_retries:
                break
            time.sleep(retry_backoff_seconds * attempt)
        except DownloadError:
            part_path.unlink(missing_ok=True)
            raise

    part_path.unlink(missing_ok=True)
    raise last_error or DownloadError(f"Falha desconhecida ao baixar '{source}'.")


def _stream_to_part(
    source: str,
    part_path: Path,
    *,
    expected_size: int | None,
    chunk_size: int,
    opener: Callable[[str], ContextManager[StreamingResponse]],
) -> None:
    try:
        with opener(source) as response:
            if response.status_code >= 500:
                raise TransientDownloadError(f"HTTP {response.status_code} ao baixar '{source}' (erro de servidor, transitorio).")
            if response.status_code >= 400:
                raise DownloadError(f"HTTP {response.status_code} ao baixar '{source}'.")

            content_length = response.header("content-length")
            if expected_size is not None and content_length is not None:
                try:
                    if int(content_length) != expected_size:
                        raise DownloadError(
                            f"Tamanho anunciado pelo servidor ({content_length}) diverge do esperado ({expected_size})."
                        )
                except ValueError:
                    pass

            written = 0
            with part_path.open("wb") as handle:
                for chunk in response.iter_bytes(chunk_size):
                    written += len(chunk)
                    if expected_size is not None and written > expected_size:
                        raise DownloadError(f"Pacote excedeu o tamanho esperado ({expected_size} bytes) durante o download.")
                    handle.write(chunk)
    except TransientDownloadError:
        raise
    except DownloadError:
        raise
    except Exception as exc:  # falhas de rede da biblioteca HTTP (timeout, conexao)
        raise TransientDownloadError(f"Falha de rede transitoria ao baixar '{source}': {exc}") from exc

    if expected_size is not None and part_path.stat().st_size != expected_size:
        raise DownloadError(
            f"Download incompleto: {part_path.stat().st_size} bytes recebidos, {expected_size} esperados."
        )


def _copy_local_source(source: str, final_path: Path, part_path: Path, *, expected_size: int | None) -> Path:
    source_path = _local_source_path(source)
    if not source_path.is_file():
        raise DownloadError(f"Fonte local nao encontrada: '{source_path}'.")
    size = source_path.stat().st_size
    if expected_size is not None and size != expected_size:
        raise DownloadError(f"Tamanho da fonte local ({size}) diverge do esperado ({expected_size}).")
    try:
        shutil.copyfile(source_path, part_path)
        part_path.replace(final_path)
    except OSError as exc:
        part_path.unlink(missing_ok=True)
        raise DownloadError(f"Falha ao copiar fonte local '{source_path}': {exc}") from exc
    return final_path
