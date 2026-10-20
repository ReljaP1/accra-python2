import configparser
import re
from pathlib import Path

from accra_language import AccraError, Config, Dependency, Manifest, ManifestSpec

from .utils import python2_versions_for_requires


class Setup_cfg(Manifest):
    def __init__(self, config: Config):
        spec = ManifestSpec(name="setup.cfg", version="", config=config)
        super().__init__(spec)
        self.install_requires: str | None = None
        self.python_requires: str | None = None

    def _path(self) -> Path | None:
        cwd = self.spec.config.cwd
        if cwd is None:
            return None
        return Path(cwd) / self.spec.name

    def detect(self) -> bool:
        path = self._path()
        if path is None or not path.is_file():
            return False
        parser = configparser.ConfigParser()
        try:
            parser.read(path)
        except (OSError, configparser.Error):
            return False

        if parser.has_section("options") and parser.has_option(
            "options", "install_requires"
        ):
            self.install_requires = parser.get("options", "install_requires")
        if parser.has_section("options") and parser.has_option(
            "options", "python_requires"
        ):
            self.python_requires = parser.get("options", "python_requires")
        return True

    def extract_dependencies(self) -> set[Dependency] | None:
        if not self.install_requires:
            return None

        dependencies: set[Dependency] = set()
        for raw_line in self.install_requires.splitlines():
            requirement = raw_line.split("#", 1)[0].strip()
            if not requirement:
                continue
            package = re.split(r"[<>=~!]", requirement, maxsplit=1)[0].strip()
            if not package:
                continue
            version = requirement[len(package) :].strip()
            dependencies.add(Dependency(name=package, version=version))
        return dependencies or None

    def get_supported_language_versions(self) -> set[str] | AccraError:
        return python2_versions_for_requires(self.python_requires or "")
