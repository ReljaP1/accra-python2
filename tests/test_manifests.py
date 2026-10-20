from pathlib import Path

from accra_language import Config, Dependency

from accra_python2 import Python2
from accra_python2.adhoc import Adhoc
from accra_python2.constants import PYTHON2_VERSION
from accra_python2.requirements_txt import Requirements_txt
from accra_python2.utils import (
    install_spec,
    python2_versions_for_requires,
    supported_python2_versions,
)


def test_py2_import_resolution(tmp_path: Path):
    source = tmp_path / "legacy.py"
    source.write_text(
        "import sklearn, cpickle\n"
        "from urllib2 import urlopen\n"
        "print sklearn\n"
        "except Exception, error:\n"
        "    pass\n",
        encoding="utf-8",
    )

    dependencies = Adhoc(Config(cwd=tmp_path)).extract_dependencies()
    assert dependencies == {Dependency(name="scikit-learn", version="")}


def test_legacy_scientific_pin():
    assert install_spec("sklearn", "") == "scikit-learn<0.21"
    assert install_spec("numpy", ">=1.8") == "numpy<1.17"
    assert install_spec("urllib2", "") is None
    assert install_spec("six", "") == "six"


def test_vermin_python2_detection():
    assert supported_python2_versions("legacy.py:2.7:!3\n") == {PYTHON2_VERSION}
    assert supported_python2_versions(":::2.0:3.0:\n") == {PYTHON2_VERSION}
    assert supported_python2_versions("modern.py:!2:3.8\n") == set()
    assert supported_python2_versions("") == set()


def test_detect_python2_fixture():
    project_dir = Path(__file__).resolve().parent / "fixtures/adhoc-module-project"
    assert Python2(Config(cwd=project_dir)).detect() is True


def test_requirements_txt(tmp_path: Path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "# comment\nsix==1.16.0\n-e .\n-r other.txt\nnumpy>=1.8\n",
        encoding="utf-8",
    )
    manifest = Requirements_txt(Config(cwd=tmp_path))
    assert manifest.detect()
    assert manifest.extract_dependencies() == {
        Dependency(name="six", version="==1.16.0"),
        Dependency(name="numpy", version=">=1.8"),
    }
    assert manifest.get_supported_language_versions() == {PYTHON2_VERSION}


def test_requires_python_keeps_only_27():
    assert python2_versions_for_requires("") == {PYTHON2_VERSION}
    assert python2_versions_for_requires(">=2.7") == {PYTHON2_VERSION}
    assert python2_versions_for_requires(">=3.8") == set()
