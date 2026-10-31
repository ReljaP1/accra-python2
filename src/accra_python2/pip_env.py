import json
import os
import shlex
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

from accra_language import (
    AccraBuildError,
    AccraError,
    AccraFailedDependencyInstallError,
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
    DOCKER_BUILD_PACKAGES,
    DOCKER_PYTHON,
    IGNORE_REQUIRES_PYTHON,
    NOT_PRIMARY_NAMES,
    OPENSSL_PREFIX,
    OPENSSL_VERSION,
    PYENV_ROOT,
    PYENV_VERSIONS,
    PYTHON2_VERSION,
    PYTHON2_VIRTUALENV_SPEC,
    PYTHON27_IMAGE,
    SOURCE_BUILD_ENV,
    VENV_DIR,
    VENV_PIP,
)
from .known_failures import KnownDependencyInstallError, classify
from .requirements_txt import Requirements_txt
from .setup_cfg import Setup_cfg
from .setup_py import Setup_py
from .utils import (
    import_roots,
    install_spec,
    local_top_level_names,
    project_own_names,
)

_SHELL_META = set(" <>|&;$'`\\*?()[]{}")

# How much of a failed install's output an error keeps.
_STDERR_TAIL = 2000


def python2_version_order(versions: set[str]) -> list[str]:
    """Python 2.7, the only version of this plugin, first; the rest, newest first."""
    rest = sorted(versions - {PYTHON2_VERSION}, reverse=True)
    return [PYTHON2_VERSION, *rest] if PYTHON2_VERSION in versions else rest


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
            version_order=python2_version_order,
        )
        super().__init__(spec)
        self._using_docker = False

    def _command_env(self) -> dict[str, str]:
        config_env = self.spec.config.env
        base = dict(os.environ if config_env is None else config_env)
        for name, value in SOURCE_BUILD_ENV.items():
            base.setdefault(name, value)
        return base

    def _run(
        self,
        args: list[str],
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        config = self.spec.config
        try:
            return subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                cwd=config.cwd,
                env=self._command_env() if env is None else env,
                shell=config.shell,
                timeout=config.timeout if timeout is None else timeout,
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

    def _image_toolchain(self) -> list[DockerfileInstruction]:
        """Python 2.7.18 on the bare Debian base: build dependencies, OpenSSL 1.1.1
        (the `ssl` module of 2.7.18 cannot build against OpenSSL 3), pyenv, and the
        interpreter compiled with pyenv. Each step skips what is already there."""
        openssl = f"openssl-{OPENSSL_VERSION}"
        libssl = f"{OPENSSL_PREFIX}/lib/libssl.so.1.1"
        flags = (
            f"CPPFLAGS=-I{OPENSSL_PREFIX}/include "
            f'LDFLAGS="-L{OPENSSL_PREFIX}/lib -Wl,-rpath,{OPENSSL_PREFIX}/lib" '
            f"PYENV_ROOT={PYENV_ROOT} MAKE_OPTS=-j$(nproc)"
        )
        return [
            DockerfileInstruction(
                "RUN apt-get update && apt-get install -y "
                + " ".join(DOCKER_BUILD_PACKAGES)
            ),
            DockerfileInstruction(
                f"RUN [ -f {libssl} ] || (cd /tmp && curl -fsSL "
                f"https://www.openssl.org/source/{openssl}.tar.gz | tar xz && "
                f"cd {openssl} && ./config --prefix={OPENSSL_PREFIX} --libdir=lib "
                "--openssldir=/usr/lib/ssl shared zlib && make -j$(nproc) && "
                f"make install_sw && cd /tmp && rm -rf {openssl})"
            ),
            DockerfileInstruction(
                f"RUN [ -d {PYENV_ROOT}/.git ] || git clone --depth 1 "
                f"https://github.com/pyenv/pyenv.git {PYENV_ROOT}"
            ),
            DockerfileInstruction(
                f"RUN {flags} {PYENV_ROOT}/bin/pyenv install --skip-existing "
                f"{PYENV_VERSIONS[0]}"
            ),
        ]

    def _image_pre(self) -> list[DockerfileInstruction]:
        venv = f"{self.spec.config.image_workdir.rstrip('/')}/{VENV_DIR}"
        return [
            *self._image_toolchain(),
            *[_dockerfile_run(c) for c in _environment_commands(DOCKER_PYTHON)],
            DockerfileInstruction(f"ENV VIRTUAL_ENV={venv}"),
            DockerfileInstruction(f'ENV PATH="{venv}/bin:$PATH"'),
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

    def _failed_dependency(
        self,
        dependency: Dependency,
        message: str,
        detail: str = "",
        output: str = "",
    ) -> AccraResult:
        """One dependency that did not install; the build goes on with the rest.
        A known native-build failure (`known_failures`) is reported as a
        `KnownDependencyInstallError`, so a caller can tell it from an unknown one;
        `output` is the failed install's own output."""
        text = f"{message}: {detail}" if detail else message
        found = classify(dependency.name, f"{text}\n{output}")
        arguments = {
            "message": text,
            "dependency": dependency,
            "environment_manager": self,
            "stderr": output[-_STDERR_TAIL:] if output else None,
        }
        if found is None:
            return AccraResult(errors=[AccraFailedDependencyInstallError(**arguments)])
        kind, signature = found
        return AccraResult(
            errors=[
                KnownDependencyInstallError(
                    known_failure=kind, signature=signature, **arguments
                )
            ]
        )

    def _pip_install_args(self, spec: str) -> list[str]:
        return [VENV_PIP, "install", spec]

    def _install_dependency(self, dependency: Dependency) -> AccraResult:
        spec = install_spec(dependency.name, dependency.version)
        if spec is None:
            return AccraResult()

        args = self._pip_install_args(spec)
        message = f"{self.spec.name} could not install dependency: {spec}"
        if self._using_docker:
            installed = self._docker([args])
            if not installed.success:
                return self._failed_dependency(
                    dependency, message, installed.errors[0].message
                )
        else:
            install_result = self._run(args)
            if install_result.returncode != 0:
                failed = self._fail(message, install_result)
                return self._failed_dependency(
                    dependency,
                    failed.errors[0].message,
                    output=(install_result.stderr or "")
                    + "\n"
                    + (install_result.stdout or ""),
                )

        return AccraResult(
            dockerfile=Dockerfile(
                dependencies_installation=[_dockerfile_run(args)],
            )
        )

    def environment_path(self) -> Path | None:
        project = self._project_dir()
        return None if project is None else project / VENV_DIR

    def run_environment(self, base_env: Mapping[str, str]) -> dict[str, str]:
        """The venv activated, as `source .venv/bin/activate` does."""
        env = dict(base_env)
        path = self.environment_path()
        if path is None:
            return env
        env["VIRTUAL_ENV"] = str(path)
        env["PATH"] = str(path / "bin") + os.pathsep + env.get("PATH", "")
        return env

    def installed_dependencies(self) -> set[Dependency] | AccraError:
        path = self.environment_path()
        if path is None:
            return AccraInstallError(message="the project directory is not set")
        listed = self._run([str(path / "bin" / "pip"), "list", "--format=json"])
        if listed.returncode != 0:
            return AccraInstallError(message="pip could not list the packages")
        try:
            return {
                Dependency(name=str(p["name"]), version=f"=={p['version']}")
                for p in json.loads(listed.stdout or "[]")
            }
        except (ValueError, KeyError, TypeError) as exc:
            return AccraInstallError(message=f"unreadable pip list output: {exc}")

    def _cython_sources(self, project: Path) -> bool:
        return any(
            path.suffix == ".pyx" and ".venv" not in path.parts
            for path in project.rglob("*.pyx")
        )

    def _install_cython_for_extensions(self) -> AccraResult | None:
        """Install the Python 2.7 Cython pin when the checkout has Cython sources."""
        project = self._project_dir()
        if project is None or not self._cython_sources(project):
            return None
        probe = self._run([f"{VENV_DIR}/bin/python", "-c", "import Cython"])
        if probe.returncode == 0:
            return None
        spec = install_spec("cython", "")
        if spec is None:
            return None
        args = [VENV_PIP, "install", spec, IGNORE_REQUIRES_PYTHON]
        if self._using_docker:
            installed = self._docker([args])
            if not installed.success:
                return installed
        else:
            installed = self._run(args)
            if installed.returncode != 0:
                return self._fail("could not install Cython", installed)
        return AccraResult(
            dockerfile=Dockerfile(
                post_dependencies_installation=[_dockerfile_run(args)],
            )
        )

    def _build_extensions(self, project: Path) -> AccraResult:
        """The project's C extensions, built in place (Cython first when it has
        `.pyx` sources); nothing without a `setup.py`."""
        if not (project / "setup.py").is_file():
            return AccraResult()
        instructions: list[DockerfileInstruction] = []
        cython = self._install_cython_for_extensions()
        if isinstance(cython, AccraResult):
            if not cython.success:
                return cython
            instructions.extend(cython.dockerfile.post_dependencies_installation)
        command = [f"{VENV_DIR}/bin/python", "setup.py", "build_ext", "--inplace"]
        if self._using_docker:
            built = self._docker([command])
            if not built.success:
                return built
        else:
            compiled = self._run(command)
            if compiled.returncode != 0:
                return self._fail("could not build project extensions", compiled)
        instructions.append(_dockerfile_run(command))
        return AccraResult(
            dockerfile=Dockerfile(
                post_dependencies_installation=instructions,
            )
        )

    def _has_setup_file(self, project: Path) -> bool:
        """A `setup.py` or `setup.cfg`."""
        return any((project / name).is_file() for name in ("setup.py", "setup.cfg"))

    def _source_mode_lines(self, project: Path) -> list[DockerfileInstruction]:
        workdir = self.spec.config.image_workdir.rstrip("/")
        roots = [
            workdir if r == "." else f"{workdir}/{r}" for r in import_roots(project)
        ]
        return [DockerfileInstruction(f"ENV PYTHONPATH={':'.join(roots)}")]

    def _source_path(self, project: Path, workdir: str | None = None) -> str:
        base = str(project) if workdir is None else workdir.rstrip("/")
        return os.pathsep.join(
            base if r == "." else f"{base}/{r}" for r in import_roots(project)
        )

    def _install_project(self, project: Path) -> AccraResult:
        """With a `setup.py` or `setup.cfg`, `pip install -e` of the project;
        without one the project runs from source and the Dockerfile puts its
        import roots on PYTHONPATH."""
        if not self._has_setup_file(project):
            return AccraResult(
                dockerfile=Dockerfile(
                    post_dependencies_installation=self._source_mode_lines(project)
                )
            )
        args = [VENV_PIP, "install", "-e", "."]
        try:
            if self._using_docker:
                installed = self._docker([args])
                failure = None if installed.success else installed.errors[0].message
            else:
                completed = self._run(
                    [VENV_PIP, "install", "-e", str(project)],
                    timeout=self.subprocess_timeout(),
                )
                failure = None
                if completed.returncode != 0:
                    failed = self._fail("pip could not install the project", completed)
                    failure = failed.errors[0].message
        except (subprocess.SubprocessError, OSError) as exc:
            failure = f"pip could not install the project: {exc}"
        if failure is not None:
            return AccraResult(
                dockerfile=Dockerfile(
                    post_dependencies_installation=self._source_mode_lines(project)
                ),
                errors=[AccraBuildError(message=failure)],
                success=False,
            )
        return AccraResult(
            dockerfile=Dockerfile(
                post_dependencies_installation=[_dockerfile_run(args)]
            )
        )

    def _primary_packages(self, project: Path) -> list[str]:
        """The project's top-level packages and modules, never its tests,
        documentation or examples."""
        return sorted(
            name
            for name in local_top_level_names(project)
            if name.replace("-", "_").lower() not in NOT_PRIMARY_NAMES
        )

    def _imports(self, project: Path, name: str) -> bool | None:
        """Whether `import <name>` works with the environment's python, from the
        project with its import roots on PYTHONPATH; None when the check cannot
        run."""
        path = self.environment_path()
        if path is None:
            return None
        interpreter = path / "bin" / "python"
        if not self._using_docker and not interpreter.is_file():
            return None
        try:
            if self._using_docker:
                workdir = self.spec.config.image_workdir
                imported = self._docker(
                    [
                        [
                            "env",
                            f"PYTHONPATH={self._source_path(project, workdir)}",
                            f"{VENV_DIR}/bin/python",
                            "-c",
                            f"import {name}",
                        ]
                    ]
                )
                return imported.success
            env = self.run_environment(self._command_env())
            env["PYTHONPATH"] = os.pathsep.join(
                p for p in (self._source_path(project), env.get("PYTHONPATH")) if p
            )
            completed = self._run(
                [str(interpreter), "-c", f"import {name}"],
                env=env,
                timeout=self.subprocess_timeout(),
            )
            return completed.returncode == 0
        except (subprocess.SubprocessError, OSError):
            return None

    def post_dependencies_installation(self) -> AccraResult:
        """Builds the project's extensions and installs it (`pip install -e`
        with a `setup.py` or `setup.cfg`, else from source). Python 2 projects
        run from their sources, so this never fails the build: when none of the
        project's packages imports, it records why in the errors, and the
        project counts as not initialised."""
        project = self._project_dir()
        if project is None:
            return AccraResult(
                errors=[AccraBuildError(message="the project directory is not set")]
            )
        lines: list[DockerfileInstruction] = []
        problems: list[AccraError] = []
        for step in (self._build_extensions(project), self._install_project(project)):
            lines.extend(step.dockerfile.post_dependencies_installation)
            problems.extend(step.errors)
        result = AccraResult(
            dockerfile=Dockerfile(post_dependencies_installation=lines)
        )
        # a project with no package of its own counts as usable, whatever failed
        candidates = self._primary_packages(project)
        if candidates and not any(
            self._imports(project, name) is not False for name in candidates
        ):
            result.errors.extend(problems)
            result.errors.append(
                AccraBuildError(
                    message="none of the project's packages imports: "
                    + ", ".join(candidates)
                )
            )
        return result

    def project_names(self) -> set[str]:
        """The project's own top-level modules and packages (at its root and in
        `src/`) and the name of its setup.py or setup.cfg, as written."""
        project = self._project_dir()
        return set() if project is None else project_own_names(project)
