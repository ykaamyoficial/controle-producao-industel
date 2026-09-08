from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSIONS_DIR = ROOT / "api" / "alembic" / "versions"
REGISTRY = ROOT / "api" / "alembic" / "migration_risk_registry.json"

VALID_CLASSIFICATIONS = {"ADDITIVE", "TRANSITIONAL", "DESTRUCTIVE", "DATA_MIGRATION"}

# Padroes simples (sem parser SQL, de proposito -- ver Fase 04) que sinalizam
# operacoes potencialmente perigosas dentro de upgrade(). Qualquer match exige uma
# classificacao != ADDITIVE + justificativa nao vazia em migration_risk_registry.json.
# Isto e um sinalizador para revisao humana, nao um veredito automatico.
DANGEROUS_PATTERNS = {
    "DROP_TABLE": re.compile(r"op\.drop_table\(|DROP\s+TABLE", re.IGNORECASE),
    "DROP_COLUMN": re.compile(r"op\.drop_column\(|DROP\s+COLUMN", re.IGNORECASE),
    "RENAME": re.compile(r"op\.rename_table\(|RENAME\s+(COLUMN|TO)", re.IGNORECASE),
    "ALTER_TYPE": re.compile(r"op\.alter_column\([^)]*type_\s*=|ALTER\s+COLUMN\s+\S+\s+TYPE", re.IGNORECASE | re.DOTALL),
    "SET_NOT_NULL": re.compile(r"op\.alter_column\([^)]*nullable\s*=\s*False|SET\s+NOT\s+NULL", re.IGNORECASE | re.DOTALL),
    "ADD_UNIQUE_OR_FK": re.compile(
        r"op\.create_unique_constraint\(|op\.create_foreign_key\(|ADD\s+CONSTRAINT\s+\S+\s+(UNIQUE|FOREIGN\s+KEY)",
        re.IGNORECASE,
    ),
    "TRUNCATE": re.compile(r"\bTRUNCATE\b", re.IGNORECASE),
}


def _upgrade_body(source: str) -> str:
    """Isola o corpo de upgrade() (ate a proxima def de nivel 0), para nao marcar
    como risco os drops legitimos que existem dentro de downgrade()."""
    match = re.search(r"^def upgrade\(\)[^\n]*:\n", source, re.MULTILINE)
    if not match:
        return ""
    rest = source[match.end():]
    end_match = re.search(r"^def \w+\(", rest, re.MULTILINE)
    return rest[: end_match.start()] if end_match else rest


def scan_migration(path: Path) -> list[str]:
    body = _upgrade_body(path.read_text(encoding="utf-8"))
    return sorted(name for name, pattern in DANGEROUS_PATTERNS.items() if pattern.search(body))


def _revision_id(path: Path) -> str:
    match = re.search(r'^revision:\s*str\s*=\s*"([^"]+)"', path.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise ValueError(f"Nao foi possivel localizar 'revision' em {path.name}")
    return match.group(1)


def migration_files() -> list[Path]:
    return sorted(path for path in VERSIONS_DIR.glob("*.py") if path.name != "__init__.py")


def load_registry() -> dict[str, dict[str, str]]:
    if not REGISTRY.exists():
        return {}
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def verify() -> list[str]:
    registry = load_registry()
    errors: list[str] = []
    for path in migration_files():
        revision = _revision_id(path)
        entry = registry.get(revision)
        flags = scan_migration(path)
        if entry is None:
            errors.append(f"{path.name} ({revision}): sem entrada em migration_risk_registry.json.")
            continue
        classification = entry.get("classification")
        justification = (entry.get("justification") or "").strip()
        if classification not in VALID_CLASSIFICATIONS:
            errors.append(f"{path.name}: classificacao invalida '{classification}'.")
            continue
        if not justification:
            errors.append(f"{path.name}: entrada no registro sem justificativa.")
        if flags and classification == "ADDITIVE":
            errors.append(f"{path.name}: contem padroes de risco {flags} mas esta classificada como ADDITIVE.")
    for revision in sorted(set(registry) - {_revision_id(p) for p in migration_files()}):
        errors.append(f"Registro orfao: revisao '{revision}' nao corresponde a nenhum arquivo de migration.")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Verifica classificacao/justificativa de risco das migrations Alembic.")
    parser.parse_args()
    errors = verify()
    if errors:
        for error in errors:
            print(error)
        raise SystemExit(1)
    print("Politica de risco das migrations OK.")


if __name__ == "__main__":
    main()
