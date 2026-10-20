import re
from pathlib import Path

from accra_language import AccraError, Config, Dependency, Manifest, ManifestSpec

from .constants import PYTHON2_VERSION

_REQUIREMENT = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*)(?P<rest>(?:\[[^\]]*\])?.*)$"
)
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
    def _parse_requirements(
        req_file_path: Path, visited_files: set[Path]
    ) -> set[Dependency]:
        dependencies: set[Dependency] = set()
        req_file_path = req_file_path.resolve()
        if not req_file_path.is_file() or req_file_path in visited_files:
            return dependencies

        visited_files.add(req_file_path)
        text = req_file_path.read_text(encoding="utf-8", errors="ignore")
        for raw_line in text.splitlines():
            stripped = raw_line.split("#", 1)[0].strip()
            if not stripped:
                continue

            if stripped.startswith(("-r ", "--requirement ")):
                nested_file = stripped.split(maxsplit=1)[1].strip()
                nested_path = (req_file_path.parent / nested_file).resolve()
                dependencies.update(
                    Requirements_txt._parse_requirements(nested_path, visited_files)
                )
                continue

            if stripped.startswith(_SKIP_PREFIXES):
                continue

            match = _REQUIREMENT.match(stripped)
            if not match:
                continue
            name = match.group("name")
            rest = match.group("rest").strip()
            if name:
                dependencies.add(Dependency(name=name, version=rest))

        return dependencies

    def extract_dependencies(self) -> set[Dependency] | None:
        path = self._path()
        if path is None or not path.is_file():
            return None
        dependencies = Requirements_txt._parse_requirements(path, set())
        return dependencies or None

    def get_supported_language_versions(self) -> set[str] | AccraError:
        # An unversioned requirements file must not wipe the intersection
        # inside EnvironmentManager.select_language_version.
        return {PYTHON2_VERSION}
