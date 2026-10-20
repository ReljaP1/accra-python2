import re
from pathlib import Path

from accra_language import AccraError, Config, Dependency, Manifest, ManifestSpec

from .utils import python2_versions_for_requires

_QUOTED = re.compile(r"'([^']+)'|\"([^\"]+)\"")
_REQUIRES = re.compile(r"(?:python_requires|requires_python)\s*=\s*['\"]([^'\"]+)['\"]")


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

        dependencies: set[Dependency] = set()
        in_install_requires = False
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            return None

        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith("install_requires"):
                if "[" in line:
                    in_install_requires = "]" not in line
                    dependencies.update(self._quoted_dependencies(line))
                continue

            if in_install_requires:
                if "]" in line:
                    in_install_requires = False
                match = re.match(r"['\"]([^'\"]+)['\"]", line)
                if match:
                    self._add_requirement(dependencies, match.group(1))

        return dependencies or None

    @classmethod
    def _quoted_dependencies(cls, line: str) -> set[Dependency]:
        dependencies: set[Dependency] = set()
        for left, right in _QUOTED.findall(line):
            cls._add_requirement(dependencies, left or right)
        return dependencies

    @staticmethod
    def _add_requirement(dependencies: set[Dependency], requirement: str) -> None:
        package = re.split(r"[<>=~!]", requirement, maxsplit=1)[0].strip()
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
