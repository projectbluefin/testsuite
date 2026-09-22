"""Regression tests for kde-smoke environment helper imports.

These tests assert that the kde-smoke environment module imports the REAL
shared helper API without any try/except swallow.  If a helper is renamed
or removed, these tests FAIL loudly — preventing a silent CI pass where
zero scenarios actually run.
"""

import importlib

import pytest


# ---------------------------------------------------------------------------
# 1. The kde-smoke environment imports helpers at module scope (no swallow)
# ---------------------------------------------------------------------------


def test_environment_imports_successfully():
    """The kde-smoke environment module must import without error."""
    mod = importlib.import_module("tests.kde-smoke.features.environment")
    assert mod is not None


# ---------------------------------------------------------------------------
# 2. Assert specific names exist and are callable on the shared modules
# ---------------------------------------------------------------------------


class TestKdePreconditionsAPI:
    """The shared kde_preconditions module must expose the real public API."""

    @pytest.fixture(autouse=True)
    def _load_module(self):
        self.mod = importlib.import_module("tests.shared.kde_preconditions")

    def test_is_kde_session_exists_and_callable(self):
        assert hasattr(self.mod, "is_kde_session")
        assert callable(self.mod.is_kde_session)

    def test_apply_kde_session_preconditions_exists_and_callable(self):
        assert hasattr(self.mod, "apply_kde_session_preconditions")
        assert callable(self.mod.apply_kde_session_preconditions)

    def test_has_sddm_exists_and_callable(self):
        assert hasattr(self.mod, "has_sddm")
        assert callable(self.mod.has_sddm)

    def test_wait_for_plasma_session_exists_and_callable(self):
        assert hasattr(self.mod, "wait_for_plasma_session")
        assert callable(self.mod.wait_for_plasma_session)

    # NOTE: The D1 defect was that environment.py imported is_kde_image and
    # ensure_kde_session when they didn't exist, then swallowed the ImportError.
    # The invariant is therefore "no guarded/swallowed imports; every imported
    # name must exist in the shared module" — NOT a ban on any particular name.
    # PR #654 added is_kde_image as a real shared function, and kde-smoke now
    # legitimately imports it instead of keeping a private duplicate.


class TestKdeWebdriverAPI:
    """The shared kde_webdriver module must expose the real public API."""

    @pytest.fixture(autouse=True)
    def _load_module(self):
        self.mod = importlib.import_module("tests.shared.kde_webdriver")

    def test_new_session_exists_and_callable(self):
        assert hasattr(self.mod, "new_session")
        assert callable(self.mod.new_session)

    def test_quit_session_exists_and_callable(self):
        assert hasattr(self.mod, "quit_session")
        assert callable(self.mod.quit_session)

    def test_find_exists_and_callable(self):
        assert hasattr(self.mod, "find")
        assert callable(self.mod.find)

    def test_find_all_exists_and_callable(self):
        assert hasattr(self.mod, "find_all")
        assert callable(self.mod.find_all)

    def test_wait_for_exists_and_callable(self):
        assert hasattr(self.mod, "wait_for")
        assert callable(self.mod.wait_for)

    def test_retry_atspi_action_exists_and_callable(self):
        assert hasattr(self.mod, "retry_atspi_action")
        assert callable(self.mod.retry_atspi_action)

    def test_save_screenshot_exists_and_callable(self):
        assert hasattr(self.mod, "save_screenshot")
        assert callable(self.mod.save_screenshot)

    def test_no_start_driver_function(self):
        """start_driver was a phantom name that never existed; ensure it stays gone."""
        assert not hasattr(self.mod, "start_driver")

    def test_no_press_key_function(self):
        """press_key never existed — the dead code branch has been removed."""
        assert not hasattr(self.mod, "press_key")


class TestKdeShellStepsAPI:
    """The shared kde_shell_steps module must expose wait_until."""

    @pytest.fixture(autouse=True)
    def _load_module(self):
        self.mod = importlib.import_module("tests.shared.kde_shell_steps")

    def test_wait_until_exists_and_callable(self):
        assert hasattr(self.mod, "wait_until")
        assert callable(self.mod.wait_until)


# ---------------------------------------------------------------------------
# 3. The environment module references the CORRECT names from shared modules
# ---------------------------------------------------------------------------


def test_environment_uses_correct_precondition_names():
    """environment.py must import the canonical shared helper names, and every
    imported name must resolve to the real object in tests.shared.kde_preconditions
    (no guarded imports, no invented names such as ensure_kde_session)."""
    mod = importlib.import_module("tests.kde-smoke.features.environment")
    # These are imported at module scope; verify they resolve to the real functions.
    from tests.shared.kde_preconditions import (
        apply_kde_session_preconditions,
        is_kde_image,
        is_kde_session,
    )

    assert mod.is_kde_session is is_kde_session
    assert mod.apply_kde_session_preconditions is apply_kde_session_preconditions
    assert mod.is_kde_image is is_kde_image


def test_environment_uses_correct_webdriver_module():
    """environment.py must import kde_webdriver with new_session (not start_driver)."""
    mod = importlib.import_module("tests.kde-smoke.features.environment")
    assert hasattr(mod.kde_webdriver, "new_session")
    assert not hasattr(mod.kde_webdriver, "start_driver")


# ---------------------------------------------------------------------------
# 4. Default SSH key resolution (no key configured by userdata or environment)
# ---------------------------------------------------------------------------


class TestDefaultSshKey:
    """_run_host now resolves context.ssh_key through ssh_argv(); the env-default
    key must stay usable in both the tmt-provisioned and the plain runner case."""

    @pytest.fixture(autouse=True)
    def _load_module(self):
        self.mod = importlib.import_module("tests.kde-smoke.features.environment")

    def test_prefers_tmt_key_when_present(self, monkeypatch):
        monkeypatch.setattr(self.mod.os.path, "exists", lambda path: True)
        assert self.mod._default_ssh_key() == "/etc/ssh/test-key/id_ed25519"

    def test_falls_back_to_runner_key_when_tmt_key_absent(self, monkeypatch):
        from tests.shared.ssh_config import DEFAULT_SSH_KEY

        monkeypatch.setattr(self.mod.os.path, "exists", lambda path: False)
        assert self.mod._default_ssh_key() == DEFAULT_SSH_KEY
        assert DEFAULT_SSH_KEY == "/home/bluefin-test/.ssh/id_ed25519"
