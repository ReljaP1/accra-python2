import re
import subprocess
import tempfile
from pathlib import Path

from accra_language import AccraError, Config, Dependency, Manifest, ManifestSpec

from .constants import VENV_DIR
from .utils import marker_fits_python2, python2_versions_for_requires

_QUOTED = re.compile(r"'([^']+)'|\"([^\"]+)\"")
_REQUIRES = re.compile(r"(?:python_requires|requires_python)\s*=\s*['\"]([^'\"]+)['\"]")
_INSTALL_REQUIRES = re.compile(r"install_requires\s*=\s*\[(.*?)\]", re.DOTALL)


class Setup_py(Manifest):
    def __init__(self, config: Config):
        spec = ManifestSpec(name="setup.py", version="", config=config)
        super().__init__(spec)

    def _path(self) -> Path | None:
        cwd = self.spec.config.cwd
        if cwd is None:
            return None
        return Path(cwd) / self.spec.name

    def detect(self) -> bool:
        path = self._path()
        return bool(path and path.is_file())

    def extract_dependencies(self) -> set[Dependency] | None:
        path = self._path()
        if path is None or not path.is_file():
            return None
        from_egg = self._dependencies_from_egg_info(path)
        if from_egg is not None:
            return from_egg or None
        return self._dependencies_from_text(path) or None

    def _dependencies_from_egg_info(self, path: Path) -> set[Dependency] | None:
        """Run setup.py when the 2.7 environment already exists.

        None means egg_info did not run, so the caller reads the file instead.
        """
        interpreter = path.parent / VENV_DIR / "bin" / "python"
        if not interpreter.is_file():
            return None
        config = self.spec.config
        with tempfile.TemporaryDirectory() as egg_base:
            completed = subprocess.run(
                [
                    str(interpreter),
                    path.name,
                    "egg_info",
                    "--egg-base",
                    egg_base,
                ],
                check=False,
                capture_output=True,
                text=True,
                cwd=path.parent,
                env=config.env,
                shell=config.shell,
                timeout=config.timeout,
            )
            if completed.returncode != 0:
                return None
            requires_files = list(Path(egg_base).glob("*.egg-info/requires.txt"))
            if not requires_files:
                return set()
            return self._dependencies_from_requires(requires_files[0])

    @classmethod
    def _dependencies_from_requires(cls, path: Path) -> set[Dependency]:
        dependencies: set[Dependency] = set()
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return dependencies
        include = True
        for raw_line in text.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip()
                if section.startswith(":"):
                    include = marker_fits_python2(section[1:].strip())
                else:
                    include = False
                continue
            if include:
                cls._add_requirement(dependencies, line)
        return dependencies

    def _dependencies_from_text(self, path: Path) -> set[Dependency]:
        dependencies: set[Dependency] = set()
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return dependencies
        for match in _INSTALL_REQUIRES.finditer(text):
            for left, right in _QUOTED.findall(match.group(1)):
                self._add_requirement(dependencies, left or right)
        return dependencies

    @staticmethod
    def _add_requirement(dependencies: set[Dependency], requirement: str) -> None:
        package = re.split(r"[<>=~!;\[]", requirement, maxsplit=1)[0].strip()
        if not package:
            return
        version = requirement[len(package) :].strip()
        dependencies.add(Dependency(name=package, version=version))

    def get_supported_language_versions(self) -> set[str] | AccraError:
        path = self._path()
        requires_python = ""
        if path is not None and path.is_file():
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                text = ""
            match = _REQUIRES.search(text)
            if match:
                requires_python = match.group(1)
        return python2_versions_for_requires(requires_python)
