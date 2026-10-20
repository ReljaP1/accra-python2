import os
import shlex
import shutil
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
    PYENV_VERSIONS,
    PYTHON27_IMAGE,
    SOURCE_BUILD_ENV,
    VENV_DIR,
    VENV_PIP,
    VIRTUALENV_SPEC,
)
from .requirements_txt import Requirements_txt
from .setup_cfg import Setup_cfg
from .setup_py import Setup_py
from .utils import install_spec

_SHELL_META = set(" <>|&;$'`\\*?()[]{}")


def host_python27() -> str | None:
    """A CPython 2.7 binary already on PATH, without requiring pyenv."""
    return shutil.which("python2.7")


def _shell_join(commands: list[list[str]]) -> str:
    return " && ".join(
        " ".join(shlex.quote(part) for part in command) for command in commands
    )


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
        self._using_docker = False

    def _command_env(self) -> dict[str, str]:
        config_env = self.spec.config.env
        base = dict(os.environ if config_env is None else config_env)
        for name, value in SOURCE_BUILD_ENV.items():
            base.setdefault(name, value)
        return base

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        config = self.spec.config
        try:
            return subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                cwd=config.cwd,
                env=self._command_env(),
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

    def _pyenv_interpreter(self, version: str) -> str | None:
        probe = self._run(["pyenv", "prefix", version])
        root = probe.stdout.strip()
        if probe.returncode != 0 or not root:
            return None
        return str(Path(root) / "bin" / "python")

    def _find_interpreter(self) -> str | None:
        for version in PYENV_VERSIONS:
            interpreter = self._pyenv_interpreter(version)
            if interpreter:
                return interpreter

        found = host_python27()
        if found:
            return found

        installed = self._run(
            ["pyenv", "install", "--skip-existing", PYENV_VERSIONS[0]]
        )
        if installed.returncode != 0:
            return None
        return self._pyenv_interpreter(PYENV_VERSIONS[0])

    def _docker_available(self) -> bool:
        return self._run(["docker", "info"]).returncode == 0

    def _project_dir(self) -> Path | None:
        cwd = self.spec.config.cwd
        if cwd is None:
            return None
        return Path(cwd).resolve()

    def _docker(self, commands: list[list[str]]) -> AccraResult:
        project = self._project_dir()
        if project is None:
            return self._fail("the project directory is not set")
        completed = self._run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{project}:/project",
                "-w",
                "/project",
                PYTHON27_IMAGE,
                "sh",
                "-c",
                _shell_join(commands),
            ]
        )
        if completed.returncode != 0:
            return self._fail("docker could not run Python 2.7", completed)
        return AccraResult()

    def _image_pre(self) -> list[DockerfileInstruction]:
        bootstrap = [VENV_PIP, "install", *BOOTSTRAP_SPECS, IGNORE_REQUIRES_PYTHON]
        return [
            DockerfileInstruction(f"FROM {PYTHON27_IMAGE}"),
            DockerfileInstruction(f"RUN python -m pip install {VIRTUALENV_SPEC}"),
            DockerfileInstruction(f"RUN python -m virtualenv {VENV_DIR}"),
            _dockerfile_run(bootstrap),
        ]

    def _prepare_host_pip(self) -> AccraResult | None:
        pip_check = self._run([sys.executable, "-m", "pip", "--version"])
        if pip_check.returncode == 0:
            return None
        ensurepip = self._record(
            [sys.executable, "-m", "ensurepip", "--upgrade"],
            "could not install pip",
        )
        if isinstance(ensurepip, AccraResult):
            return ensurepip
        return None

    def pre_dependencies_installation(self) -> AccraResult:
        result = AccraResult()

        language_version: str | AccraError = self.select_language_version()
        if isinstance(language_version, AccraError):
            return AccraResult(errors=[language_version], success=False)

        interpreter = self._find_interpreter()
        if interpreter is None:
            if not self._docker_available():
                return self._fail(
                    "Python 2.7 was not found. Install python2.7, pyenv, or Docker."
                )
            self._using_docker = True
            prepared = self._docker(
                [
                    ["python", "-m", "pip", "install", VIRTUALENV_SPEC],
                    ["python", "-m", "virtualenv", VENV_DIR],
                    [VENV_PIP, "install", *BOOTSTRAP_SPECS, IGNORE_REQUIRES_PYTHON],
                ]
            )
            if not prepared.success:
                return prepared
            result.dockerfile.pre_dependencies_installation.extend(self._image_pre())
            return result

        missing_pip = self._prepare_host_pip()
        if missing_pip is not None:
            return missing_pip

        virtualenv_step = self._record(
            [sys.executable, "-m", "pip", "install", VIRTUALENV_SPEC],
            "could not install virtualenv",
        )
        if isinstance(virtualenv_step, AccraResult):
            return virtualenv_step

        venv_result = self._run(
            [sys.executable, "-m", "virtualenv", "-p", interpreter, VENV_DIR]
        )
        if venv_result.returncode != 0:
            return self._fail("virtualenv failed", venv_result)

        bootstrap_step = self._record(
            [VENV_PIP, "install", *BOOTSTRAP_SPECS, IGNORE_REQUIRES_PYTHON],
            "could not bootstrap pip, setuptools, and wheel",
        )
        if isinstance(bootstrap_step, AccraResult):
            return bootstrap_step

        result.dockerfile.pre_dependencies_installation.extend(self._image_pre())
        return result

    def _pip_install_args(self, spec: str) -> list[str]:
        return [VENV_PIP, "install", spec, IGNORE_REQUIRES_PYTHON]

    def _install_dependency(self, dependency: Dependency) -> AccraResult:
        spec = install_spec(dependency.name, dependency.version)
        if spec is None:
            return AccraResult()

        args = self._pip_install_args(spec)
        if self._using_docker:
            installed = self._docker([args])
            if not installed.success:
                return installed
        else:
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
