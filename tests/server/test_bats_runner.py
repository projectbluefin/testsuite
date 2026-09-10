"""Pytest execution wrapper for BATS test suites in tests/server/."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def test_server_bats_contracts(server_root: Path) -> None:
    """Execute BATS contracts for Bluefin Server if bats CLI is present."""
    bats_bin = shutil.which("bats")
    if not bats_bin:
        pytest.skip("bats binary not found in PATH")

    bats_file = Path(__file__).parent / "test_server_contracts.bats"
    assert bats_file.is_file(), f"Missing BATS test file at {bats_file}"

    env = dict(os.environ)
    env["BLUEFIN_SERVER_ROOT"] = str(server_root)

    res = subprocess.run(
        [bats_bin, str(bats_file)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert res.returncode == 0, (
        f"BATS tests in {bats_file.name} failed with code {res.returncode}:\n"
        f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )
