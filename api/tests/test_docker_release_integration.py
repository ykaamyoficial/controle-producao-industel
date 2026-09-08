from __future__ import annotations

import subprocess
import time
import unittest
import uuid

from api.app.core.config import API_VERSION
from api.app.health.smoke import SmokeTestRunner
from api.tests._docker_test_support import dev_postgres_network, docker_available
from api.tests._migration_test_support import TEST_DATABASE_URL, integration_enabled
from scripts.build_release_image import (
    ReleaseVersionMismatchError,
    build_image,
    inspect_labels,
    resolve_build_time,
    resolve_commit_sha,
    verify_image_identity,
)
from scripts.validate_release_image import start_container, stop_container, wait_healthy

_SKIP_DOCKER = "Docker nao disponivel neste ambiente (Fase 07: testes de identidade real da imagem)."
_SKIP_RUNTIME = "Exige Docker + o Postgres de desenvolvimento (controle_producao_postgres_dev) + POSTGRES_TEST_DATABASE_URL/APP_ENV=test (mesmo guard das Fases 04-06)."


def _network_database_url() -> str:
    # mesmas credenciais de TEST_DATABASE_URL, mas com o host trocado para o
    # nome do servico Docker ("postgres") em vez do endereco publicado no host
    # (127.0.0.1:55432), ja que o container de teste roda dentro da rede Docker.
    return TEST_DATABASE_URL.replace("127.0.0.1:55432", "postgres:5432")


@unittest.skipUnless(docker_available(), _SKIP_DOCKER)
class ReleaseImageBuildIdentityTests(unittest.TestCase):
    """Secao 23/28 da Fase 07: builda a imagem real e valida sua identidade."""

    @classmethod
    def setUpClass(cls):
        cls.image_ref = f"controle-producao-api-test:{uuid.uuid4().hex[:10]}"
        cls.commit_sha = resolve_commit_sha()
        cls.build_time = resolve_build_time()
        build_image(image_ref=cls.image_ref, server_version=API_VERSION, commit_sha=cls.commit_sha, build_time=cls.build_time)

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["docker", "image", "rm", "-f", cls.image_ref], capture_output=True)

    def test_image_carries_expected_oci_labels(self):
        labels = inspect_labels(self.image_ref)
        self.assertEqual(labels.get("org.opencontainers.image.version"), API_VERSION)
        self.assertEqual(labels.get("org.opencontainers.image.revision"), self.commit_sha)
        self.assertEqual(labels.get("org.opencontainers.image.title"), "controle-producao-api")

    def test_verify_identity_passes_for_matching_version(self):
        verify_image_identity(self.image_ref, expected_version=API_VERSION)

    def test_verify_identity_fails_for_mismatched_version(self):
        with self.assertRaises(ReleaseVersionMismatchError):
            verify_image_identity(self.image_ref, expected_version="9.9.9")

    def test_no_env_or_secret_files_are_baked_into_the_image(self):
        result = subprocess.run(
            ["docker", "run", "--rm", self.image_ref, "sh", "-c", "find /app -iname '*.env' -o -iname '*secret*' 2>/dev/null"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.stdout.strip(), "")

    def test_image_does_not_bundle_the_tests_directory(self):
        result = subprocess.run(
            ["docker", "run", "--rm", self.image_ref, "sh", "-c", "test -d /app/api/tests && echo EXISTS || echo ABSENT"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.stdout.strip(), "ABSENT")

    def test_container_runs_as_non_root_user(self):
        result = subprocess.run(["docker", "run", "--rm", self.image_ref, "whoami"], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.stdout.strip(), "apiuser")

    def test_process_starts_without_configuration_instead_of_crash_looping(self):
        # sem DATABASE_URL/SECRET_KEY o processo ainda deve subir (a Fase 01/06
        # ja tratam ausencia de config como readiness=nao-pronto, nunca crash
        # silencioso) -- confirma que o simples startup nao exige credenciais.
        container_name = f"release-config-check-{uuid.uuid4().hex[:8]}"
        run = subprocess.run(["docker", "run", "-d", "--name", container_name, self.image_ref], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        try:
            time.sleep(2)
            status = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Status}}", container_name], capture_output=True, text=True,
            ).stdout.strip()
            self.assertEqual(status, "running")
        finally:
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)


@unittest.skipUnless(docker_available() and integration_enabled() and dev_postgres_network() is not None, _SKIP_RUNTIME)
class ReleaseImageRuntimeSmokeTests(unittest.TestCase):
    """Secao 22/29: container isolado da imagem real + health/smoke da Fase 06
    contra o PostgreSQL de teste descartavel (nunca contra producao)."""

    @classmethod
    def setUpClass(cls):
        cls.image_ref = f"controle-producao-api-test:{uuid.uuid4().hex[:10]}"
        build_image(image_ref=cls.image_ref, server_version=API_VERSION, commit_sha=resolve_commit_sha(), build_time=resolve_build_time())
        cls.network = dev_postgres_network()

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["docker", "image", "rm", "-f", cls.image_ref], capture_output=True)

    def test_isolated_container_reports_correct_version_and_passes_smoke(self):
        container = start_container(
            image=self.image_ref, network=self.network, database_url=_network_database_url(),
            secret_key="release-integration-test-secret-32chars", port=18123,
        )
        try:
            self.assertTrue(wait_healthy(container, timeout_seconds=60), "container nao ficou healthy")
            runner = SmokeTestRunner(base_url="http://127.0.0.1:18123", expected_server_version=API_VERSION)
            report = runner.run()
            self.assertEqual(report.status.value, "PASS", [s.to_dict() for s in report.steps])
            self.assertEqual(report.actual_server_version, API_VERSION)
        finally:
            stop_container(container)


if __name__ == "__main__":
    unittest.main()
