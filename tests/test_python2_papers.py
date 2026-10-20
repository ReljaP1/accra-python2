import os
import subprocess
from pathlib import Path

import pytest

PAPERS = Path(os.environ.get("PYTHON2_PAPERS", "/tmp/papers"))

# Articles whose released source is Python 2, checked out on the test machine.
CASES = (
    {
        "name": "nltk",
        "article": "Loper and Bird, NLTK: The Natural Language Toolkit, ACL 2004",
        "source": Path("nltk/data.py"),
        "syntax": "import cPickle as pickle",
        "statement": "import nltk; print(nltk.__version__)",
    },
    {
        "name": "gensim",
        "article": (
            "Rehurek and Sojka, Software Framework for Topic Modelling "
            "with Large Corpora, LREC 2010"
        ),
        "source": Path("gensim/downloader.py"),
        "syntax": "from urllib2 import urlopen",
        "statement": "import gensim; print(gensim.__version__)",
    },
    {
        "name": "pattern",
        "article": "De Smedt and Daelemans, Pattern for Python, JMLR 2012",
        "source": Path("pattern/web/__init__.py"),
        "syntax": "from urllib2 import urlopen",
        "statement": "import pattern; print(pattern.__version__)",
    },
)


def _papers_present() -> bool:
    return all((PAPERS / case["name"]).is_dir() for case in CASES)


pytestmark = pytest.mark.skipif(
    not _papers_present(),
    reason="Python 2 article checkouts are not in PYTHON2_PAPERS",
)


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_article_source_is_python2_and_imports_on_cpython27(case):
    root = PAPERS / case["name"]
    interpreter = root / ".venv" / "bin" / "python"
    assert interpreter.is_file(), case["article"]

    version = subprocess.run(
        [str(interpreter), "-c", "import sys; print(sys.version)"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert version.returncode == 0, version.stderr
    assert version.stdout.startswith("2.7"), version.stdout

    source = (root / case["source"]).read_text(encoding="utf-8", errors="ignore")
    assert case["syntax"] in source

    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    imported = subprocess.run(
        [str(interpreter), "-c", case["statement"]],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert imported.returncode == 0, imported.stderr
    print(case["article"])
    print(version.stdout.strip())
    print(imported.stdout.strip())
