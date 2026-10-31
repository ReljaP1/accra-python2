"""Python 2 installs that are known to fail, and say so.

Some packages cannot be installed on Python 2.7 without a native toolchain the
host may lack (numpy, scipy and the scientific stack that needs BLAS/LAPACK or a
Fortran compiler). A caller that is told a failed install is one of these, not
just "failed", can report it as a known limitation instead of spending a repair
on it. The plugin says so with two optional attributes on the error it already
returns for a failed dependency (`KnownDependencyInstallError`), so the
accra-language contract is unchanged and a caller that ignores them sees an
ordinary `AccraFailedDependencyInstallError`.

`known_failure` is `"native"`: a known native-build failure of a package of the
lists below. `signature` is the text of the output that identified it, when one
did.
"""

from __future__ import annotations

import re

from accra_language import AccraFailedDependencyInstallError

# Packages whose Python 2.7 install is a native build (main's legacy native
# scientific list, with the 2.7 pins of `constants.LEGACY_PINS` behind them).
LEGACY_NATIVE_PACKAGES = frozenset(
    {
        "numpy",
        "scipy",
        "pandas",
        "matplotlib",
        "scikit-learn",
        "h5py",
        "numba",
        "llvmlite",
    }
)

# Packages that fail on 2.7 with any native-build output (main's high-risk list).
HIGH_RISK_PACKAGES = frozenset({"scipy", "numpy", "stochastic", "scikit-learn"})

# Output that names why a package could not be built, by package (main's
# known-failure signatures); matched in lower case.
SIGNATURES: dict[str, tuple[str, ...]] = {
    "scipy": (
        "no lapack/blas resources found",
        "lapack not found",
        "blas not found",
        "openblas not found",
        "atlas not found",
        "numpy.distutils.system_info.notfounderror",
        "library dfftpack has fortran sources",
        "failed building wheel for scipy",
    ),
    "numpy": ("failed building wheel for numpy", "fatal error: python.h"),
    "h5py": ("hdf5",),
    "llvmlite": ("llvm-config",),
    "numba": ("llvmlite",),
}

# Output that shows a native build failing, whichever package it was.
NATIVE_BUILD_INDICATORS = (
    "failed building wheel",
    "could not build wheels",
    "library dfftpack has fortran sources",
    "error: library",
    "atlas",
    "lapack",
    "blas",
    "gfortran",
    "fortran",
    "openblas",
    "numpy.distutils",
    "setup.py clean is not supported",
    "fatal error: python.h",
    "command errored out with exit status 1",
)

# The package names the lists use: lower case, `_` and `.` as `-`, and the
# `sklearn` alias of scikit-learn.
_ALIASES = {"sklearn": "scikit-learn"}


def package_key(name: str) -> str:
    """A package name as the lists key it."""
    base = re.split(r"[\[<>=!~;@\s(]", str(name).strip(), maxsplit=1)[0]
    key = re.sub(r"[-_.]+", "-", base).lower()
    return _ALIASES.get(key, key)


def classify(name: str, output: str) -> tuple[str, str | None] | None:
    """`("native", signature)` when *output* of a failed install of *name* is a
    known native-build failure, else None. A package of the legacy native list
    or the high-risk list qualifies when the output names its signature or shows
    a native build failing."""
    package = package_key(name)
    if package not in LEGACY_NATIVE_PACKAGES and package not in HIGH_RISK_PACKAGES:
        return None
    lowered = str(output or "").lower()
    signature = next((s for s in SIGNATURES.get(package, ()) if s in lowered), None)
    if signature or any(i in lowered for i in NATIVE_BUILD_INDICATORS):
        return "native", signature
    return None


class KnownDependencyInstallError(AccraFailedDependencyInstallError):
    """A failed dependency install that is a known failure (see the module)."""

    known_failure: str | None = None
    signature: str | None = None
