import re

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from .constants import LEGACY_PINS, PYTHON2_VERSION, STDLIB_ALIASES

# A vermin field that names a Python 2 minimum, optionally prefixed with ~.
_PY2_FIELD = re.compile(r"^~?2(?:\.\d+)*$")


def supported_python2_versions(vermin_stdout: str) -> set[str]:
    """Return {2.7} when vermin reports a Python 2 line, otherwise an empty set.

    A field that starts with ``!`` means that line is incompatible with Python 2.
    Python 3-only output must not select this plugin.
    """
    for line in vermin_stdout.splitlines():
        for field in line.strip().split(":"):
            token = field.strip()
            if not token or token.startswith("!"):
                continue
            if _PY2_FIELD.fullmatch(token):
                return {PYTHON2_VERSION}
    return set()


def python2_versions_for_requires(requires_python: str) -> set[str]:
    """Return {2.7} when a requires-python specifier allows CPython 2.7.

    An empty specifier does not exclude 2.7. A floor such as >=3.8 does.
    """
    spec = requires_python.strip()
    if not spec:
        return {PYTHON2_VERSION}
    if SpecifierSet(spec).contains(Version("2.7.18")):
        return {PYTHON2_VERSION}
    return set()


def install_spec(name: str, version: str) -> str | None:
    """Pip requirement for a manifest entry. Standard-library names are skipped."""
    key = name.strip().lower()
    if not key or key in STDLIB_ALIASES:
        return None
    pinned = LEGACY_PINS.get(key)
    if pinned:
        return pinned
    suffix = version.strip()
    cleaned = name.strip()
    if not suffix:
        return cleaned
    if suffix[0] in "<>=!~[":
        return f"{cleaned}{suffix}"
    return f"{cleaned} {suffix}"
