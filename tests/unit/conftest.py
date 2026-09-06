"""Shared pytest isolation for unit tests that stub imported modules."""

import sys

import pytest


@pytest.fixture(autouse=True)
def restore_sys_modules():
    """Prevent per-test import stubs from leaking into later tests."""
    snapshot = sys.modules.copy()
    yield
    sys.modules.clear()
    sys.modules.update(snapshot)
