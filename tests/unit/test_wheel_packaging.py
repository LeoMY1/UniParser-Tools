"""Regression test for setuptools namespace-package discovery."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_repeated_wheel_builds_only_package_uniparser_tools(tmp_path: Path) -> None:
    wheels = []
    for build_number in range(2):
        wheel_dir = tmp_path / f"wheel-{build_number}"
        wheel_dir.mkdir()
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                str(REPO_ROOT),
                "--no-cache-dir",
                "--no-deps",
                "--no-build-isolation",
                "--wheel-dir",
                str(wheel_dir),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        built_wheels = list(wheel_dir.glob("*.whl"))
        assert len(built_wheels) == 1
        wheels.append(built_wheels[0])

    with zipfile.ZipFile(wheels[-1]) as wheel:
        unexpected = [
            name for name in wheel.namelist() if not name.startswith(("uniparser_tools/", "uniparser_tools-"))
        ]

    assert unexpected == []
