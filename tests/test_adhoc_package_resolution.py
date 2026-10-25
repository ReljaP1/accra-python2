import shutil
import subprocess
from pathlib import Path

import pytest
from accra_language import AccraResult, Config

from accra_python2 import Pip, Python2
from accra_python2.adhoc import Adhoc
from accra_python2.constants import (
    DOCKER_PYTHON,
    PYTHON2_VIRTUALENV_SPEC,
    PYTHON27_IMAGE,
)

_BOOTSTRAP = (
    "RUN .venv/bin/pip install 'pip<21' 'setuptools<45' 'wheel<0.35' "
    "--ignore-requires-python"
)


def _fake_run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
    stdout = "/tmp/pyenv/versions/2.7\n" if args[:2] == ["pyenv", "prefix"] else ""
    return subprocess.CompletedProcess(args, 0, stdout, "")


def test_adhoc_package_resolution(monkeypatch):
    monkeypatch.setattr(Pip, "_run", _fake_run)

    project_dir = Path(__file__).resolve().parent / Path(
        "fixtures/adhoc-module-project"
    )
    tmp_dir = Path("/tmp/adhoc-module-project-py2")

    shutil.rmtree(tmp_dir, ignore_errors=True)
    shutil.copytree(project_dir, tmp_dir)

    try:
        config = Config(cwd=tmp_dir)
        python2 = Python2(config)

        assert python2.detect() is True

        result: AccraResult = python2.build()
        assert result.success
        pre = result.dockerfile.pre_dependencies_installation
        assert pre[0].startswith("RUN apt-get update && apt-get install -y ")
        assert "pyenv install --skip-existing 2.7.18" in pre[3]
        assert pre[4:] == [
            f"RUN {DOCKER_PYTHON} -m pip install {PYTHON2_VIRTUALENV_SPEC}",
            f"RUN {DOCKER_PYTHON} -m virtualenv .venv",
            _BOOTSTRAP,
            "ENV VIRTUAL_ENV=/project/.venv",
            'ENV PATH="/project/.venv/bin:$PATH"',
        ]
        assert result.dockerfile.dependencies_installation == [
            "RUN .venv/bin/pip install six"
        ]
        assert result.dockerfile.post_dependencies_installation == []
    finally:
        shutil.rmtree(tmp_dir)


def test_pyenv_failure_stops_the_build(monkeypatch, tmp_path: Path):
    def fail_run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 1, "", "pyenv missing")

    monkeypatch.setattr("accra_python2.pip_env.host_python27", lambda: None)
    monkeypatch.setattr(Pip, "_run", fail_run)
    source = tmp_path / "legacy.py"
    source.write_text("import six\n", encoding="utf-8")

    result = Python2(Config(cwd=tmp_path)).build()
    assert result.success is False
    assert result.errors
    assert result.dockerfile.pre_dependencies_installation == []


def _command_ok(args: list[str]) -> bool:
    try:
        probe = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False
    return probe.returncode == 0


def _python27_available() -> bool:
    if shutil.which("python2.7"):
        return True
    if _command_ok(["pyenv", "prefix", "2.7.18"]) or _command_ok(
        ["pyenv", "prefix", "2.7"]
    ):
        return True
    return _command_ok(["docker", "info"])


@pytest.mark.skipif(
    not _python27_available(),
    reason="no python2.7, pyenv, or Docker",
)
def _remove_project(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
    if not path.exists() or not _command_ok(["docker", "info"]):
        return
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{path.parent.resolve()}:/cleanup",
            "-w",
            "/cleanup",
            PYTHON27_IMAGE,
            "rm",
            "-rf",
            path.name,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _import_six(project: Path) -> subprocess.CompletedProcess[str]:
    interpreter = project / ".venv" / "bin" / "python"
    imported = subprocess.run(
        [str(interpreter), "-c", "import six"],
        check=False,
        capture_output=True,
        text=True,
    )
    # A venv built inside python:2.7 is linked to that image's libpython.
    # The host can run it only when the same library is installed locally.
    if imported.returncode == 0 or "libpython2.7" not in imported.stderr:
        return imported
    return subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{project.resolve()}:/project",
            "-w",
            "/project",
            PYTHON27_IMAGE,
            ".venv/bin/python",
            "-c",
            "import six",
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_real_python27_installs_six():
    project_dir = Path(__file__).resolve().parent / Path(
        "fixtures/adhoc-module-project"
    )
    tmp_dir = Path("/tmp/adhoc-module-project-py2-real")

    _remove_project(tmp_dir)
    shutil.copytree(project_dir, tmp_dir)

    try:
        result = Python2(Config(cwd=tmp_dir)).build()
        assert result.success, [error.message for error in result.errors]
        interpreter = tmp_dir / ".venv" / "bin" / "python"
        assert interpreter.is_file()
        imported = _import_six(tmp_dir)
        assert imported.returncode == 0, imported.stderr
    finally:
        _remove_project(tmp_dir)


def test_docker_builds_when_the_host_has_no_python27(monkeypatch, tmp_path: Path):
    calls: list[list[str]] = []

    def fake_run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "docker":
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 127, "", "not found")

    monkeypatch.setattr("accra_python2.pip_env.host_python27", lambda: None)
    monkeypatch.setattr(Pip, "_run", fake_run)
    source = tmp_path / "legacy.py"
    source.write_text("import six\n", encoding="utf-8")

    result = Python2(Config(cwd=tmp_path)).build()
    assert result.success, [error.message for error in result.errors]
    assert result.dockerfile.pre_dependencies_installation[0].startswith("RUN apt-get")
    assert any(command[0] == "docker" and "run" in command for command in calls)


def test_imports_of_the_projects_own_modules_are_not_dependencies(tmp_path):
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "_init_paths.py").write_text("import numpy\n")
    (tmp_path / "loader.py").write_text("x = 1\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "main.py").write_text(
        "import loader\nimport _init_paths\nfrom pkg import a\nimport requests\n"
    )

    dependencies = Adhoc(Config(cwd=tmp_path)).extract_dependencies()

    assert {d.name for d in dependencies} == {"numpy", "requests"}
