import shutil
import subprocess
from pathlib import Path

import pytest
from accra_language import Config

from accra_python2 import Pip, Python2
from accra_python2.constants import PYTHON27_IMAGE


def _command_ok(args: list[str]) -> bool:
    try:
        probe = subprocess.run(args, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        return False
    return probe.returncode == 0


def _host_python27() -> bool:
    if shutil.which("python2.7"):
        return True
    return _command_ok(["pyenv", "prefix", "2.7.18"]) or _command_ok(
        ["pyenv", "prefix", "2.7"]
    )


pytestmark = pytest.mark.skipif(
    not _host_python27(),
    reason="this machine has no CPython 2.7 interpreter",
)


def _build(tmp_path: Path):
    result = Python2(Config(cwd=tmp_path)).build()
    interpreter = tmp_path / ".venv" / "bin" / "python"
    return result, interpreter


def _imports(interpreter: Path, statement: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(interpreter), "-c", statement],
        check=False,
        capture_output=True,
        text=True,
    )


def _dockerfile_text(result) -> str:
    lines = (
        result.dockerfile.pre_dependencies_installation
        + result.dockerfile.dependencies_installation
        + result.dockerfile.post_dependencies_installation
    )
    return "\n".join(lines)


def test_requirements_installs_six_and_skips_stdlib(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text(
        "six==1.16.0\nurllib2\n",
        encoding="utf-8",
    )

    result, interpreter = _build(tmp_path)
    assert result.success, [error.message for error in result.errors]
    imported = _imports(interpreter, "import six")
    assert imported.returncode == 0, imported.stderr
    assert "urllib2" not in _dockerfile_text(result)
    shown = subprocess.run(
        [str(tmp_path / ".venv" / "bin" / "pip"), "show", "urllib2"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert shown.returncode != 0


def test_setup_py_installs_six(tmp_path: Path):
    (tmp_path / "install-requires.txt").write_text("six==1.16.0\n", encoding="utf-8")
    (tmp_path / "setup.py").write_text(
        "from setuptools import setup\n"
        "setup(name='sample', python_requires='>=2.7', "
        "install_requires=open('install-requires.txt').read().splitlines())\n",
        encoding="utf-8",
    )

    result, interpreter = _build(tmp_path)
    assert result.success, [error.message for error in result.errors]
    imported = _imports(interpreter, "import six")
    assert imported.returncode == 0, imported.stderr


def test_setup_cfg_installs_six(tmp_path: Path):
    (tmp_path / "app.py").write_text('print("ok")\n', encoding="utf-8")
    (tmp_path / "setup.cfg").write_text(
        "[options]\npython_requires = >=2.7\ninstall_requires =\n    six==1.16.0\n",
        encoding="utf-8",
    )

    result, interpreter = _build(tmp_path)
    assert result.success, [error.message for error in result.errors]
    imported = _imports(interpreter, "import six")
    assert imported.returncode == 0, imported.stderr


def test_python3_only_setup_is_not_selected(tmp_path: Path):
    (tmp_path / "setup.py").write_text(
        "from setuptools import setup\n"
        "setup(name='sample', python_requires='>=3.8', install_requires=['six'])\n",
        encoding="utf-8",
    )

    result, interpreter = _build(tmp_path)
    assert result.success is False
    assert result.errors
    assert not interpreter.is_file()


def test_numpy_is_pinned_and_installed(tmp_path: Path):
    (tmp_path / "app.py").write_text("import numpy\n", encoding="utf-8")

    result, interpreter = _build(tmp_path)
    assert result.success, [error.message for error in result.errors]
    assert "numpy<1.17" in _dockerfile_text(result)
    imported = _imports(interpreter, "import numpy")
    assert imported.returncode == 0, imported.stderr


def test_failed_package_stops_before_the_next_one(tmp_path: Path):
    (tmp_path / "app.py").write_text(
        "import aaaa_missing_dist_zz\nimport six\n",
        encoding="utf-8",
    )

    result, interpreter = _build(tmp_path)
    assert result.success is False
    assert any("aaaa_missing_dist_zz" in error.message for error in result.errors)
    assert "six" not in _dockerfile_text(result)
    assert interpreter.is_file()
    imported = _imports(interpreter, "import six")
    assert imported.returncode != 0


def test_docker_installs_six_inside_the_image(monkeypatch, tmp_path: Path):
    if not _command_ok(["docker", "info"]):
        pytest.skip("Docker daemon is not running")

    monkeypatch.setattr(Pip, "_find_interpreter", lambda self: None)
    (tmp_path / "app.py").write_text("import six\n", encoding="utf-8")

    result = Python2(Config(cwd=tmp_path)).build()
    assert result.success, [error.message for error in result.errors]
    imported = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{tmp_path.resolve()}:/project",
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
    assert imported.returncode == 0, imported.stderr
