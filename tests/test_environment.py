import subprocess
from pathlib import Path

from accra_language import (
    AccraBuildError,
    AccraError,
    AccraFailedDependencyInstallError,
    Config,
    Dependency,
)

from accra_python2 import Pip
from accra_python2.pip_env import python2_version_order


def test_failed_install_is_a_failed_dependency_not_a_failed_build(
    tmp_path: Path, monkeypatch
):
    pip = Pip(Config(cwd=tmp_path))
    monkeypatch.setattr(
        pip,
        "_run",
        lambda args: __import__("subprocess").CompletedProcess(
            args, 1, "", "ERROR: No matching distribution found for nothing"
        ),
    )

    result = pip._install_dependency(Dependency(name="nothing", version=""))

    assert result.success is True
    assert isinstance(result.errors[0], AccraFailedDependencyInstallError)
    assert result.errors[0].dependency.name == "nothing"


def test_run_environment_activates_the_venv(tmp_path: Path):
    env = Pip(Config(cwd=tmp_path)).run_environment({"PATH": "/usr/bin"})

    assert env["VIRTUAL_ENV"] == str(tmp_path.resolve() / ".venv")
    assert env["PATH"].startswith(str(tmp_path.resolve() / ".venv" / "bin"))


def test_version_order_puts_python_27_first(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("six\n", encoding="utf-8")
    pip = Pip(Config(cwd=tmp_path))

    assert python2_version_order({"2.6", "2.7", "3.0"}) == ["2.7", "3.0", "2.6"]
    assert python2_version_order({"3.0", "2.6"}) == ["3.0", "2.6"]
    assert pip.spec.version_order is python2_version_order
    assert pip.ranked_language_versions() == ["2.7"]
    assert pip.select_language_version() == "2.7"


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_project_names_of_a_script_collection(tmp_path: Path):
    for name in ("loader.py", "model.py", "setup.py", "conftest.py", "notes.txt"):
        _write(tmp_path / name)
    _write(tmp_path / "scripts" / "run.py")

    assert Pip(Config(cwd=tmp_path)).project_names() == {"loader", "model"}


def test_project_names_of_packages_and_src_layout(tmp_path: Path):
    _write(tmp_path / "pkg" / "__init__.py")
    _write(tmp_path / "src" / "inner" / "__init__.py")
    _write(tmp_path / "src" / "tool.py")

    names = Pip(Config(cwd=tmp_path)).project_names()

    assert names == {"pkg", "inner", "tool"}


def test_project_names_skip_listed_and_hidden_dirs(tmp_path: Path):
    for folder in (
        ".venv",
        "tests",
        "test",
        "docs",
        "doc",
        "examples",
        "build",
        "dist",
    ):
        _write(tmp_path / folder / "__init__.py")
    _write(tmp_path / ".hidden" / "__init__.py")
    _write(tmp_path / "real" / "__init__.py")

    assert Pip(Config(cwd=tmp_path)).project_names() == {"real"}


def test_project_names_include_the_setup_name(tmp_path: Path):
    _write(
        tmp_path / "setup.py", "from setuptools import setup\nsetup(name='my-dist')\n"
    )

    assert Pip(Config(cwd=tmp_path)).project_names() == {"my-dist"}

    (tmp_path / "setup.py").unlink()
    _write(tmp_path / "setup.cfg", "[metadata]\nname = cfg-dist\n")

    assert Pip(Config(cwd=tmp_path)).project_names() == {"cfg-dist"}


def test_project_names_ignore_unreadable_files(tmp_path: Path):
    _write(tmp_path / "setup.py", "\xff\xfe print 'py2' \x00 setup(")
    _write(tmp_path / "setup.cfg", "[metadata\nname")
    broken = tmp_path / "broken.py"
    broken.symlink_to(tmp_path / "missing.py")

    assert Pip(Config(cwd=tmp_path)).project_names() == set()
    assert Pip(Config(cwd=tmp_path / "absent")).project_names() == set()


def _lines(result) -> list[str]:
    return [str(i) for i in result.dockerfile.post_dependencies_installation]


def _fake_interpreter(tmp_path: Path) -> Path:
    return _write(tmp_path / ".venv" / "bin" / "python")


def _runs(pip, monkeypatch, imports=True, pip_ok=True):
    """Fakes every command: `pip install` succeeds or not, imports likewise."""
    calls = []

    def run(args, env=None, timeout=None):
        calls.append(args)
        ok = imports if args[-2:-1] == ["-c"] else pip_ok
        return subprocess.CompletedProcess(args, 0 if ok else 1, "", "ERROR: boom")

    monkeypatch.setattr(pip, "_run", run)
    return calls


def test_source_mode_puts_the_import_roots_on_pythonpath(tmp_path: Path):
    _write(tmp_path / "loader.py")
    pip = Pip(Config(cwd=tmp_path))

    result = pip.post_dependencies_installation()
    assert result.success and not result.errors
    assert _lines(result) == ["ENV PYTHONPATH=/project"]

    _write(tmp_path / "src" / "tool.py")
    assert _lines(pip.post_dependencies_installation()) == [
        "ENV PYTHONPATH=/project:/project/src"
    ]

    pip = Pip(Config(cwd=tmp_path, image_workdir="/work/"))
    assert _lines(pip.post_dependencies_installation()) == [
        "ENV PYTHONPATH=/work:/work/src"
    ]


def test_post_step_runs_an_editable_pip_install(tmp_path: Path, monkeypatch):
    _write(tmp_path / "setup.py")
    pip = Pip(Config(cwd=tmp_path))
    calls = _runs(pip, monkeypatch)

    result = pip.post_dependencies_installation()

    assert calls == [
        [".venv/bin/python", "setup.py", "build_ext", "--inplace"],
        [".venv/bin/pip", "install", "-e", str(tmp_path.resolve())],
    ]
    assert result.success is True and not result.errors
    assert _lines(result) == [
        "RUN .venv/bin/python setup.py build_ext --inplace",
        "RUN .venv/bin/pip install -e .",
    ]


def test_failed_install_without_a_package_is_not_an_error(tmp_path: Path, monkeypatch):
    # nothing to import, so the project counts as usable in source mode
    _write(tmp_path / "setup.py")
    pip = Pip(Config(cwd=tmp_path))
    _runs(pip, monkeypatch, pip_ok=False)

    result = pip.post_dependencies_installation()

    assert result.success is True and not result.errors
    assert _lines(result) == ["ENV PYTHONPATH=/project"]


def test_unusable_project_is_recorded_without_failing_the_build(
    tmp_path: Path, monkeypatch
):
    _fake_interpreter(tmp_path)
    _write(tmp_path / "setup.py")
    _write(tmp_path / "loader.py")
    pip = Pip(Config(cwd=tmp_path))
    _runs(pip, monkeypatch, imports=False, pip_ok=False)

    result = pip.post_dependencies_installation()

    assert result.success is True
    messages = [e.message for e in result.errors]
    assert any("boom" in m for m in messages)
    assert any("none of the project's packages imports: loader" in m for m in messages)
    assert all(isinstance(e, AccraError) for e in result.errors)


def test_project_usable_from_source_after_a_failed_install(tmp_path: Path, monkeypatch):
    _fake_interpreter(tmp_path)
    _write(tmp_path / "setup.py")
    _write(tmp_path / "loader.py")
    pip = Pip(Config(cwd=tmp_path))
    _runs(pip, monkeypatch, imports=True, pip_ok=False)

    result = pip.post_dependencies_installation()

    assert result.success is True and not result.errors


def test_import_check_puts_the_project_on_pythonpath(tmp_path: Path, monkeypatch):
    _fake_interpreter(tmp_path)
    _write(tmp_path / "src" / "tool.py")
    pip = Pip(Config(cwd=tmp_path, env={"PATH": "/usr/bin"}))
    seen = []

    def run(args, env=None, timeout=None):
        seen.append((args[-1], env["PYTHONPATH"], env["VIRTUAL_ENV"]))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(pip, "_run", run)

    pip.post_dependencies_installation()

    root = str(tmp_path.resolve())
    assert seen[0][0] == "import tool"
    assert seen[0][1] == f"{root}:{root}/src"
    assert seen[0][2] == str(tmp_path.resolve() / ".venv")


def test_import_check_that_cannot_run_is_not_an_error(tmp_path: Path, monkeypatch):
    _write(tmp_path / "loader.py")
    pip = Pip(Config(cwd=tmp_path))

    # no interpreter to ask
    assert not pip.post_dependencies_installation().errors

    _fake_interpreter(tmp_path)

    def timed_out(args, env=None, timeout=None):
        raise subprocess.TimeoutExpired(args, 1)

    monkeypatch.setattr(pip, "_run", timed_out)

    assert not pip.post_dependencies_installation().errors


def test_import_check_ignores_tests_and_docs(tmp_path: Path, monkeypatch):
    _fake_interpreter(tmp_path)
    _write(tmp_path / "docs" / "__init__.py")
    pip = Pip(Config(cwd=tmp_path))
    calls = _runs(pip, monkeypatch, imports=False)

    assert not pip.post_dependencies_installation().errors
    assert calls == []


def test_missing_project_directory_is_recorded(tmp_path: Path):
    result = Pip(Config()).post_dependencies_installation()

    assert result.success is True
    assert isinstance(result.errors[0], AccraBuildError)
