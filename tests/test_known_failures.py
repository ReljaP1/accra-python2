import subprocess
from pathlib import Path

from accra_language import AccraFailedDependencyInstallError, Config, Dependency

from accra_python2 import Pip
from accra_python2.known_failures import (
    KnownDependencyInstallError,
    classify,
    package_key,
)


def _pip_failing_with(tmp_path: Path, monkeypatch, stderr: str) -> Pip:
    pip = Pip(Config(cwd=tmp_path))
    monkeypatch.setattr(
        pip, "_run", lambda args: subprocess.CompletedProcess(args, 1, "", stderr)
    )
    return pip


def test_package_names_are_keyed_like_the_lists():
    assert package_key("Scikit_Learn>=0.2") == "scikit-learn"
    assert package_key("sklearn") == "scikit-learn"
    assert package_key("numpy[extra]==1.0") == "numpy"


def test_a_signature_of_a_listed_package_is_a_native_failure():
    assert classify("scipy", "ERROR: No lapack/blas resources found") == (
        "native",
        "no lapack/blas resources found",
    )


def test_a_native_build_failing_without_a_signature_is_a_native_failure():
    assert classify("numpy", "error: command errored out with exit status 1") == (
        "native",
        None,
    )


def test_a_high_risk_package_qualifies_on_any_native_output():
    assert classify("stochastic", "building with gfortran failed") == ("native", None)


def test_other_packages_and_other_failures_are_not_known():
    assert classify("requests", "gfortran not found") is None
    assert classify("scipy", "No matching distribution found for scipy") is None


def test_a_known_failure_is_a_failed_dependency_with_the_optional_attributes(
    tmp_path: Path, monkeypatch
):
    pip = _pip_failing_with(
        tmp_path,
        monkeypatch,
        "ERROR: Failed building wheel for scipy\nlapack not found",
    )

    result = pip._install_dependency(Dependency(name="scipy", version=""))

    error = result.errors[0]
    assert result.success is True
    assert isinstance(error, KnownDependencyInstallError)
    assert isinstance(error, AccraFailedDependencyInstallError)
    assert error.dependency.name == "scipy"
    assert error.known_failure == "native"
    assert error.signature == "lapack not found" or error.signature == (
        "failed building wheel for scipy"
    )
    assert "lapack not found" in (error.stderr or "")


def test_an_unknown_failure_stays_an_ordinary_failed_dependency(
    tmp_path: Path, monkeypatch
):
    pip = _pip_failing_with(
        tmp_path, monkeypatch, "ERROR: No matching distribution found for nothing"
    )

    result = pip._install_dependency(Dependency(name="nothing", version=""))

    error = result.errors[0]
    assert type(error) is AccraFailedDependencyInstallError
    assert not hasattr(error, "known_failure")


def test_the_failed_installs_output_is_kept_on_the_error(tmp_path: Path, monkeypatch):
    pip = _pip_failing_with(tmp_path, monkeypatch, "line one\nERROR: boom")

    result = pip._install_dependency(Dependency(name="nothing", version=""))

    assert "boom" in (result.errors[0].stderr or "")
