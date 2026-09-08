---
name: migration-check
description: Classify a new Alembic migration's risk level, write its migration_risk_registry.json entry with justification, and verify it passes the project's migration safety checks. Use after creating/editing an Alembic revision under api/alembic/versions/.
---

# Migration risk check

Goal: make a new/changed Alembic migration pass the project's migration safety gate
on the first try.

## 1. Identify the migration(s)

```
git status api/alembic/versions/
git diff --stat api/alembic/versions/
```

For each new/changed file, find its revision id:

```
grep '^revision: str' api/alembic/versions/<file>.py
```

## 2. Read and judge the migration honestly

Open the file and read `upgrade()` (and `downgrade()`). Decide the classification:

- **ADDITIVE** — pure addition with zero data-loss risk: new table, new nullable
  column, new column with `server_default`, new index. Nothing existing is
  touched in a way that could break old readers.
- **TRANSITIONAL** — reversible but touches existing structure carefully: new FK
  on an existing table, widening a CHECK constraint, relaxing NOT NULL to
  nullable, a dual-write/expand step ahead of a later backfill.
- **DATA_MIGRATION** — the main job is transforming/backfilling existing data
  (DML: `INSERT`/`UPDATE`/`UPSERT`), little or no DDL.
- **DESTRUCTIVE** — anything that can lose data or break old code reading the
  same table: `DROP_TABLE`, `DROP_COLUMN`, `RENAME`, `TRUNCATE`, `ALTER_TYPE`,
  or `SET_NOT_NULL` without a prior backfill.

`scripts/check_migration_safety.py` is a regex linter (no SQL parser) that scans
only the `upgrade()` body for these dangerous patterns: `DROP_TABLE`,
`DROP_COLUMN`, `RENAME`, `ALTER_TYPE`, `SET_NOT_NULL`, `ADD_UNIQUE_OR_FK`,
`TRUNCATE`. If any pattern is flagged, the classification **cannot** be
`ADDITIVE` — the linter hard-fails that combination. Note `ADD_UNIQUE_OR_FK`
fires even for a unique/FK constraint added on a brand-new table; in that case
classify `TRANSITIONAL`, not `ADDITIVE` (see existing entries for
`20260812_0019` / `20260812_0020` in the registry for the precedent).

## 3. Write a specific, honest justification

No generic placeholders ("ok", "safe migration"). Explain concretely why this
change is safe at the classification given — e.g. "coluna nova com
server_default, sem backfill necessario" or "TRUNCATE em tabela ja vazia,
confirmado por auditoria X". Look at existing entries in
`api/alembic/migration_risk_registry.json` for the expected tone/detail level.

## 4. Add/update the registry entry

Edit `api/alembic/migration_risk_registry.json` — a flat JSON dict keyed by the
`revision` string, each value `{"classification", "summary", "justification"}`
in that key order, 2-space indent. Every file under `api/alembic/versions/`
must have exactly one matching entry; an entry with no matching file becomes an
"orphaned" registry error, so renaming/deleting a migration file requires
updating the registry too.

## 5. Run the safety linter

```
python scripts/check_migration_safety.py
```

Success prints `Politica de risco das migrations OK.` and exits 0. Iterate on
classification/justification until it passes — don't loosen a classification
just to silence the linter; fix the migration or accept the honest label.

## 6. Run the checksum guard

```
python scripts/check_migration_checksums.py
```

This hashes every file in `api/alembic/versions/` against
`api/alembic/migration_checksums.json` to catch edits to already-applied
migrations. Only run `python scripts/check_migration_checksums.py --update` if
the file is a genuinely brand-new migration that was never previously
committed/applied. Never use `--update` to paper over an edit to an existing,
already-committed migration — that defeats the check. If the checksum guard
flags a file you edited and it was already applied/committed before your
change, that's a signal to add a new forward migration instead of editing
history.

## 7. Run the policy test

```
python -m pytest tests/test_migration_safety_policy.py -q
```

(Note: root `tests/`, not `api/tests/`.) This must stay green — it re-asserts
the linter passes, that the registry keys exactly match the versions folder,
and that specific known-destructive historical migrations (`20260720_0005`,
`20260807_0014`) keep their `DESTRUCTIVE` classification.

## 8. Flag DESTRUCTIVE / DATA_MIGRATION to the user

If the migration you just classified is `DESTRUCTIVE` or `DATA_MIGRATION`,
say so explicitly in your final response before considering the task done —
these need human sign-off. Don't silently mark it "safe" and move on. For
`DESTRUCTIVE` changes, point out whether an EXPAND -> MIGRATE -> CONTRACT
alternative (see `docs/architecture/DATABASE_MIGRATIONS.md`) was available
instead.
