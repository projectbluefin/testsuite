"""Unit tests for tests/lifecycle/features/steps/steps.py.

Tests pure helper functions without importing the full behave SSH stack.
"""

import sys
import types
from unittest.mock import MagicMock, call

import pytest


# ---------------------------------------------------------------------------
# Import helper (avoids behave decorator side effects)
# ---------------------------------------------------------------------------

def _import_lifecycle_steps():
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules["behave"] = behave_stub

    ssh_stub = types.ModuleType("tests.shared.ssh_steps")
    ssh_stub.run_ssh = MagicMock()
    sys.modules["tests.shared.ssh_steps"] = ssh_stub

    if "tests.lifecycle.features.steps.steps" in sys.modules:
        del sys.modules["tests.lifecycle.features.steps.steps"]

    import tests.lifecycle.features.steps.steps as m
    return m


class TestParseBootcStatus:
    def setup_method(self):
        self.mod = _import_lifecycle_steps()

    def test_returns_status_dict_from_command_stdout(self):
        context = MagicMock(command_stdout='{"status": {"booted": {"pinned": true}}}')

        status = self.mod._parse_bootc_status(context)

        assert status == {"booted": {"pinned": True}}

    def test_raises_when_command_stdout_missing(self):
        context = MagicMock(command_stdout="")

        with pytest.raises(AssertionError, match="No bootc status output available"):
            self.mod._parse_bootc_status(context)

    def test_raises_on_invalid_json(self):
        context = MagicMock(command_stdout="not-json")

        with pytest.raises(AssertionError, match="Invalid bootc status JSON"):
            self.mod._parse_bootc_status(context)

    def test_raises_when_status_is_missing_or_not_a_dict(self):
        missing_status = MagicMock(command_stdout='{"booted": {}}')
        wrong_status_type = MagicMock(command_stdout='{"status": []}')

        with pytest.raises(AssertionError, match="missing 'status' dict"):
            self.mod._parse_bootc_status(missing_status)

        with pytest.raises(AssertionError, match="missing 'status' dict"):
            self.mod._parse_bootc_status(wrong_status_type)


class TestSkipCurrentScenario:
    def setup_method(self):
        self.mod = _import_lifecycle_steps()

    def test_calls_skip_with_reason_when_available(self):
        scenario = MagicMock()
        context = MagicMock(scenario=scenario)

        self.mod._skip_current_scenario(context, "skip me")

        scenario.skip.assert_called_once_with("skip me")

    def test_falls_back_to_skip_without_reason_on_type_error(self):
        scenario = MagicMock()
        scenario.skip.side_effect = [TypeError("legacy skip"), None]
        context = MagicMock(scenario=scenario)

        self.mod._skip_current_scenario(context, "skip me")

        assert scenario.skip.call_args_list == [call("skip me"), call()]

    def test_raises_when_context_has_no_scenario(self):
        context = MagicMock()
        context.scenario = None

        with pytest.raises(AssertionError, match="skip me"):
            self.mod._skip_current_scenario(context, "skip me")


class TestParseOsRelease:
    def setup_method(self):
        self.mod = _import_lifecycle_steps()

    def test_parses_basic_key_value_pairs(self):
        raw = "ID=fedora\nVERSION_ID=42\nNAME=Fedora Linux\n"

        data = self.mod._parse_os_release(raw)

        assert data == {
            "ID": "fedora",
            "VERSION_ID": "42",
            "NAME": "Fedora Linux",
        }

    def test_strips_quotes_and_skips_comments_empty_and_invalid_lines(self):
        raw = (
            '# comment\n'
            '\n'
            'PRETTY_NAME="Bluefin Linux"\n'
            'VARIANT_ID=bluefin\n'
            'not-a-key-value-line\n'
        )

        data = self.mod._parse_os_release(raw)

        assert data == {
            "PRETTY_NAME": "Bluefin Linux",
            "VARIANT_ID": "bluefin",
        }

    def test_splits_only_on_first_equals_sign(self):
        data = self.mod._parse_os_release("KEY=a=b\n")

        assert data == {"KEY": "a=b"}

    def test_raises_on_empty_input(self):
        with pytest.raises(AssertionError, match="No /etc/os-release output available"):
            self.mod._parse_os_release("")


class TestValidFedoraVersion:
    def setup_method(self):
        self.mod = _import_lifecycle_steps()

    @pytest.mark.parametrize("version", ["40", "41", "42"])
    def test_accepts_numeric_version_strings(self, version):
        assert self.mod._valid_fedora_version(version) is True

    @pytest.mark.parametrize("version", ["40.1", "rawhide", "", None, "40a", "abc"])
    def test_rejects_non_numeric_version_strings(self, version):
        assert self.mod._valid_fedora_version(version) is False


class TestIsDeploymentSettled:
    def setup_method(self):
        self.mod = _import_lifecycle_steps()

    def test_settled_with_booted_and_no_staged(self):
        raw = '{"status": {"booted": {"image": {"imageDigest": "sha256:abc"}}, "staged": null}}'
        settled, reason = self.mod._is_deployment_settled(raw)
        assert settled is True
        assert "deployment is settled" in reason

    def test_settled_with_booted_and_staged_omitted(self):
        raw = '{"status": {"booted": {"image": {"imageDigest": "sha256:abc"}}}}'
        settled, reason = self.mod._is_deployment_settled(raw)
        assert settled is True
        assert "deployment is settled" in reason

    def test_not_settled_when_staged_present(self):
        raw = '{"status": {"booted": {"image": {}}, "staged": {"image": {}}}}'
        settled, reason = self.mod._is_deployment_settled(raw)
        assert settled is False
        assert "staged deployment is present" in reason

    def test_not_settled_when_booted_missing(self):
        raw = '{"status": {"staged": null}}'
        settled, reason = self.mod._is_deployment_settled(raw)
        assert settled is False
        assert "missing or empty 'booted'" in reason

    def test_not_settled_when_booted_empty_dict(self):
        raw = '{"status": {"booted": {}}}'
        settled, reason = self.mod._is_deployment_settled(raw)
        assert settled is False
        assert "missing or empty 'booted'" in reason

    def test_not_settled_when_status_missing(self):
        raw = '{"booted": {"image": {}}}'
        settled, reason = self.mod._is_deployment_settled(raw)
        assert settled is False
        assert "missing 'status' dict" in reason

    def test_not_settled_when_status_not_a_dict(self):
        raw = '{"status": "ready"}'
        settled, reason = self.mod._is_deployment_settled(raw)
        assert settled is False
        assert "missing 'status' dict" in reason

    def test_not_settled_when_top_level_not_a_dict(self):
        raw = '["status"]'
        settled, reason = self.mod._is_deployment_settled(raw)
        assert settled is False
        assert "top-level JSON is list" in reason

    def test_not_settled_when_invalid_json(self):
        settled, reason = self.mod._is_deployment_settled("not-json")
        assert settled is False
        assert "invalid bootc status JSON" in reason

    def test_not_settled_when_empty_or_whitespace(self):
        settled, reason = self.mod._is_deployment_settled("")
        assert settled is False
        assert "output was empty" in reason

        settled, reason = self.mod._is_deployment_settled("   \n\t")
        assert settled is False
        assert "output was empty" in reason


class TestDeploymentIsSettled:
    def setup_method(self):
        self.mod = _import_lifecycle_steps()

    def test_settles_immediately_when_valid(self, monkeypatch):
        context = MagicMock()
        valid_json = '{"status": {"booted": {"image": "ref"}, "staged": null}}'
        self.mod.run_ssh.return_value = (valid_json, 0)
        sleep_mock = MagicMock()
        monkeypatch.setattr(self.mod, "sleep", sleep_mock)

        self.mod.deployment_is_settled(context, timeout=60)

        self.mod.run_ssh.assert_called_once_with(
            context, "sudo bootc status --format=json", timeout=15
        )
        sleep_mock.assert_not_called()

    def test_retries_and_succeeds_after_transient_states(self, monkeypatch):
        context = MagicMock()
        staged_json = '{"status": {"booted": {"image": "ref"}, "staged": {"image": "new"}}}'
        settled_json = '{"status": {"booted": {"image": "ref"}, "staged": null}}'
        self.mod.run_ssh.side_effect = [
            ("error: locked", 1),
            (staged_json, 0),
            (settled_json, 0),
        ]
        sleep_mock = MagicMock()
        monkeypatch.setattr(self.mod, "sleep", sleep_mock)

        self.mod.deployment_is_settled(context, timeout=60)

        assert self.mod.run_ssh.call_count == 3
        assert sleep_mock.call_count == 2

    def test_raises_assertion_error_on_deadline_expiration(self, monkeypatch):
        import subprocess

        context = MagicMock()
        self.mod.run_ssh.side_effect = subprocess.TimeoutExpired(cmd="ssh", timeout=15)
        sleep_mock = MagicMock()
        monkeypatch.setattr(self.mod, "sleep", sleep_mock)

        # Mock time progression to trigger deadline expiration
        times = [100.0, 105.0, 115.0]
        monkeypatch.setattr(self.mod, "time", lambda: times.pop(0) if times else 200.0)

        with pytest.raises(AssertionError, match="Deployment did not settle within 10s"):
            self.mod.deployment_is_settled(context, timeout=10)

    def test_deployment_is_settled_with_timeout(self, monkeypatch):
        context = MagicMock()
        valid_json = '{"status": {"booted": {"image": "ref"}}}'
        self.mod.run_ssh.return_value = (valid_json, 0)
        monkeypatch.setattr(self.mod, "sleep", MagicMock())

        self.mod.deployment_is_settled_with_timeout(context, timeout=45)

        self.mod.run_ssh.assert_called_once_with(
            context, "sudo bootc status --format=json", timeout=15
        )

