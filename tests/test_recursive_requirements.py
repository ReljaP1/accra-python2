import shutil
from pathlib import Path

from accra_language import Config, Dependency

from accra_python2 import Requirements_txt


def test_recursive_requirements():
    correct_dependencies: set[Dependency] = {
        Dependency(name="requests", version=">=2.31"),
        Dependency(name="packaging", version=">=23.0"),
        Dependency(name="pytest", version=">=8.0"),
    }

    project_dir = Path(__file__).resolve().parent / Path(
        "fixtures/recursive_requirements"
    )
    tmp_dir = Path("/tmp/recursive_requirements-py2")

    shutil.rmtree(tmp_dir, ignore_errors=True)
    shutil.copytree(project_dir, tmp_dir)

    try:
        manifest = Requirements_txt(Config(cwd=tmp_dir))
        assert manifest.detect()
        assert manifest.extract_dependencies() == correct_dependencies
    finally:
        shutil.rmtree(tmp_dir)
