import shutil
from pathlib import Path

from accra_language import Config, Dependency

from accra_python2 import Setup_py
from accra_python2.constants import PYTHON2_VERSION


def test_setuppy():
    correct_dependencies: set[Dependency] = {
        Dependency(name="requests", version=">=2.28"),
        Dependency(name="numpy", version=">=1.8"),
        Dependency(name="click", version=">=8.1"),
    }

    project_dir = Path(__file__).resolve().parent / Path("fixtures/setup_py-project")
    tmp_dir = Path("/tmp/setup_py-project-py2")

    shutil.rmtree(tmp_dir, ignore_errors=True)
    shutil.copytree(project_dir, tmp_dir)

    try:
        manifest = Setup_py(Config(cwd=tmp_dir))
        assert manifest.detect()
        assert manifest.extract_dependencies() == correct_dependencies
        assert manifest.get_supported_language_versions() == {PYTHON2_VERSION}
    finally:
        shutil.rmtree(tmp_dir)


def test_setuppy_keeps_python2_marker_requirements(tmp_path: Path):
    requires = tmp_path / "requires.txt"
    requires.write_text(
        'six\n\n[:python_version < "3.4"]\nsingledispatch\n\n[all]\nmatplotlib\n',
        encoding="utf-8",
    )
    dependencies = Setup_py._dependencies_from_requires(requires)
    assert dependencies == {
        Dependency(name="six", version=""),
        Dependency(name="singledispatch", version=""),
    }


def test_setuppy_reads_a_one_line_install_requires(tmp_path: Path):
    setup_py = tmp_path / "setup.py"
    setup_py.write_text(
        "from setuptools import setup\n"
        "setup(name='sample', install_requires=['six==1.16.0'])\n",
        encoding="utf-8",
    )
    manifest = Setup_py(Config(cwd=tmp_path))
    assert manifest.extract_dependencies() == {
        Dependency(name="six", version="==1.16.0"),
    }


def test_setuppy_rejects_python3_only(tmp_path: Path):
    setup_py = tmp_path / "setup.py"
    setup_py.write_text(
        'from setuptools import setup\nsetup(python_requires=">=3.8")\n',
        encoding="utf-8",
    )
    manifest = Setup_py(Config(cwd=tmp_path))
    assert manifest.detect()
    assert manifest.get_supported_language_versions() == set()
