from __future__ import annotations

from app.versioning.compatibility import evaluate_desktop, evaluate_startup_compatibility
from app.versioning.models import CompatibilityPolicy, CompatibilityStatus, SemVer, SystemVersionInfo
from app.versioning.parser import compare_versions, is_version_at_least, is_version_newer, parse_version
from app.versioning.versions import build_system_version_info, get_desktop_version, get_minimum_api_version, get_supported_api_contract_version

__all__ = [
    "CompatibilityPolicy",
    "CompatibilityStatus",
    "SemVer",
    "SystemVersionInfo",
    "build_system_version_info",
    "compare_versions",
    "evaluate_desktop",
    "evaluate_startup_compatibility",
    "get_desktop_version",
    "get_minimum_api_version",
    "get_supported_api_contract_version",
    "is_version_at_least",
    "is_version_newer",
    "parse_version",
]
