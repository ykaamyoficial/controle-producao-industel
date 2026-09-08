---
name: release-checklist
description: Walk through this project's PRECHECK/DEPLOY/VERIFY/ROLLBACK release checklist using its own backup, image-build, and validation scripts. Use before cutting or shipping a release.
---

# Release checklist

This project's real pipeline (`docs/architecture/CI_CD_PIPELINE.md`) is a job
graph: `PRECHECK -> DEPLOY -> VERIFY -> ROLLBACK`. This skill re-derives that
same sequence manually/locally using the scripts that pipeline itself calls —
never invent a shortcut, never skip a gate because "it probably passed".

Read-only steps (1-5, and 6's health check) can run without asking. Any step
that touches a real (non-local/dev) environment — actual deploy, actual
rollback — requires explicit user confirmation first (step 8).

## 1. PRECHECK — version consistency

Confirm the version bump is consistent everywhere it needs to be, since the
image tag and the release manifest both derive from these:

- API/server version: `api/app/core/config.py` -> `API_VERSION`
- Desktop version: `app/version.py` -> `APP_VERSION`

These are two independent axes (API and Desktop release independently) — do
not expect them to be equal, but do confirm each one matches what you intend
to tag/ship in this release.

## 2. Backup — must be usable, not just "ran"

```
python scripts/run_predeployment_backup.py [--target-release-version X.Y.Z] [--build-sha <sha>]
```

Exit code 0 only when **both** conditions hold — check the printed line
(`status=... validation=...`) yourself, don't just trust exit code alone:

- `status=SUCCESS`
- `validation=VALID`

`UNKNOWN` or `INVALID` validation blocks deployment with the same weight as a
failed dump — a file merely existing on disk is never sufficient
(`is_usable_for_deployment` is the one gate: `status == SUCCESS and
validation_status == VALID`). Do not proceed past this step without both
fields confirmed.

## 3. Build the release image

```
python scripts/build_release_image.py --registry <registry> [--tag X.Y.Z]
```

- Omit `--tag` to let it derive from `API_VERSION` (preferred), or pass it
  explicitly — it must equal `API_VERSION` exactly or the script fails.
- Confirm the resulting image reference is `<registry>/controle-producao-api:<API_VERSION>`.
- Never tag or reference `:latest` for a real deployment — banned in
  production paths and enforced by an automated policy test
  (`test_release_compose_policy.py`).

## 4. Validate the built image

```
python scripts/validate_release_image.py \
  --image <registry>/controle-producao-api:<API_VERSION> \
  --network <docker-network-with-postgres> \
  --database-url <postgresql+asyncpg://...> \
  --expected-server-version <API_VERSION>
```

Confirm both:
- Healthcheck reports healthy (container's own `/health/ready`).
- Smoke tests report `PASS` for `server_version` matching `--expected-server-version`.

Do not consider the image deployable until this step's output shows all
green.

## 5. Desktop release artifacts (if this release ships Desktop)

```
python scripts/create_release_files.py
python scripts/generate_release_manifest.py \
  --artifact <path-to-installer> \
  --minimum-server-version <X.Y.Z> \
  --api-contract-version <vN> \
  [--release-version <APP_VERSION>] [--artifact-url ...] [--release-notes ...] [--output <manifest.json>]
```

Confirm the manifest's SHA-256 was computed from the real artifact file by
the script itself — never hand-typed or copied from a prior release.

## 6. DEPLOY / VERIFY (real environment)

After deployment (manual or via the `release-server.yml` pipeline), verify:

- The live service's health endpoint (`/api/v1/health/ready`) reports healthy.
- The reported `server_version` matches `API_VERSION` **exactly** — a
  near-match is a failure, not a warning.

If either check fails, treat this as a VERIFY failure and go to step 7.

## 7. ROLLBACK (only if VERIFY failed, or the user explicitly requests it)

```
python scripts/run_rollback.py --reason "<why>" [--failed-deployment-id <id>]
```

Exit code 0 only when the final state is `ROLLED_BACK`.

Before/while doing this, remind the user explicitly:

- Rollback **only swaps the Docker image** back to the last healthy one —
  **PostgreSQL is never auto-reverted**.
- This is only safe if the prior release's code can still operate correctly
  against the **current** schema. Cross-check any migrations shipped in this
  release against `api/alembic/migration_risk_registry.json` (same registry
  the `migration-check` skill uses) — if any migration in the path is
  classified `DESTRUCTIVE`, automatic rollback is blocked/unsafe and the
  script itself will escalate to `MANUAL_INTERVENTION_REQUIRED` rather than
  improvise a downgrade. Don't declare rollback "safe" without checking this.

## 8. Production-consequence gate

Steps 3-5 build/validate artifacts and are safe to run against local/dev
resources without asking. But before actually **running a deploy or rollback
against a real (staging/production) environment** — not a local Docker
network or dev Postgres — stop and get explicit user confirmation first,
even if every earlier step passed cleanly. State plainly what is about to
happen (which image/version, which environment, backup status) before
proceeding.
