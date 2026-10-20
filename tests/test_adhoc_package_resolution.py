import shutil
import subprocess
from pathlib import Path

import pytest
from accra_language import AccraResult, Config

from accra_python2 import Pip, Python2
from accra_python2.constants import VIRTUALENV_SPEC

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
        assert result.dockerfile.pre_dependencies_installation == [
            "RUN pyenv install --skip-existing 2.7",
            "RUN python -m ensurepip --upgrade",
            f"RUN python -m pip install {VIRTUALENV_SPEC}",
            'RUN python -m virtualenv -p "$(pyenv prefix 2.7)/bin/python" .venv',
            _BOOTSTRAP,
        ]
        assert result.dockerfile.dependencies_installation == [
            "RUN .venv/bin/pip install six --ignore-requires-python"
        ]
        assert result.dockerfile.post_dependencies_installation == []
    finally:
        shutil.rmtree(tmp_dir)


def test_pyenv_failure_stops_the_build(monkeypatch, tmp_path: Path):
    def fail_run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 1, "", "pyenv missing")

    monkeypatch.setattr(Pip, "_run", fail_run)
    source = tmp_path / "legacy.py"
    source.write_text("import six\n", encoding="utf-8")

    result = Python2(Config(cwd=tmp_path)).build()
    assert result.success is False
    assert result.errors
    assert result.dockerfile.pre_dependencies_installation == []


def _python27_available() -> bool:
    probe = subprocess.run(
        ["pyenv", "prefix", "2.7.18"],
        check=False,
        capture_output=True,
        text=True,
    )
    return probe.returncode == 0 and bool(probe.stdout.strip())


@pytest.mark.skipif(not _python27_available(), reason="pyenv has no CPython 2.7.18")
def test_real_python27_installs_six():
    project_dir = Path(__file__).resolve().parent / Path(
        "fixtures/adhoc-module-project"
    )
    tmp_dir = Path("/tmp/adhoc-module-project-py2-real")

    shutil.rmtree(tmp_dir, ignore_errors=True)
    shutil.copytree(project_dir, tmp_dir)

    try:
        result = Python2(Config(cwd=tmp_dir)).build()
        assert result.success, [error.message for error in result.errors]
        interpreter = tmp_dir / ".venv" / "bin" / "python"
        assert interpreter.is_file()
        imported = subprocess.run(
            [str(interpreter), "-c", "import six"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert imported.returncode == 0, imported.stderr
    finally:
        shutil.rmtree(tmp_dir)
