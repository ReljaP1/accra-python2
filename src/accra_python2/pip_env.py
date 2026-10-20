import os
import shlex
import shutil
import subprocess
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
    PYTHON2_VIRTUALENV_SPEC,
    PYTHON27_IMAGE,
    SOURCE_BUILD_ENV,
    VENV_DIR,
    VENV_PIP,
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


def _environment_commands(python: str) -> list[list[str]]:
    """Commands that create the 2.7 environment. Dockerfile text uses the same list."""
    return [
        [python, "-m", "pip", "install", PYTHON2_VIRTUALENV_SPEC],
        [python, "-m", "virtualenv", VENV_DIR],
        [VENV_PIP, "install", *BOOTSTRAP_SPECS, IGNORE_REQUIRES_PYTHON],
    ]


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
            lines = [line.strip() for line in detail.splitlines() if line.strip()]
            if lines:
                error_line = next(
                    (line for line in reversed(lines) if line.startswith("ERROR")),
                    lines[-1],
                )
                message = f"{message}: {error_line}"
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
        return [
            DockerfileInstruction(f"FROM {PYTHON27_IMAGE}"),
            *[_dockerfile_run(command) for command in _environment_commands("python")],
        ]

    def _prepare_environment(self, python: str) -> AccraResult | None:
        messages = (
            "could not install virtualenv",
            "virtualenv failed",
            "could not bootstrap pip, setuptools, and wheel",
        )
        for command, message in zip(
            _environment_commands(python), messages, strict=True
        ):
            step = self._record(command, message)
            if isinstance(step, AccraResult):
                return step
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
            prepared = self._docker(_environment_commands("python"))
            if not prepared.success:
                return prepared
            result.dockerfile.pre_dependencies_installation.extend(self._image_pre())
            return result

        failed = self._prepare_environment(interpreter)
        if failed is not None:
            return failed

        result.dockerfile.pre_dependencies_installation.extend(self._image_pre())
        return result

    def _pip_install_args(self, spec: str) -> list[str]:
        return [VENV_PIP, "install", spec]

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
        project = self._project_dir()
        if project is None or not (project / "setup.py").is_file():
            return AccraResult()
        command = [f"{VENV_DIR}/bin/python", "setup.py", "build_ext", "--inplace"]
        if self._using_docker:
            built = self._docker([command])
            if not built.success:
                return built
        else:
            compiled = self._run(command)
            if compiled.returncode != 0:
                return self._fail("could not build project extensions", compiled)
        return AccraResult(
            dockerfile=Dockerfile(
                post_dependencies_installation=[_dockerfile_run(command)],
            )
        )
