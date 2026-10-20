from pathlib import Path

from accra_language import AccraError, Config, Dependency, Manifest, ManifestSpec
from packaging.requirements import InvalidRequirement, Requirement

from .constants import PYTHON2_VERSION
from .utils import fits_python2

_SKIP_PREFIXES = ("-e", "--editable", "-c", "-f", "--")


class Requirements_txt(Manifest):
    def __init__(self, config: Config):
        spec = ManifestSpec(name="requirements.txt", version="", config=config)
        super().__init__(spec)

    def _path(self) -> Path | None:
        cwd = self.spec.config.cwd
        if cwd is None:
            return None
        return Path(cwd) / self.spec.name

    def detect(self) -> bool:
        path = self._path()
        return bool(path and path.is_file())

    @staticmethod
    def _requirement_lines(req_file_path: Path, visited_files: set[Path]) -> list[str]:
        lines: list[str] = []
        req_file_path = req_file_path.resolve()
        if not req_file_path.is_file() or req_file_path in visited_files:
            return lines

        visited_files.add(req_file_path)
        text = req_file_path.read_text(encoding="utf-8", errors="ignore")
        for raw_line in text.splitlines():
            stripped = raw_line.split("#", 1)[0].strip()
            if not stripped:
                continue

            if stripped.startswith(("-r ", "--requirement ")):
                nested_file = stripped.split(maxsplit=1)[1].strip()
                nested_path = (req_file_path.parent / nested_file).resolve()
                lines.extend(
                    Requirements_txt._requirement_lines(nested_path, visited_files)
                )
                continue

            if stripped.startswith(_SKIP_PREFIXES):
                continue
            lines.append(stripped)

        return lines

    @staticmethod
    def _dependency_for_python2(line: str) -> Dependency | None:
        try:
            requirement = Requirement(line)
        except InvalidRequirement:
            return None
        if not fits_python2(requirement):
            return None
        extras = ""
        if requirement.extras:
            extras = "[" + ",".join(sorted(requirement.extras)) + "]"
        return Dependency(
            name=requirement.name,
            version=f"{extras}{requirement.specifier}",
        )

    def _lines(self) -> list[str]:
        path = self._path()
        if path is None or not path.is_file():
            return []
        return self._requirement_lines(path, set())

    def extract_dependencies(self) -> set[Dependency] | None:
        dependencies = {
            dependency
            for line in self._lines()
            if (dependency := self._dependency_for_python2(line)) is not None
        }
        return dependencies or None

    def get_supported_language_versions(self) -> set[str] | AccraError:
        lines = self._lines()
        if not lines:
            return {PYTHON2_VERSION}
        parsed = False
        for line in lines:
            try:
                requirement = Requirement(line)
            except InvalidRequirement:
                continue
            parsed = True
            if fits_python2(requirement):
                return {PYTHON2_VERSION}
        if not parsed:
            return {PYTHON2_VERSION}
        return set()
