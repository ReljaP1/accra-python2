import os
import re
import subprocess
import sys
from collections.abc import Mapping
from importlib.metadata import packages_distributions
from pathlib import Path
from typing import override

from accra_language import AccraError, Config, Dependency, Manifest, ManifestSpec

from .constants import STDLIB_ALIASES
from .utils import install_spec, supported_python2_versions

_ADHOC_PACKAGES: Mapping[str, str] = {
    "google.auth": "google-auth",
    "google.api_core": "google-api-core",
    "google.cloud.storage": "google-cloud-storage",
    "googleapiclient": "google-api-python-client",
    "pydantic_settings": "pydantic-settings",
    "yaml": "PyYAML",
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "MySQLdb": "mysqlclient",
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "dateutil": "python-dateutil",
    "jwt": "PyJWT",
    "attr": "attrs",
    "markdown_it": "markdown-it-py",
}

_MODULE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")

_EXCLUDED_SUBDIRS: set[str] = {
    "__pycache__",
    ".git",
    ".eggs",
    ".venv",
    "venv",
    "env",
    "build",
    "dist",
    "tests",
    "test",
    "docs",
    "doc",
    "examples",
    "example",
    "benchmarks",
    "benchmark",
}


class Adhoc(Manifest):
    def __init__(self, config: Config):
        spec = ManifestSpec(name="adhoc", version="", config=config)
        super().__init__(spec)

    def _python_files(self) -> list[Path]:
        cwd = self.spec.config.cwd or Path(".")
        files_found: list[Path] = []
        for root, dirs, files in os.walk(cwd):
            dirs[:] = [
                directory
                for directory in dirs
                if directory.lower() not in _EXCLUDED_SUBDIRS
                and not directory.lower().endswith((".egg-info", ".egg"))
            ]
            for file in files:
                if file.endswith(".py") and file != "setup.py":
                    files_found.append(Path(root) / file)
        return files_found

    @override
    def detect(self) -> bool:
        return bool(self._python_files())

    @staticmethod
    def imported_modules(code: str) -> set[str]:
        """Module names from ``import`` and ``from`` lines.

        A regex is used instead of ``ast`` so Python 2 statements such as
        ``print x`` and ``except Exception, e`` still yield their imports.
        """
        modules: set[str] = set()
        for line in code.splitlines():
            stripped = line.split("#", 1)[0].strip()
            if stripped.startswith("import "):
                clause = stripped[len("import ") :]
                for part in clause.split(","):
                    name = part.strip().split(" ")[0]
                    if _MODULE_NAME.fullmatch(name):
                        modules.add(name)
            elif stripped.startswith("from "):
                module = stripped[len("from ") :].split(" import ", 1)[0].strip()
                if _MODULE_NAME.fullmatch(module):
                    modules.add(module)
        return modules

    @staticmethod
    def resolve_package(
        module: str, installed: Mapping[str, list[str]] | None = None
    ) -> str | None:
        """Map a dotted import name to an installable package name."""
        top = module.split(".")[0]
        if top.lower() in STDLIB_ALIASES:
            return None
        if top in sys.stdlib_module_names:
            return None

        parts = module.split(".")
        for index in range(len(parts), 0, -1):
            key = ".".join(parts[:index])
            if key in _ADHOC_PACKAGES:
                return _ADHOC_PACKAGES[key]

        installed = installed if installed is not None else packages_distributions()
        if top in installed:
            return installed[top][0]
        return top

    def local_module_names(self) -> set[str]:
        """The names the project's own files and directories import as: a
        Python 2 script finds a module beside it, so `import loader` is the
        project's `loader.py`, not a package to install."""
        cwd = self.spec.config.cwd or Path(".")
        names: set[str] = set()
        for root, dirs, files in os.walk(cwd):
            dirs[:] = [d for d in dirs if d not in {".git", ".venv", "site-packages"}]
            names.update(d for d in dirs if _MODULE_NAME.fullmatch(d))
            names.update(f[:-3] for f in files if f.endswith(".py") and f != "setup.py")
        return names

    def _declared_manifest_present(self) -> bool:
        cwd = self.spec.config.cwd or Path(".")
        return any(
            (cwd / name).is_file()
            for name in ("setup.py", "setup.cfg", "requirements.txt")
        )

    @override
    def extract_dependencies(self) -> set[Dependency] | None:
        # A declared manifest is the dependency list. Scanning every import
        # also picks up prose, optional imports, and files egg_info unpacked.
        if self._declared_manifest_present():
            return None
        dependencies: set[Dependency] = set()
        local = self.local_module_names()
        for file_path in self._python_files():
            try:
                code = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for module in self.imported_modules(code):
                if module.split(".")[0] in local:
                    continue
                package = self.resolve_package(module)
                if not package or install_spec(package, "") is None:
                    continue
                dependencies.add(Dependency(name=package, version=""))

        return dependencies or None

    @override
    def get_supported_language_versions(self) -> set[str] | AccraError:
        cwd = self.spec.config.cwd or Path(".")
        config = self.spec.config
        result = subprocess.run(
            ["vermin", "-f", "parsable", str(cwd)],
            check=False,
            capture_output=True,
            text=True,
            cwd=config.cwd,
            env=config.env,
            shell=config.shell,
            timeout=config.timeout,
        )
        if result.returncode != 0:
            return set()
        return supported_python2_versions(result.stdout)
