"""Sanitizacao central de metadata de auditoria (Fase 16, Secao 21/22).

Unico ponto por onde `metadata` passa antes de ser persistida -- nunca
confie em quem chama `record_event` para ja ter sanitizado. Mascara chaves
sensiveis, limita profundidade/tamanho e rejeita tipos nao suportados, para
nunca guardar secrets, dumps de request ou objetos arbitrarios (Secao 21).
"""

from __future__ import annotations

from typing import Any

_REDACTED = "***REDACTED***"
_TRUNCATED_SUFFIX = "...<truncated>"
_MAX_DEPTH_PLACEHOLDER = "<profundidade maxima excedida>"
_UNSUPPORTED_PLACEHOLDER = "<tipo nao suportado>"

# Substring, case-insensitive -- cobre password/senha, token/jwt/refresh_token,
# secret, authorization, cookie, api_key, database_url/connection_string,
# github token/PAT, etc. (Secao 22: "teste chaves como password, token,
# secret, authorization, cookie, api_key, database_url").
_SENSITIVE_KEY_MARKERS = (
    "password", "senha", "token", "secret", "authorization", "cookie",
    "api_key", "apikey", "database_url", "connection_string", "jwt",
    "credential", "pat", "private_key", "access_key",
)

_SUPPORTED_SCALAR_TYPES = (str, int, float, bool, type(None))


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS)


def _truncate_string(value: str, *, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - len(_TRUNCATED_SUFFIX)] + _TRUNCATED_SUFFIX


def _sanitize_value(value: Any, *, depth: int, max_depth: int, max_string_length: int, max_keys: int) -> Any:
    if depth > max_depth:
        return _MAX_DEPTH_PLACEHOLDER
    if isinstance(value, str):
        return _truncate_string(value, max_length=max_string_length)
    if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
        return value
    if isinstance(value, dict):
        return _sanitize_dict(value, depth=depth, max_depth=max_depth, max_string_length=max_string_length, max_keys=max_keys)
    if isinstance(value, (list, tuple, set)):
        items = list(value)[:max_keys]
        return [_sanitize_value(item, depth=depth + 1, max_depth=max_depth, max_string_length=max_string_length, max_keys=max_keys) for item in items]
    # Tipo desconhecido (Secao 22: "rejeita objetos desconhecidos quando
    # necessario") -- nunca serializado as cegas, nunca levanta excecao.
    return _UNSUPPORTED_PLACEHOLDER


def _sanitize_dict(data: dict, *, depth: int, max_depth: int, max_string_length: int, max_keys: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for index, (key, value) in enumerate(data.items()):
        if index >= max_keys:
            result["_truncated_keys"] = len(data) - max_keys
            break
        safe_key = _truncate_string(str(key), max_length=120)
        if _is_sensitive_key(str(key)):
            result[safe_key] = _REDACTED
            continue
        result[safe_key] = _sanitize_value(value, depth=depth + 1, max_depth=max_depth, max_string_length=max_string_length, max_keys=max_keys)
    return result


def sanitize_audit_metadata(
    data: Any,
    *,
    max_depth: int = 3,
    max_string_length: int = 500,
    max_keys: int = 40,
) -> dict[str, Any]:
    """Sempre devolve um dict pronto para `json.dumps`/JSONB -- nunca None,
    nunca levanta excecao para entrada inesperada."""
    if data is None:
        return {}
    if not isinstance(data, dict):
        return {"value": _sanitize_value(data, depth=0, max_depth=max_depth, max_string_length=max_string_length, max_keys=max_keys)}
    return _sanitize_dict(data, depth=0, max_depth=max_depth, max_string_length=max_string_length, max_keys=max_keys)
