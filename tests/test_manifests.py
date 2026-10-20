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


def test_adhoc_detects_only_project_sources(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("six==1.16.0\n", encoding="utf-8")
    (tmp_path / "setup.py").write_text(
        "from setuptools import setup\n", encoding="utf-8"
    )
    assert Adhoc(Config(cwd=tmp_path)).detect() is False
    (tmp_path / "legacy.py").write_text("import six\n", encoding="utf-8")
    assert Adhoc(Config(cwd=tmp_path)).detect() is True


def test_adhoc_defers_to_a_declared_manifest(tmp_path: Path):
    (tmp_path / "setup.py").write_text(
        "setup(install_requires=['six'])\n",
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text("import sklearn\n", encoding="utf-8")
    manifest = Adhoc(Config(cwd=tmp_path))
    assert manifest.detect() is True
    assert manifest.extract_dependencies() is None


def test_py2_import_resolution(tmp_path: Path):
    source = tmp_path / "legacy.py"
    source.write_text(
        "import sklearn, cpickle\n"
        "from urllib2 import urlopen\n"
        "print sklearn\n"
        "except Exception, error:\n"
        "    pass\n"
        'from "Table 5 Comparison of String Comparators"\n'
        "from :class:`~gensim.models.word2vec.Word2Vec`\n",
        encoding="utf-8",
    )

    (tmp_path / ".eggs" / "Cython").mkdir(parents=True)
    (tmp_path / ".eggs" / "Cython" / "hidden.py").write_text(
        "import CompilationOptions\n",
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text("import __main__\n", encoding="utf-8")

    dependencies = Adhoc(Config(cwd=tmp_path)).extract_dependencies()
    assert dependencies == {Dependency(name="scikit-learn", version="")}


def test_legacy_scientific_pin():
    assert install_spec("sklearn", "") == "scikit-learn<0.21"
    assert install_spec("numpy", ">=1.8") == "numpy<1.17"
    assert install_spec("urllib2", "") is None
    assert install_spec("six", "") == "six"
    assert install_spec("nltk", "") == "nltk<3.5"
    assert install_spec("pdfminer", "") == "pdfminer<20191010"
    assert install_spec("statsmodels", ">=0.8.0") == "statsmodels<0.11"
    assert install_spec("biopython", ">=1.62") == "biopython<1.77"
    assert install_spec("Cython", "") == "cython<3"


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


def test_requirements_skip_python3_markers_and_conflicting_pins(tmp_path: Path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        'six==1.16.0; python_version < "3"\n'
        'rich==13.0; python_version >= "3.8"\n'
        "numpy>=1.20\n",
        encoding="utf-8",
    )
    manifest = Requirements_txt(Config(cwd=tmp_path))
    assert manifest.extract_dependencies() == {
        Dependency(name="six", version="==1.16.0"),
    }
    assert manifest.get_supported_language_versions() == {PYTHON2_VERSION}

    requirements.write_text(
        'rich==13.0; python_version >= "3.8"\nnumpy>=1.20\n',
        encoding="utf-8",
    )
    assert manifest.extract_dependencies() is None
    assert manifest.get_supported_language_versions() == set()


def test_requires_python_keeps_only_27():
    assert python2_versions_for_requires("") == {PYTHON2_VERSION}
    assert python2_versions_for_requires(">=2.7") == {PYTHON2_VERSION}
    assert python2_versions_for_requires(">=3.8") == set()
    assert python2_versions_for_requires(">={}") == {PYTHON2_VERSION}
