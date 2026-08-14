from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROD_COMPOSE = ROOT / "docker-compose.prod.yml"
DOCKERFILE = ROOT / "api" / "Dockerfile"


def _uncommented(text: str) -> str:
    """Remove linhas de comentario (YAML '#') antes de checagens de substring,
    para nao confundir uma explicacao em comentario ("sem build:") com o uso
    real da diretiva."""
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))


class ProductionComposeDoesNotUseLatestTests(unittest.TestCase):
    """Secao 24: PRODUCAO nunca depende de :latest."""

    def setUp(self):
        self.text = _uncommented(PROD_COMPOSE.read_text(encoding="utf-8"))

    def test_file_exists(self):
        self.assertTrue(PROD_COMPOSE.exists())

    def test_api_image_line_does_not_reference_latest(self):
        image_lines = [line for line in self.text.splitlines() if "image:" in line and "controle-producao-api" in line]
        self.assertTrue(image_lines, "linha 'image:' da API nao encontrada em docker-compose.prod.yml")
        for line in image_lines:
            self.assertNotIn(":latest", line)

    def test_api_image_tag_is_parameterized_by_server_version(self):
        self.assertIn("${SERVER_VERSION", self.text)

    def test_no_bind_mount_of_application_code(self):
        # nao pode existir um "volumes:" no servico api apontando para ./api
        self.assertNotIn("./api:/app/api", self.text)

    def test_no_build_section_only_prebuilt_image_reference(self):
        # producao consome uma imagem ja publicada, nunca builda do codigo fonte do host
        self.assertNotIn("build:", self.text)

    def test_required_variables_have_no_silent_defaults(self):
        for var in ("IMAGE_REGISTRY", "SERVER_VERSION", "SECRET_KEY", "PROVISIONING_SECRET", "NOMUS_ENCRYPTION_KEY"):
            self.assertRegex(self.text, re.escape(f"${{{var}:?"), f"{var} deveria falhar explicitamente se nao definida")


class ProductionComposeApiPortIsLanReachableTests(unittest.TestCase):
    """Fase 1 - Servidor e Endereco Oficial da API: a porta da API precisa ser
    publicada em uma interface alcancavel pela rede local, nunca restrita a
    127.0.0.1 (senao nenhum outro computador da LAN consegue chegar na API).
    PostgreSQL continua sem publicar porta nenhuma (ver servico postgres)."""

    def setUp(self):
        self.text = _uncommented(PROD_COMPOSE.read_text(encoding="utf-8"))

    def test_api_port_publication_is_not_restricted_to_loopback(self):
        port_lines = [line for line in self.text.splitlines() if re.search(r"127\.0\.0\.1.*:\$\{API_PORT", line)]
        self.assertFalse(port_lines, "porta da API nao pode ficar restrita a 127.0.0.1 em producao (LAN nao alcancaria a API)")

    def test_postgres_service_does_not_publish_a_port(self):
        postgres_block = self.text.split("api:")[0]
        self.assertNotIn("ports:", postgres_block, "PostgreSQL nao deve publicar porta para o host em producao")


class ProductionComposeHttpsReverseProxyTests(unittest.TestCase):
    """Fase 5 - HTTPS e Seguranca: existe um unico ponto de terminacao TLS
    (Secao 3), a chave privada nunca e versionada (Secao 5) e a migracao
    permanece incremental -- a porta 8000 continua publicada em paralelo
    (Secao 12, Etapas A-C); fecha-la e passo manual documentado, nao algo
    que este compose faca sozinho."""

    def setUp(self):
        self.text = _uncommented(PROD_COMPOSE.read_text(encoding="utf-8"))

    def test_caddy_service_publishes_443(self):
        self.assertRegex(self.text, r'"\$\{CADDY_BIND_HOST:-0\.0\.0\.0\}:443:443"')

    def test_caddy_tls_material_comes_from_required_env_vars_not_hardcoded_paths(self):
        for var in ("CADDY_HOSTNAME", "CADDY_TLS_CERT_PATH", "CADDY_TLS_KEY_PATH"):
            self.assertRegex(self.text, re.escape(f"${{{var}:?"), f"{var} deveria falhar explicitamente se nao definida")

    def test_no_private_key_file_is_versioned_in_the_repo(self):
        ignored_dirs = {".git", "node_modules", ".venv", "venv", "dist", "build", "release"}
        for pattern in ("*.key", "*.pem"):
            for path in ROOT.rglob(pattern):
                if any(part in ignored_dirs for part in path.parts):
                    continue
                self.fail(f"Arquivo de chave/certificado versionado no repositorio: {path.relative_to(ROOT)}")

    def test_api_port_still_published_alongside_caddy_for_incremental_migration(self):
        # a Fase 5 nao pode remover a porta 8000 silenciosamente -- fechar o
        # acesso direto e uma Etapa D manual, depois de validar HTTPS.
        self.assertRegex(self.text, r'"\$\{API_BIND_HOST:-0\.0\.0\.0\}:\$\{API_PORT:-8000\}:8000"')

    def test_caddyfile_referenced_by_compose_exists_in_repo(self):
        self.assertIn("./Caddyfile:/etc/caddy/Caddyfile", self.text)
        self.assertTrue((ROOT / "Caddyfile").exists())


class DesktopHttpClientNeverBypassesTlsValidationTests(unittest.TestCase):
    """Fase 5, Secao 6/13: nenhum caminho de producao do Desktop desativa a
    validacao de certificado TLS."""

    @staticmethod
    def _production_python_files():
        for base in (ROOT / "app", ROOT / "api"):
            for path in base.rglob("*.py"):
                if "tests" in path.relative_to(ROOT).parts:
                    continue  # codigo de teste referencia esses padroes de proposito para verificar a ausencia deles
                yield path

    def test_no_verify_false_anywhere_in_desktop_or_api_source(self):
        forbidden = re.compile(r"verify\s*=\s*False")
        offenders = [
            str(path.relative_to(ROOT))
            for path in self._production_python_files()
            if forbidden.search(path.read_text(encoding="utf-8", errors="ignore"))
        ]
        self.assertFalse(offenders, f"verify=False encontrado em: {offenders}")

    def test_no_urllib3_warning_suppression_in_desktop_or_api_source(self):
        offenders = []
        for path in self._production_python_files():
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "disable_warnings" in text and "urllib3" in text:
                offenders.append(str(path.relative_to(ROOT)))
        self.assertFalse(offenders, f"supressao de warnings TLS encontrada em: {offenders}")


class DockerfileHardeningTests(unittest.TestCase):
    """Verificacoes estruturais do Dockerfile de release (Secoes 10, 11, 26)."""

    def setUp(self):
        self.text = _uncommented(DOCKERFILE.read_text(encoding="utf-8"))

    def test_base_image_is_pinned_by_tag_and_digest(self):
        self.assertRegex(self.text, r"FROM python:3\.12-slim@sha256:[0-9a-f]{64}")

    def test_does_not_use_floating_python_latest(self):
        self.assertNotIn("python:latest", self.text)

    def test_uses_multi_stage_build(self):
        self.assertIn("AS builder", self.text)
        self.assertIn("AS runtime", self.text)

    def test_switches_to_non_root_user(self):
        self.assertIn("USER apiuser", self.text)

    def test_declares_server_version_build_arg_without_hardcoded_default(self):
        self.assertRegex(self.text, r"ARG SERVER_VERSION\s*\n")

    def test_declares_oci_labels(self):
        for label in (
            "org.opencontainers.image.version",
            "org.opencontainers.image.revision",
            "org.opencontainers.image.created",
            "org.opencontainers.image.title",
        ):
            self.assertIn(label, self.text)

    def test_healthcheck_reuses_phase_06_ready_endpoint(self):
        self.assertIn("/api/v1/health/ready", self.text)
        self.assertNotIn("curl", self.text)
        self.assertNotIn("wget", self.text)

    def test_cmd_never_runs_migrations_automatically(self):
        self.assertNotIn("alembic upgrade", self.text)
        self.assertNotIn("alembic", self.text.split("CMD")[-1])


if __name__ == "__main__":
    unittest.main()
