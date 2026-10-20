import shlex
import subprocess
import sys
from pathlib import Path

from accra_language import (
    AccraError,
    AccraInstallError,
    AccraResult,
    Config,
    Dependency,
    Dockerfile,
    DockerfileInstruction,
    EnvironmentManager,
    EnvironmentManagerSpec,
)

from .adhoc import Adhoc
from .constants import (
    BOOTSTRAP_SPECS,
    IGNORE_REQUIRES_PYTHON,
    VENV_DIR,
    VENV_PIP,
    VIRTUALENV_SPEC,
)
from .requirements_txt import Requirements_txt
from .setup_cfg import Setup_cfg
from .setup_py import Setup_py
from .utils import install_spec

_SHELL_META = set(" <>|&;$'`\\*?()[]{}")


def _dockerfile_run(args: list[str]) -> DockerfileInstruction:
    rendered: list[str] = []
    for arg in args:
        if any(character in arg for character in _SHELL_META):
            rendered.append(shlex.quote(arg))
        else:
            rendered.append(arg)
    return DockerfileInstruction("RUN " + " ".join(rendered))


class Pip(EnvironmentManager):
    def __init__(self, config: Config):
        spec = EnvironmentManagerSpec(
            name="pip",
            version="20.3",
            supported_manifests={
                Adhoc(config),
                Requirements_txt(config),
                Setup_cfg(config),
                Setup_py(config),
            },
            config=config,
        )
        super().__init__(spec)

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        config = self.spec.config
        try:
            return subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                cwd=config.cwd,
                env=config.env,
                shell=config.shell,
                timeout=config.timeout,
            )
        except FileNotFoundError:
            return subprocess.CompletedProcess(
                args,
                127,
                "",
                f"{args[0]}: command not found",
            )

    def _fail(
        self, message: str, result: subprocess.CompletedProcess[str] | None = None
    ) -> AccraResult:
        if result is not None:
            detail = (result.stderr or result.stdout or "").strip()
            if detail:
                message = f"{message}: {detail.splitlines()[-1]}"
        return AccraResult(
            errors=[AccraInstallError(message=message)],
            success=False,
        )

    def _record(
        self, args: list[str], message: str
    ) -> AccraResult | DockerfileInstruction:
        completed = self._run(args)
        if completed.returncode != 0:
            return self._fail(message, completed)
        return _dockerfile_run(args)

    def pre_dependencies_installation(self) -> AccraResult:
        result = AccraResult()

        language_version: str | AccraError = self.select_language_version()
        if isinstance(language_version, AccraError):
            return AccraResult(errors=[language_version], success=False)

        pyenv_args = ["pyenv", "install", "--skip-existing", language_version]
        pyenv_step = self._record(
            pyenv_args,
            f"pyenv could not install python2 version: {language_version}",
        )
        if isinstance(pyenv_step, AccraResult):
            return pyenv_step
        result.dockerfile.pre_dependencies_installation.append(pyenv_step)

        ensurepip_args = [sys.executable, "-m", "ensurepip", "--upgrade"]
        ensurepip_step = self._record(ensurepip_args, "could not install pip")
        if isinstance(ensurepip_step, AccraResult):
            return ensurepip_step
        result.dockerfile.pre_dependencies_installation.append(
            DockerfileInstruction("RUN python -m ensurepip --upgrade")
        )

        virtualenv_install = [sys.executable, "-m", "pip", "install", VIRTUALENV_SPEC]
        virtualenv_step = self._record(
            virtualenv_install, "could not install virtualenv"
        )
        if isinstance(virtualenv_step, AccraResult):
            return virtualenv_step
        result.dockerfile.pre_dependencies_installation.append(
            _dockerfile_run(["python", "-m", "pip", "install", VIRTUALENV_SPEC])
        )

        prefix_result = self._run(["pyenv", "prefix", language_version])
        if prefix_result.returncode != 0:
            return self._fail(
                f"pyenv prefix failed for python2 version: {language_version}",
                prefix_result,
            )
        interpreter = str(Path(prefix_result.stdout.strip()) / "bin" / "python")
        venv_result = self._run(
            [sys.executable, "-m", "virtualenv", "-p", interpreter, VENV_DIR]
        )
        if venv_result.returncode != 0:
            return self._fail("virtualenv failed", venv_result)
        result.dockerfile.pre_dependencies_installation.append(
            DockerfileInstruction(
                "RUN python -m virtualenv -p "
                f'"$(pyenv prefix {language_version})/bin/python" {VENV_DIR}'
            )
        )

        bootstrap_args = [VENV_PIP, "install", *BOOTSTRAP_SPECS, IGNORE_REQUIRES_PYTHON]
        bootstrap_step = self._record(
            bootstrap_args,
            "could not bootstrap pip, setuptools, and wheel",
        )
        if isinstance(bootstrap_step, AccraResult):
            return bootstrap_step
        result.dockerfile.pre_dependencies_installation.append(bootstrap_step)

        return result

    def _pip_install_args(self, spec: str) -> list[str]:
        return [VENV_PIP, "install", spec, IGNORE_REQUIRES_PYTHON]

    def _install_dependency(self, dependency: Dependency) -> AccraResult:
        spec = install_spec(dependency.name, dependency.version)
        if spec is None:
            return AccraResult()

        args = self._pip_install_args(spec)
        install_result = self._run(args)
        if install_result.returncode != 0:
            return self._fail(
                f"{self.spec.name} could not install dependency: {spec}",
                install_result,
            )

        return AccraResult(
            dockerfile=Dockerfile(
                dependencies_installation=[_dockerfile_run(args)],
            )
        )

    def post_dependencies_installation(self) -> AccraResult:
        return AccraResult()
