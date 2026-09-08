from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSIONS_DIR = ROOT / "api" / "alembic" / "versions"
MANIFEST = ROOT / "api" / "alembic" / "migration_checksums.json"


def migration_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_hashes() -> dict[str, str]:
    return {path.name: migration_hash(path) for path in sorted(VERSIONS_DIR.glob("*.py")) if path.name != "__init__.py"}


def load_manifest() -> dict[str, str]:
    if not MANIFEST.exists():
        return {}
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def write_manifest(hashes: dict[str, str]) -> None:
    MANIFEST.write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify() -> list[str]:
    expected = load_manifest()
    actual = current_hashes()
    errors: list[str] = []
    for name, expected_hash in expected.items():
        actual_hash = actual.get(name)
        if actual_hash is None:
            errors.append(f"Migration ausente: {name}")
        elif actual_hash != expected_hash:
            errors.append(f"Migration alterada: {name}")
    for name in sorted(set(actual) - set(expected)):
        errors.append(f"Migration nova sem checksum: {name}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Verifica checksums das migrations Alembic.")
    parser.add_argument("--update", action="store_true", help="Atualiza o manifesto com as migrations atuais.")
    args = parser.parse_args()
    if args.update:
        write_manifest(current_hashes())
        print(f"Checksums atualizados em {MANIFEST}")
        return
    errors = verify()
    if errors:
        for error in errors:
            print(error)
        raise SystemExit(1)
    print("Checksums das migrations OK.")


if __name__ == "__main__":
    main()
