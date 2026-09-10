"""Shared pytest fixtures and utilities for Bluefin Server OS test suite."""

from __future__ import annotations

import configparser
import os
from pathlib import Path
from typing import Any

import pytest
import yaml

DEFAULT_SERVER_PATH = Path("/home/jorge/src/server")


@pytest.fixture(scope="session")
def server_root() -> Path:
    """Return the resolved path to the Bluefin Server repository root."""
    env_path = os.environ.get("BLUEFIN_SERVER_ROOT")
    if env_path:
        candidate = Path(env_path).resolve()
        if candidate.is_dir():
            return candidate

    if DEFAULT_SERVER_PATH.is_dir():
        return DEFAULT_SERVER_PATH.resolve()

    adjacent = Path(__file__).resolve().parents[3] / "server"
    if adjacent.is_dir():
        return adjacent.resolve()

    pytest.skip(
        f"Bluefin Server repository not found. Set BLUEFIN_SERVER_ROOT or place at {DEFAULT_SERVER_PATH}"
    )


@pytest.fixture(scope="session")
def files_dir(server_root: Path) -> Path:
    """Return the files/ directory of the server repo."""
    path = server_root / "files"
    assert path.is_dir(), f"Expected files directory at {path}"
    return path


@pytest.fixture(scope="session")
def elements_dir(server_root: Path) -> Path:
    """Return the elements/ directory of the server repo."""
    path = server_root / "elements"
    assert path.is_dir(), f"Expected elements directory at {path}"
    return path


@pytest.fixture(scope="session")
def all_elements_text(elements_dir: Path) -> str:
    """Return concatenated content of all BuildStream element files."""
    return "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted(elements_dir.rglob("*.bst"))
    )


def load_systemd_conf(path: Path) -> configparser.ConfigParser:
    """Parse a systemd configuration file preserving case and comments."""
    parser = configparser.ConfigParser(strict=False)
    parser.optionxform = str
    parser.read_string(path.read_text(encoding="utf-8"))
    return parser


def load_yaml(path: Path) -> dict[str, Any]:
    """Parse a YAML file using safe_load."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"Expected dict from YAML file {path}"
    return data
