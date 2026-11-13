"""Unit tests for tests/lifecycle/features/steps/update_failure_steps.py.

Covers the module's own ``_parse_bootc_status`` / ``_skip`` helpers, the
rollback-digest assertion, the forced rollback + reboot wait loop, and the
four @pending greenboot / corrupted-digest stubs. ``behave`` and
``tests.shared.ssh_steps`` are stubbed so no SSH transport is imported.
"""
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


def _import_update_failure_steps():
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules["behave"] = behave_stub

    ssh_stub = types.ModuleType("tests.shared.ssh_steps")
    ssh_stub.run_ssh = MagicMock()
    sys.modules["tests.shared.ssh_steps"] = ssh_stub

    sys.modules.pop("tests.lifecycle.features.steps.update_failure_steps", None)

    import tests.lifecycle.features.steps.update_failure_steps as m  # noqa: PLC0415
    return m


@pytest.fixture
def mod():
    return _import_update_failure_steps()


class TestParseBootcStatus:
    def test_unwraps_status_key(self, mod):
        context = MagicMock(command_stdout='{"status": {"rollback": null}}')

        assert mod._parse_bootc_status(context) == {"rollback": None}

    def test_falls_back_to_top_level_document(self, mod):
        context = MagicMock(command_stdout='{"rollback": {"a": 1}}')

        assert mod._parse_bootc_status(context) == {"rollback": {"a": 1}}

    def test_raises_when_stdout_empty(self, mod):
        with pytest.raises(AssertionError, match="No bootc status output"):
            mod._parse_bootc_status(MagicMock(command_stdout=""))

    def test_raises_on_invalid_json(self, mod):
        with pytest.raises(AssertionError, match="not valid JSON"):
            mod._parse_bootc_status(MagicMock(command_stdout="not json"))


class TestSkip:
    def test_calls_scenario_skip_with_reason(self, mod):
        context = MagicMock()

        mod._skip(context, "because")

        context.scenario.skip.assert_called_once_with("because")

    def test_retries_without_reason_when_signature_rejects_it(self, mod):
        scenario = MagicMock()
        scenario.skip.side_effect = [TypeError, None]
        context = MagicMock(scenario=scenario)

        mod._skip(context, "because")

        assert scenario.skip.call_count == 2
        assert scenario.skip.call_args[0] == ()

    def test_is_a_noop_when_no_scenario_attached(self, mod):
        context = types.SimpleNamespace(scenario=None)

        mod._skip(context, "because")


class TestBootcRollbackMatchesOriginal:
    def test_skips_when_original_digest_missing(self, mod):
        context = MagicMock()
        context.original_digest = None

        with patch.object(mod, "_skip") as skip:
            mod.bootc_rollback_matches_original(context)

        skip.assert_called_once()
        assert "original_digest not set" in skip.call_args[0][1]

    def test_passes_when_nested_image_digest_matches(self, mod):
        context = MagicMock()
        context.original_digest = "sha256:abc"
        context.command_stdout = (
            '{"status": {"rollback": {"image": {"imageDigest": "sha256:abc"}}}}'
        )

        mod.bootc_rollback_matches_original(context)

    def test_passes_when_flat_image_digest_matches(self, mod):
        context = MagicMock()
        context.original_digest = "sha256:abc"
        context.command_stdout = '{"status": {"rollback": {"imageDigest": "sha256:abc"}}}'

        mod.bootc_rollback_matches_original(context)

    def test_fails_when_rollback_deployment_absent(self, mod):
        context = MagicMock()
        context.original_digest = "sha256:abc"
        context.command_stdout = '{"status": {"rollback": null}}'

        with pytest.raises(AssertionError, match="no rollback deployment"):
            mod.bootc_rollback_matches_original(context)

    def test_fails_when_digest_differs(self, mod):
        context = MagicMock()
        context.original_digest = "sha256:abc"
        context.command_stdout = '{"status": {"rollback": {"imageDigest": "sha256:def"}}}'

        with pytest.raises(AssertionError, match="!= "):
            mod.bootc_rollback_matches_original(context)

    def test_fails_when_digest_key_missing_entirely(self, mod):
        context = MagicMock()
        context.original_digest = "sha256:abc"
        context.command_stdout = '{"status": {"rollback": {"image": {}}}}'

        with pytest.raises(AssertionError, match="!= "):
            mod.bootc_rollback_matches_original(context)


class TestForceBootcRollbackAndReboot:
    """run_ssh returns (stdout, rc) and sets no context.command_returncode;
    the step used to read that attribute and failed on a successful rollback
    (run 43506113077)."""

    def test_returns_once_ssh_comes_back(self, mod):
        context = MagicMock(spec=[])

        with (
            patch.object(mod, "run_ssh", return_value=("Next boot: rollback deployment", 0)) as run_ssh,
            patch.object(mod.time, "sleep"),
        ):
            mod.force_bootc_rollback_and_reboot(context)

        commands = [c[0][1] for c in run_ssh.call_args_list]
        assert commands[:2] == ["sudo bootc rollback", "sudo systemctl reboot"]
        assert commands[-1] == "true"

    def test_fails_when_rollback_command_errors(self, mod):
        with (
            patch.object(mod, "run_ssh", return_value=("denied", 1)),
            patch.object(mod.time, "sleep"),
        ):
            with pytest.raises(AssertionError, match="bootc rollback exited 1"):
                mod.force_bootc_rollback_and_reboot(MagicMock(spec=[]))

    def test_tolerates_reboot_disconnect(self, mod):
        def side_effect(_context, cmd, timeout=60):
            if cmd == "sudo systemctl reboot":
                raise OSError("connection closed")
            return "", 0

        with (
            patch.object(mod, "run_ssh", side_effect=side_effect),
            patch.object(mod.time, "sleep"),
        ):
            mod.force_bootc_rollback_and_reboot(MagicMock(spec=[]))

    def test_raises_when_vm_never_returns(self, mod):
        # rollback succeeds, every later probe fails
        returncodes = iter([0] + [1] * 200)

        def side_effect(_context, cmd, timeout=60):
            return "", next(returncodes, 1)

        with (
            patch.object(mod, "run_ssh", side_effect=side_effect),
            patch.object(mod.time, "sleep"),
            patch.object(mod.time, "time", side_effect=[0, 1, 2, 10_000]),
        ):
            with pytest.raises(AssertionError, match="did not come back"):
                mod.force_bootc_rollback_and_reboot(MagicMock(spec=[]))

    def test_waits_as_long_as_the_suite_reboot_deadline(self, mod):
        assert mod.FORCED_ROLLBACK_REBOOT_DEADLINE_S == 300


class TestPendingStubs:
    @pytest.mark.parametrize(
        "func_name,expected",
        [
            ("plant_failing_greenboot_check", "greenboot is masked"),
            ("wait_greenboot_rollback", "greenboot is masked"),
            ("remove_planted_greenboot_check", "greenboot is masked"),
            ("stage_corrupted_image_digest", "corrupted-digest registry mirror"),
        ],
    )
    def test_stub_skips_unconditionally(self, mod, func_name, expected):
        context = MagicMock()

        getattr(mod, func_name)(context)

        context.scenario.skip.assert_called_once()
        assert expected in context.scenario.skip.call_args[0][0]
