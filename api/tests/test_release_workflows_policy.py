from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"
CI_YML = WORKFLOWS_DIR / "ci.yml"
RELEASE_YML = WORKFLOWS_DIR / "release-server.yml"

PRODUCTION_JOBS = ("precheck", "deploy", "verify", "rollback", "summary")


def _uncommented(text: str) -> str:
    """Remove linhas de comentario ('#') antes de checagens de substring, para
    nao confundir uma explicacao em comentario (ex.: 'write-all nunca e usado')
    com o uso real da diretiva (mesmo padrao de test_release_compose_policy.py,
    Fase 07)."""
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))


class WorkflowYamlSyntaxTests(unittest.TestCase):
    """Secao 27: validacao sintatica dos YAMLs."""

    def test_all_workflow_files_parse_as_valid_yaml(self):
        files = sorted(WORKFLOWS_DIR.glob("*.yml"))
        self.assertTrue(files, "nenhum workflow encontrado em .github/workflows/")
        for path in files:
            with self.subTest(path=path.name):
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                self.assertIsInstance(data, dict)
                self.assertIn("jobs", data)


class CiWorkflowPolicyTests(unittest.TestCase):
    """Secao 27: CI nao possui acesso a secrets de producao; deploy nao roda em todo push."""

    def setUp(self):
        self.text = CI_YML.read_text(encoding="utf-8")
        self.data = yaml.safe_load(self.text)
        self.uncommented = _uncommented(self.text)

    def test_triggers_on_push_and_pull_request_only_no_tag_trigger(self):
        triggers = self.data["on"]
        self.assertIn("push", triggers)
        self.assertIn("pull_request", triggers)
        self.assertNotIn("tags", triggers.get("push", {}) or {})

    def test_no_environment_declared_anywhere(self):
        for job in self.data["jobs"].values():
            self.assertNotIn("environment", job)

    def test_no_production_secret_references(self):
        self.assertNotIn("secrets.PROD_", self.uncommented)
        self.assertNotIn("secrets.GHCR", self.uncommented)

    def test_permissions_are_minimal_and_explicit(self):
        self.assertIn("permissions", self.data)
        self.assertEqual(self.data["permissions"], {"contents": "read"})

    def test_does_not_use_write_all_permission(self):
        self.assertNotIn("write-all", self.uncommented)

    def test_no_docker_push_or_deploy_action(self):
        self.assertNotIn("docker push", self.uncommented)
        self.assertNotIn("docker/login-action", self.uncommented)


class ReleaseWorkflowPolicyTests(unittest.TestCase):
    """Secao 7-22, 27: gatilho controlado, permissoes minimas, concorrencia,
    separacao de jobs e reuso das Fases 04-08 (nunca reimplementadas em YAML)."""

    def setUp(self):
        self.text = RELEASE_YML.read_text(encoding="utf-8")
        self.data = yaml.safe_load(self.text)
        self.uncommented = _uncommented(self.text)
        self.jobs = self.data["jobs"]

    def test_triggered_only_by_tag_or_manual_dispatch(self):
        triggers = self.data["on"]
        self.assertEqual(set(triggers.keys()), {"push", "workflow_dispatch"})
        self.assertIn("tags", triggers["push"])
        self.assertNotIn("branches", triggers["push"])

    def test_never_triggers_on_push_to_main_branch(self):
        triggers = self.data["on"]
        self.assertNotIn("branches", triggers.get("push", {}))

    def test_release_tag_pattern_is_exclusive_to_server_convention(self):
        tags = self.data["on"]["push"]["tags"]
        self.assertIn("api-v*.*.*", tags)

    def test_workflow_dispatch_requires_explicit_version_input(self):
        inputs = self.data["on"]["workflow_dispatch"]["inputs"]
        self.assertIn("version", inputs)
        self.assertTrue(inputs["version"]["required"])

    def test_top_level_permissions_are_minimal(self):
        self.assertEqual(self.data["permissions"], {"contents": "read"})

    def test_does_not_use_write_all_anywhere(self):
        self.assertNotIn("write-all", self.uncommented)

    def test_packages_write_only_on_build_and_publish_job(self):
        for name, job in self.jobs.items():
            perms = job.get("permissions", {})
            if perms.get("packages") == "write":
                self.assertEqual(name, "build-and-publish", f"packages:write inesperado no job '{name}'")

    def test_ci_x_deploy_separation_test_gate_blocks_build(self):
        self.assertIn("test", self.jobs["build-and-publish"]["needs"])
        self.assertIn("validate-tag", self.jobs["build-and-publish"]["needs"])

    def test_publish_gate_blocks_production_jobs(self):
        self.assertIn("build-and-publish", self.jobs["precheck"]["needs"])
        self.assertIn("check-production-runner", self.jobs["precheck"]["needs"])

    def test_production_jobs_declare_production_environment(self):
        for job_name in PRODUCTION_JOBS:
            self.assertEqual(self.jobs[job_name].get("environment"), "production", f"job '{job_name}' sem environment: production")

    def test_non_production_jobs_do_not_declare_production_environment(self):
        for job_name in ("validate-tag", "test", "build-and-publish", "check-production-runner"):
            self.assertNotIn("environment", self.jobs[job_name])

    def test_production_jobs_run_on_self_hosted_labeled_runner(self):
        for job_name in PRODUCTION_JOBS:
            runs_on = self.jobs[job_name]["runs-on"]
            self.assertIn("self-hosted", runs_on)
            self.assertIn("production", runs_on)
            self.assertIn("deploy", runs_on)

    def test_non_production_jobs_do_not_run_on_self_hosted_runner(self):
        for job_name in ("validate-tag", "test", "build-and-publish", "check-production-runner"):
            runs_on = self.jobs[job_name]["runs-on"]
            self.assertEqual(runs_on, "ubuntu-latest")

    def test_all_production_jobs_share_the_same_exclusive_concurrency_group(self):
        for job_name in PRODUCTION_JOBS:
            concurrency = self.jobs[job_name].get("concurrency")
            self.assertIsNotNone(concurrency, f"job '{job_name}' sem concurrency")
            self.assertEqual(concurrency["group"], "production-deploy")

    def test_concurrency_does_not_cancel_in_progress_production_deploys(self):
        # Secao 9: "nao cancelar um deployment de producao em andamento de forma
        # cega" -- serializacao segura, nunca cancel-in-progress: true.
        for job_name in PRODUCTION_JOBS:
            concurrency = self.jobs[job_name]["concurrency"]
            self.assertFalse(concurrency.get("cancel-in-progress", False))

    def test_no_latest_tag_used_for_deploy(self):
        self.assertNotIn(":latest", self.text)

    def test_rollback_job_reuses_official_phase_08_script(self):
        # Regra de ouro: chama scripts/run_rollback.py (Fase 08), nunca
        # reimplementa pg_dump/comparacao de versao/rollback em YAML.
        rollback_job_text = yaml.dump(self.jobs["rollback"])
        self.assertIn("scripts/run_rollback.py", rollback_job_text)
        self.assertNotIn("pg_dump", self.text)
        self.assertNotIn("docker rm -f controle_producao_api", self.text)

    def test_rollback_only_runs_after_precheck_succeeded_and_deploy_or_verify_failed(self):
        condition = self.jobs["rollback"]["if"]
        self.assertIn("needs.precheck.result == 'success'", condition)
        self.assertIn("needs.deploy.result == 'failure'", condition)
        self.assertIn("needs.verify.result == 'failure'", condition)

    def test_summary_job_always_runs_regardless_of_upstream_outcome(self):
        self.assertEqual(self.jobs["summary"]["if"], "always()")

    def test_build_job_captures_digest_and_never_relies_on_floating_tag_alone(self):
        build_text = yaml.dump(self.jobs["build-and-publish"])
        self.assertIn("digest", build_text)

    def test_no_hardcoded_production_credentials(self):
        # "password:" e um input legitimo de docker/login-action, mas seu VALOR
        # precisa sempre vir de secrets/vars -- nunca um literal hardcoded.
        for line in self.uncommented.splitlines():
            stripped = line.strip()
            if stripped.startswith("password:"):
                self.assertIn("secrets.", stripped, f"linha com credencial hardcoded: {stripped!r}")
        self.assertNotIn("PGPASSWORD=", self.uncommented)
        self.assertNotIn("://admin:", self.uncommented)


if __name__ == "__main__":
    unittest.main()
