"""Tests for the apiary-sdk transitional stub distribution.

Verifies that the backward-compat ``apiary-sdk`` distribution name resolves
correctly by depending on ``superpos-sdk``.
"""

import pathlib
import subprocess
import sys

import pytest

COMPAT_DIR = pathlib.Path(__file__).resolve().parents[2] / "python-compat"


class TestApiaryCompatDistribution:
    """Verify the apiary-sdk stub distribution is correctly structured."""

    def test_compat_pyproject_exists(self):
        assert (COMPAT_DIR / "pyproject.toml").is_file()

    def test_compat_declares_apiary_sdk_name(self):
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            pytest.skip("tomllib requires Python 3.11+")

        with open(COMPAT_DIR / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)

        assert data["project"]["name"] == "apiary-sdk"

    def test_compat_depends_on_superpos_sdk(self):
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            pytest.skip("tomllib requires Python 3.11+")

        with open(COMPAT_DIR / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)

        deps = data["project"]["dependencies"]
        assert any("superpos-sdk" in d for d in deps)

    def test_compat_package_builds(self):
        """Verify the stub package can be built."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--dry-run",
                "--no-deps",
                "--break-system-packages",
                str(COMPAT_DIR),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Build failed: {result.stderr}"

    def test_pip_resolves_apiary_sdk_from_local(self):
        """Verify pip can resolve apiary-sdk from the local compat package."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--dry-run",
                "--no-deps",
                "--break-system-packages",
                f"apiary-sdk @ file://{COMPAT_DIR}",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"pip resolve failed: {result.stderr}"
