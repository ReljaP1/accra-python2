import re

from packaging.markers import Marker, default_environment
from packaging.requirements import Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

from .constants import LEGACY_PINS, PYTHON2_VERSION, STDLIB_ALIASES

_PY2_ENVIRONMENT = {
    "python_version": "2.7",
    "python_full_version": "2.7.18",
    "implementation_version": "2.7.18",
}

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
    A value that is not a specifier, such as an unformatted template, does not
    exclude 2.7 either.
    """
    spec = requires_python.strip()
    if not spec:
        return {PYTHON2_VERSION}
    try:
        parsed = SpecifierSet(spec)
    except InvalidSpecifier:
        return {PYTHON2_VERSION}
    if parsed.contains(Version("2.7.18")):
        return {PYTHON2_VERSION}
    return set()


def _nearby_versions(version: Version) -> list[Version]:
    parts = list(version.release)
    below = parts[:]
    below[-1] = max(below[-1] - 1, 0)
    return [
        version,
        Version(".".join(str(part) for part in below)),
        Version(".".join(str(part) for part in [*parts, 1])),
    ]


def legacy_pin_conflicts(name: str, specifier: str) -> bool:
    """True when a requested specifier cannot meet the Python 2.7 pin.

    ``numpy>=1.8`` still meets ``numpy<1.17``. ``numpy>=1.20`` does not.
    """
    pinned = LEGACY_PINS.get(name.strip().lower())
    text = specifier.strip()
    if not pinned or not text:
        return False
    user = SpecifierSet(text)
    legacy = Requirement(pinned).specifier
    candidates: list[Version] = []
    for spec in (*user, *legacy):
        candidates.extend(_nearby_versions(Version(spec.version)))
    return not any(
        user.contains(version) and legacy.contains(version) for version in candidates
    )


def marker_fits_python2(marker_text: str) -> bool:
    """Whether an environment marker is true on CPython 2.7."""
    environment = default_environment()
    environment.update(_PY2_ENVIRONMENT)
    return bool(Marker(marker_text).evaluate(environment))


def fits_python2(requirement: Requirement) -> bool:
    """Whether one requirement can be installed for CPython 2.7."""
    if requirement.marker is not None and not marker_fits_python2(
        str(requirement.marker)
    ):
        return False
    return not legacy_pin_conflicts(requirement.name, str(requirement.specifier))


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
