"""Unit tests for tests/common features step and environment helpers."""
import sys
import types
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Import helper
# ---------------------------------------------------------------------------

def _import_common_steps():
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules["behave"] = behave_stub

    ssh_steps_stub = types.ModuleType("tests.shared.ssh_steps")
    ssh_steps_stub.run_ssh = lambda *a, **kw: ("", 0)
    _ensure_tests_shared_package()
    sys.modules["tests.shared.ssh_steps"] = ssh_steps_stub

    for key in list(sys.modules):
        if "common.features.steps.steps" in key:
            del sys.modules[key]

    import tests.common.features.steps.steps as m  # noqa: PLC0415
    return m


def _ctx(**attrs):
    ctx = MagicMock()
    for k, v in attrs.items():
        setattr(ctx, k, v)
    return ctx


_ENVIRONMENT_STUB_KEYS = [
    "tests.shared.ssh_steps",
    "tests.shared.quarantine",
    "tests.shared.timing",
]


def _ensure_tests_shared_package():
    """Make sure `tests.shared` in sys.modules is the real package.

    `before_scenario` imports `tests.shared.quarantine` lazily, at call time
    rather than at module import. If `tests.shared` has been replaced by a
    plain `ModuleType` it carries no `__path__`, so that submodule import
    raises `ModuleNotFoundError: 'tests.shared' is not a package` — but only
    when this file runs in isolation, since a real import elsewhere in the
    suite otherwise leaves the genuine package cached.
    """
    cached = sys.modules.get("tests.shared")
    if cached is not None and not hasattr(cached, "__path__"):
        # A previous helper installed a non-package stub; drop it so the
        # import below resolves the real package from disk.
        del sys.modules["tests.shared"]

    import tests.shared  # noqa: PLC0415

    sys.modules["tests.shared"] = tests.shared

def _import_common_environment(*, run_ssh_returncode=0):
    ssh_steps_stub = types.ModuleType("tests.shared.ssh_steps")

    def _run_ssh(context, cmd, timeout=60):
        context.command_stdout = ""
        context.last_command_output = ""
        context.ssh_rc = run_ssh_returncode
        context.last_ssh_result = None
        return "", run_ssh_returncode

    ssh_steps_stub.run_ssh = _run_ssh

    # Save originals before overwriting — restored in teardown via the sentinel
    # dict stored on the returned module so callers can clean up.
    _saved = {k: sys.modules.get(k) for k in _ENVIRONMENT_STUB_KEYS}

    _ensure_tests_shared_package()
    sys.modules["tests.shared.ssh_steps"] = ssh_steps_stub

    quarantine_stub = types.ModuleType("tests.shared.quarantine")
    quarantine_stub.skip_quarantine = lambda scenario: False
    sys.modules["tests.shared.quarantine"] = quarantine_stub

    timing_stub = types.ModuleType("tests.shared.timing")
    timing_stub.record_start = lambda context: None
    timing_stub.record_end = lambda context, scenario: None
    sys.modules["tests.shared.timing"] = timing_stub

    for key in list(sys.modules):
        if key.endswith("common.features.environment"):
            del sys.modules[key]

    import tests.common.features.environment as m  # noqa: PLC0415

    # Restore sys.modules so the stub does not shadow the real timing module
    # for subsequent test files (e.g. test_timing.py).
    for k, v in _saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v

    return m


class _Scenario:
    def __init__(self, tags, name=""):
        self.tags = list(tags)
        self.effective_tags = list(tags)
        self.name = name
        self.skip_message = None

    def skip(self, message=None):
        self.skip_message = message


# ---------------------------------------------------------------------------
# last_command_exits_with_non_zero_status
# ---------------------------------------------------------------------------

class TestLastCommandExitsWithNonZeroStatus:
    def test_passes_when_rc_is_nonzero(self):
        m = _import_common_steps()
        ctx = _ctx(ssh_rc=1, last_ssh_result=None)
        m.last_command_exits_with_non_zero_status(ctx)  # should not raise

    def test_passes_when_rc_is_large_nonzero(self):
        m = _import_common_steps()
        ctx = _ctx(ssh_rc=127, last_ssh_result=None)
        m.last_command_exits_with_non_zero_status(ctx)  # should not raise

    def test_raises_when_rc_is_zero(self):
        m = _import_common_steps()
        ctx = _ctx(ssh_rc=0, last_ssh_result=None)
        with pytest.raises(AssertionError, match="non-zero"):
            m.last_command_exits_with_non_zero_status(ctx)

    def test_raises_when_rc_is_none(self):
        m = _import_common_steps()
        ctx = _ctx(ssh_rc=None, last_ssh_result=None)
        with pytest.raises(AssertionError):
            m.last_command_exits_with_non_zero_status(ctx)

    def test_raises_when_ssh_rc_missing(self):
        m = _import_common_steps()
        ctx = MagicMock(spec=[])  # no attributes at all
        with pytest.raises(AssertionError):
            m.last_command_exits_with_non_zero_status(ctx)

    def test_includes_stdout_in_error_message(self):
        m = _import_common_steps()
        last_result = MagicMock()
        last_result.stderr = ""
        last_result.stdout = "unexpected success output"
        ctx = _ctx(ssh_rc=0, last_ssh_result=last_result)
        with pytest.raises(AssertionError, match="unexpected success output"):
            m.last_command_exits_with_non_zero_status(ctx)

    def test_includes_stderr_in_error_message(self):
        m = _import_common_steps()
        last_result = MagicMock()
        last_result.stderr = "something went wrong but rc=0"
        last_result.stdout = ""
        ctx = _ctx(ssh_rc=0, last_ssh_result=last_result)
        with pytest.raises(AssertionError, match="something went wrong"):
            m.last_command_exits_with_non_zero_status(ctx)


class TestCommonEnvironmentRequiresBrew:
    def test_skips_requires_brew_when_brew_is_missing(self):
        m = _import_common_environment(run_ssh_returncode=1)
        context = _ctx(is_bluefin_image=True, has_brew=None)
        scenario = _Scenario(["requires_brew"])

        m.before_scenario(context, scenario)

        assert scenario.skip_message == "Homebrew not present on this image"
        assert context.has_brew is False

    def test_allows_requires_brew_when_brew_is_present(self):
        m = _import_common_environment(run_ssh_returncode=0)
        context = _ctx(is_bluefin_image=True, has_brew=None)
        scenario = _Scenario(["requires_brew"])

        m.before_scenario(context, scenario)

        assert scenario.skip_message is None
        assert context.has_brew is True


# ---------------------------------------------------------------------------
# _is_dakota_image / @dakota_only gating
# ---------------------------------------------------------------------------

class TestIsDakotaImage:
    @pytest.mark.parametrize(
        "image",
        [
            "ghcr.io/projectbluefin/dakota:testing",
            "ghcr.io/projectbluefin/dakota",
            "DAKOTA:latest",
            "ghcr.io/projectbluefin/dakota@sha256:abc123",
        ],
    )
    def test_matches_dakota_images(self, image):
        m = _import_common_environment()
        assert m._is_dakota_image(image) is True

    @pytest.mark.parametrize(
        "image",
        [
            "ghcr.io/projectbluefin/bluefin:testing",
            "ghcr.io/projectbluefin/bluefin-lts:latest",
            "ghcr.io/ublue-os/bazzite:stable",
            "",
        ],
    )
    def test_rejects_non_dakota_images(self, image):
        m = _import_common_environment()
        assert m._is_dakota_image(image) is False

    def test_org_name_alone_does_not_match(self):
        """Only the image name is inspected, so a dakota-named org cannot match."""
        m = _import_common_environment()
        assert m._is_dakota_image("ghcr.io/dakota/bluefin:testing") is False


class TestCommonEnvironmentDakotaOnly:
    def test_skips_dakota_only_on_non_dakota_image(self):
        m = _import_common_environment()
        context = _ctx(is_bluefin_image=True, is_dakota_image=False)
        scenario = _Scenario(["dakota_only"])

        m.before_scenario(context, scenario)

        assert "Skipping @dakota_only scenario" in scenario.skip_message

    def test_allows_dakota_only_on_dakota_image(self):
        m = _import_common_environment()
        context = _ctx(is_bluefin_image=True, is_dakota_image=True, has_brew=True)
        scenario = _Scenario(["dakota_only"])

        m.before_scenario(context, scenario)

        assert scenario.skip_message is None


class TestCommonEnvironmentRequiresBctl:
    def test_skips_requires_bctl_when_bctl_is_missing(self):
        m = _import_common_environment(run_ssh_returncode=1)
        context = _ctx(is_bluefin_image=True, has_brew=True, has_bctl=None)
        scenario = _Scenario(["requires_bctl"])

        m.before_scenario(context, scenario)

        assert scenario.skip_message == "bluefinctl (bctl) not present on this image"
        assert context.has_bctl is False

    def test_allows_requires_bctl_when_bctl_is_present(self):
        m = _import_common_environment(run_ssh_returncode=0)
        context = _ctx(is_bluefin_image=True, has_brew=True, has_bctl=None)
        scenario = _Scenario(["requires_bctl"])

        m.before_scenario(context, scenario)

        assert scenario.skip_message is None
        assert context.has_bctl is True


class TestCommonEnvironmentRequiresToggleAction:
    def test_skips_when_recipe_lacks_action_value(self):
        m = _import_common_environment(run_ssh_returncode=1)
        context = _ctx(is_bluefin_image=True, has_brew=True, has_toggle_action=None)
        scenario = _Scenario(["requires_toggle_action"])

        m.before_scenario(context, scenario)

        assert scenario.skip_message == "ujust toggle-updates ACTION support not present on this image"
        assert context.has_toggle_action is False

    def test_allows_when_recipe_has_action_value(self):
        m = _import_common_environment(run_ssh_returncode=0)
        context = _ctx(is_bluefin_image=True, has_brew=True, has_toggle_action=None)
        scenario = _Scenario(["requires_toggle_action"])

        m.before_scenario(context, scenario)

        assert scenario.skip_message is None
        assert context.has_toggle_action is True

    def test_probes_recipe_definition_directly(self):
        m = _import_common_environment(run_ssh_returncode=0)
        calls = []
        m.run_ssh = lambda context, cmd, **kw: (calls.append(cmd), ("", 0))[1]
        context = _ctx(has_toggle_action=None)

        result = m._has_toggle_action(context)

        assert result is True
        assert calls == ["ujust --show toggle-updates 2>/dev/null | grep -q 'ACTION_VALUE'"]


class TestCommonEnvironmentBootcUnifiedStorage:
    def test_restarts_service_when_result_is_not_success(self):
        m = _import_common_environment(run_ssh_returncode=0)
        calls = []

        def _fake_run_ssh(context, cmd, **kw):
            calls.append(cmd)
            if "Result --value" in cmd:
                return "signal\n", 0
            return "", 0

        m.run_ssh = _fake_run_ssh
        context = _ctx(is_bluefin_image=True, has_brew=True)
        scenario = _Scenario([], name="bootc unified storage service completed successfully")

        m.before_scenario(context, scenario)

        assert any("restart bootc-unified-storage.service" in c for c in calls)

    def test_does_not_restart_when_result_is_already_success(self):
        m = _import_common_environment(run_ssh_returncode=0)
        calls = []

        def _fake_run_ssh(context, cmd, **kw):
            calls.append(cmd)
            if "Result --value" in cmd:
                return "success\n", 0
            return "", 0

        m.run_ssh = _fake_run_ssh
        context = _ctx(is_bluefin_image=True, has_brew=True)
        scenario = _Scenario([], name="bootc unified storage service completed successfully")

        m.before_scenario(context, scenario)

        assert not any("restart bootc-unified-storage.service" in c for c in calls)


class TestCommonEnvironmentDevmodeCleanup:
    def test_disables_devmode_after_a_tagged_scenario(self):
        m = _import_common_environment(run_ssh_returncode=0)
        calls = []
        m.run_ssh = lambda context, cmd, **kw: (calls.append(cmd), ("", 0))[1]
        context = _ctx()
        scenario = _Scenario(["devmode_cleanup"])
        scenario.status = "passed"

        m.after_scenario(context, scenario)

        assert calls == ["bctl devmode --disable"]

    def test_skips_cleanup_for_untagged_scenarios(self):
        m = _import_common_environment(run_ssh_returncode=0)
        calls = []
        m.run_ssh = lambda context, cmd, **kw: (calls.append(cmd), ("", 0))[1]
        context = _ctx()
        scenario = _Scenario(["requires_bctl"])
        scenario.status = "passed"

        m.after_scenario(context, scenario)

        assert calls == []

    def test_skips_cleanup_when_scenario_was_skipped(self):
        m = _import_common_environment(run_ssh_returncode=0)
        calls = []
        m.run_ssh = lambda context, cmd, **kw: (calls.append(cmd), ("", 0))[1]
        context = _ctx()
        scenario = _Scenario(["devmode_cleanup"])
        scenario.status = "skipped"

        m.after_scenario(context, scenario)

        assert calls == []

    def test_cleanup_failure_does_not_mask_the_real_failure(self):
        m = _import_common_environment(run_ssh_returncode=0)

        def _boom(context, cmd, **kw):
            raise RuntimeError("ssh transport died")

        m.run_ssh = _boom
        context = _ctx()
        scenario = _Scenario(["devmode_cleanup"])
        scenario.status = "failed"

        m.after_scenario(context, scenario)  # should not raise


# ---------------------------------------------------------------------------
# Dakota ujust chooser / report mocks
# ---------------------------------------------------------------------------

def _captured_script(step_callable, *args):
    """Run a step with run_ssh stubbed and return the shell script it sent."""
    m = _import_common_steps()
    captured = {}

    def fake_run_ssh(context, command, **kwargs):
        captured["command"] = command
        return ("", 0)

    m.run_ssh = fake_run_ssh
    step_callable(m)(_ctx(), *args)
    return captured["command"]


def _extract_heredoc(script, marker):
    """Return the body of a ``<<'MARKER'`` heredoc embedded in a script."""
    start = script.index(f"<<'{marker}'\n") + len(f"<<'{marker}'\n")
    end = script.index(f"\n{marker}\n", start)
    return script[start:end]


class TestUjustChooseMockedFzf:
    def test_records_and_reports_fzf_invocation(self):
        script = _captured_script(
            lambda m: m.ujust_choose_mocked_fzf, "logs-this-boot"
        )
        assert "touch /tmp/fake-fzf-bin/invoked" in script
        assert "echo FZF_INVOKED=1" in script
        assert "echo FZF_INVOKED=0" in script

    def test_propagates_ujust_return_code(self):
        script = _captured_script(
            lambda m: m.ujust_choose_mocked_fzf, "logs-this-boot"
        )
        assert "ujust --choose || rc=$?" in script
        assert script.rstrip().endswith("exit $rc")

    def test_clears_stale_invocation_marker_first(self):
        script = _captured_script(
            lambda m: m.ujust_choose_mocked_fzf, "logs-this-boot"
        )
        assert script.index("rm -f /tmp/fake-fzf-bin/invoked") < script.index(
            "ujust --choose"
        )

    def test_quotes_the_recipe_name(self):
        script = _captured_script(lambda m: m.ujust_choose_mocked_fzf, "a b; rm -rf /")
        assert "'a b; rm -rf /'" in script


class TestUjustReportMocks:
    def _script(self):
        return _captured_script(lambda m: m.ujust_report_safe_mocks)

    def test_gum_choose_drives_the_real_prompts(self):
        script = self._script()
        assert 'echo "Skip"' not in script
        assert '"Update / boot"' in script
        assert '"Bug report"' in script
        assert '"No queue preference"' in script

    def test_reports_gist_and_issue_markers(self):
        script = self._script()
        assert "MOCK_GH_GIST_OK=1" in script
        assert "MOCK_GH_ISSUE_OK=1" in script

    def test_gh_is_only_ever_the_mock_on_path(self):
        """No real GitHub call can escape: gh is shadowed before ujust runs."""
        script = self._script()
        assert script.index('export PATH="$mock_dir:$PATH"') < script.index(
            "ujust report"
        )

    @pytest.mark.parametrize(
        "argv,expected_rc",
        [
            (["auth", "status"], 0),
            (["gist", "create", "--public", "--desc", "d", "FILE"], 0),
            (["gist", "list"], 1),
            (["gist", "create", "--public", "--desc", "d"], 1),
            (["gist", "create", "--public", "FILE"], 1),
            (["gist", "create", "--public", "--desc", "d", "missing.txt"], 1),
            (["issue", "create", "--title", "t"], 0),
            (["issue", "list"], 1),
            (["pr", "create"], 1),
        ],
    )
    def test_gh_mock_validates_the_invocation(self, tmp_path, argv, expected_rc):
        import subprocess  # noqa: PLC0415

        gh = tmp_path / "gh"
        gh.write_text(_extract_heredoc(self._script(), "GH_EOF"))
        gh.chmod(0o755)
        payload = tmp_path / "payload.md"
        payload.write_text("body\n")
        argv = [str(payload) if a == "FILE" else a for a in argv]

        result = subprocess.run(
            [str(gh), *argv],
            cwd=tmp_path,
            env={"MOCK_GH_LOG": str(tmp_path / "gh.log"), "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
        )
        assert result.returncode == expected_rc, result.stderr

    def test_gh_mock_logs_a_successful_gist_upload(self, tmp_path):
        import subprocess  # noqa: PLC0415

        gh = tmp_path / "gh"
        gh.write_text(_extract_heredoc(self._script(), "GH_EOF"))
        gh.chmod(0o755)
        payload = tmp_path / "payload.md"
        payload.write_text("body\n")
        log = tmp_path / "gh.log"

        result = subprocess.run(
            [str(gh), "gist", "create", "--public", "--desc", "d", str(payload)],
            cwd=tmp_path,
            env={"MOCK_GH_LOG": str(log), "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "gist.github.com" in result.stdout
        assert "MOCK_GH_GIST_OK=1" in log.read_text()
