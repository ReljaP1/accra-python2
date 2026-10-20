import json
import os
import subprocess
from pathlib import Path

import pytest
from accra_language import Config

from accra_python2 import Python2

PAPERS = Path(os.environ.get("PYTHON2_PAPERS", "/tmp/papers"))
CASES = json.loads(
    (Path(__file__).with_name("papers.json")).read_text(encoding="utf-8")
)


def test_article_dataset_covers_at_least_fifty_papers():
    assert len(CASES) >= 50


def _papers_present() -> bool:
    return all((PAPERS / case["name"]).is_dir() for case in CASES)


def _import_name(statement: str) -> str:
    imported = statement.split(";", 1)[0].strip().split()
    return imported[1].split(".")[0]


def _pythonpath(project_dir: Path, statement: str) -> str:
    module = _import_name(statement)
    paths = [str(project_dir)]
    for candidate in project_dir.rglob(module):
        if (
            candidate.is_dir()
            and (candidate / "__init__.py").is_file()
            and ".venv" not in candidate.parts
        ):
            paths.insert(0, str(candidate.parent))
            break
    return os.pathsep.join(dict.fromkeys(paths))


@pytest.mark.skipif(
    not _papers_present(),
    reason="Python 2 article checkouts are not in PYTHON2_PAPERS",
)
@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_article_source_builds_with_the_plugin(case: dict):
    root = PAPERS / case["name"]
    source = (root / case["source"]).read_text(encoding="utf-8", errors="ignore")
    assert case["syntax"] in source
    for project in case["projects"]:
        project_dir = root / project
        result = Python2(Config(cwd=project_dir)).build()
        messages = [error.message for error in result.errors]
        assert result.success is True, messages
        interpreter = project_dir / ".venv" / "bin" / "python"
        version = subprocess.run(
            [str(interpreter), "-c", "import sys; print(sys.version)"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert version.returncode == 0, version.stderr
        assert version.stdout.startswith("2.7"), version.stdout
        env = dict(os.environ)
        env["PYTHONPATH"] = _pythonpath(project_dir, case["statement"])
        imported = subprocess.run(
            [str(interpreter), "-c", case["statement"]],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            cwd=project_dir,
        )
        assert imported.returncode == 0, imported.stderr
        print(case["article"])
        print(imported.stdout.strip())
