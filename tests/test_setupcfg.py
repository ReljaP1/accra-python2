import shutil
from pathlib import Path

from accra_language import Config, Dependency

from accra_python2 import Setup_cfg
from accra_python2.constants import PYTHON2_VERSION


def test_setupcfg():
    correct_dependencies: set[Dependency] = {
        Dependency(name="requests", version=">=2.28"),
        Dependency(name="numpy", version=">=1.8"),
        Dependency(name="click", version=">=8.1"),
    }

    project_dir = Path(__file__).resolve().parent / Path("fixtures/setup_cfg-project")
    tmp_dir = Path("/tmp/setup_cfg-project-py2")

    shutil.rmtree(tmp_dir, ignore_errors=True)
    shutil.copytree(project_dir, tmp_dir)

    try:
        manifest = Setup_cfg(Config(cwd=tmp_dir))
        assert manifest.detect()
        assert manifest.extract_dependencies() == correct_dependencies
        assert manifest.get_supported_language_versions() == {PYTHON2_VERSION}
    finally:
        shutil.rmtree(tmp_dir)


def test_setupcfg_rejects_python3_only(tmp_path: Path):
    setup_cfg = tmp_path / "setup.cfg"
    setup_cfg.write_text(
        "[options]\npython_requires = >=3.8\ninstall_requires =\n    rich\n",
        encoding="utf-8",
    )
    manifest = Setup_cfg(Config(cwd=tmp_path))
    assert manifest.detect()
    assert manifest.extract_dependencies() == {Dependency(name="rich", version="")}
    assert manifest.get_supported_language_versions() == set()
