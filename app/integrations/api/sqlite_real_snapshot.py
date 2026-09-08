from __future__ import annotations

import sys


def main() -> None:
    print(
        "Snapshot de banco desktop antigo desativado no runtime oficial. "
        "Ferramentas historicas ficam em tools.legacy_sqlite_migration.",
        file=sys.stderr,
    )
    raise SystemExit(2)


if __name__ == "__main__":
    main()
