from __future__ import annotations

from datetime import datetime, timezone

from api.app.health.models import SmokeStatus, SmokeStepResult, SmokeTestReport


class FakeDocker:
    """Substitui api.app.deployment.docker_control nos testes unitarios do
    orquestrador (Fase 08) -- nenhum subprocess/docker real e chamado. Registra
    todas as chamadas para os testes inspecionarem o que o orquestrador teria
    feito de verdade."""

    def __init__(
        self,
        *,
        running_image: str | None = None,
        healthy_after_run: bool = True,
        docker_is_available: bool = True,
        pulled_digest: str | None = None,
        ephemeral_returncode: int = 0,
        ephemeral_stderr: str = "",
    ):
        self.running_image = running_image
        self.healthy_after_run = healthy_after_run
        self.docker_is_available = docker_is_available
        self.pulled_digest = pulled_digest
        self.ephemeral_returncode = ephemeral_returncode
        self.ephemeral_stderr = ephemeral_stderr
        self.calls: list[tuple[str, dict]] = []
        self.stopped: list[str] = []
        self.run_args: list[dict] = []
        self.pulled_images: list[str] = []
        self.ephemeral_commands: list[dict] = []

    def docker_available(self) -> bool:
        return self.docker_is_available

    def pull_image(self, image_ref: str) -> None:
        self.calls.append(("pull_image", {"image_ref": image_ref}))
        self.pulled_images.append(image_ref)

    def image_digest(self, image_ref: str) -> str | None:
        self.calls.append(("image_digest", {"image_ref": image_ref}))
        return self.pulled_digest

    def run_ephemeral(self, *, image_ref: str, command: list[str], network: str, env: dict, timeout: float = 300.0):
        self.calls.append(("run_ephemeral", {"image_ref": image_ref, "command": command, "network": network}))
        self.ephemeral_commands.append({"image_ref": image_ref, "command": command, "network": network, "env": env})
        import subprocess

        return subprocess.CompletedProcess(args=command, returncode=self.ephemeral_returncode, stdout="", stderr=self.ephemeral_stderr)

    def current_image_ref(self, container_name: str) -> str | None:
        self.calls.append(("current_image_ref", {"container_name": container_name}))
        return self.running_image

    def stop_and_remove_container(self, name: str) -> None:
        self.calls.append(("stop_and_remove_container", {"name": name}))
        self.stopped.append(name)
        self.running_image = None

    def run_container(self, *, name: str, image_ref: str, network: str, env: dict, port: int, container_port: int = 8000) -> None:
        self.calls.append(("run_container", {"name": name, "image_ref": image_ref, "network": network, "env": env, "port": port}))
        self.run_args.append({"name": name, "image_ref": image_ref, "network": network, "env": env, "port": port})
        self.running_image = image_ref

    def wait_for_healthy(self, name: str, *, timeout_seconds: float = 60.0, poll_interval_seconds: float = 2.0) -> bool:
        self.calls.append(("wait_for_healthy", {"name": name}))
        return self.healthy_after_run

    def recent_logs(self, name: str, *, tail: int = 200) -> str:
        return "(fake logs)"


def fake_smoke_runner_factory(status: SmokeStatus = SmokeStatus.PASS, *, actual_version_override: str | None = None):
    """Retorna uma factory compativel com DeploymentOrchestrator(smoke_runner_factory=...)
    (Fase 08) e com run_verify.run_verify(runner_factory=...) (Fase 09) que produz um
    runner falso (sem HTTP real) com o status desejado. `actual_version_override`
    permite simular uma resposta com versao divergente da esperada."""

    class _FakeRunner:
        def __init__(self, base_url: str, expected_version: str | None):
            self._base_url = base_url
            self._expected_version = expected_version

        def run(self) -> SmokeTestReport:
            now = datetime.now(timezone.utc)
            step_status = status
            actual_version = actual_version_override if actual_version_override is not None else self._expected_version
            return SmokeTestReport(
                status=status,
                started_at_utc=now,
                completed_at_utc=now,
                target_base_url=self._base_url,
                actual_server_version=actual_version,
                expected_server_version=self._expected_version,
                steps=[SmokeStepResult(name="health_live", status=step_status, duration_ms=5, http_status=200 if step_status == SmokeStatus.PASS else 500)],
            )

    return lambda base_url, expected_version: _FakeRunner(base_url, expected_version)
