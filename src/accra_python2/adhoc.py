import os
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
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "dateutil": "python-dateutil",
    "jwt": "PyJWT",
    "attr": "attrs",
    "markdown_it": "markdown-it-py",
}

_EXCLUDED_SUBDIRS: set[str] = {
    "__pycache__",
    ".git",
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

    @override
    def detect(self) -> bool:
        return True

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
                    if name:
                        modules.add(name)
            elif stripped.startswith("from "):
                module = stripped[len("from ") :].split(" import ", 1)[0].strip()
                if module and not module.startswith("."):
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

    @override
    def extract_dependencies(self) -> set[Dependency] | None:
        dependencies: set[Dependency] = set()
        cwd = self.spec.config.cwd or Path(".")

        for root, dirs, files in os.walk(cwd):
            dirs[:] = [d for d in dirs if d.lower() not in _EXCLUDED_SUBDIRS]
            for file in files:
                if not file.endswith(".py"):
                    continue
                file_path = Path(root) / file
                try:
                    code = file_path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for module in self.imported_modules(code):
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
