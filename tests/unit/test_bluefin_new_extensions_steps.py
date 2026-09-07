"""Unit tests for tests/smoke/features/steps/bluefin_new_extensions_steps.py.

The module runs against a live GNOME session over SSH/gdbus, so these tests
stub ``behave``, ``dogtail``, ``steps.gnome_extensions_steps`` and
``steps.steps`` and exercise only the pure/host-command-construction logic:
journal filtering, memory-bound math, gsettings key parsing, and the
soft-pass/hard-fail branching used throughout the module.
"""
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


def _import_module(tree_available: bool = True):
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules["behave"] = behave_stub

    dogtail_stub = types.ModuleType("dogtail")
    tree_stub = types.ModuleType("dogtail.tree")
    if tree_available:
        tree_stub.root = MagicMock()
    sys.modules["dogtail"] = dogtail_stub
    sys.modules["dogtail.tree"] = tree_stub

    # bluefin_new_extensions_steps does:
    #   from steps.gnome_extensions_steps import _extension_state, _run_host
    #   from steps.steps import _eval_bool, _shell_eval
    # `steps` is only on sys.path inside a behave run — stub the package and
    # both submodules so the imports resolve under plain pytest.
    steps_pkg_stub = types.ModuleType("steps")
    steps_pkg_stub.__path__ = []
    sys.modules["steps"] = steps_pkg_stub

    gnome_extensions_stub = types.ModuleType("steps.gnome_extensions_steps")
    gnome_extensions_stub._extension_state = MagicMock(return_value="1")
    gnome_extensions_stub._run_host = MagicMock(return_value=("", 0, ""))
    sys.modules["steps.gnome_extensions_steps"] = gnome_extensions_stub

    steps_mod_stub = types.ModuleType("steps.steps")
    steps_mod_stub._eval_bool = MagicMock(return_value=True)
    steps_mod_stub._shell_eval = MagicMock(return_value="(true, '')")
    sys.modules["steps.steps"] = steps_mod_stub

    for key in list(sys.modules):
        if "bluefin_new_extensions_steps" in key:
            del sys.modules[key]

    import tests.smoke.features.steps.bluefin_new_extensions_steps as m  # noqa: PLC0415
    return m


@pytest.fixture
def mod():
    return _import_module()


def _ctx(**attrs):
    ctx = MagicMock()
    for key, value in attrs.items():
        setattr(ctx, key, value)
    return ctx


# ---------------------------------------------------------------------------
# Extension uuid constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_seven_extension_uuids_defined(self, mod):
        uuids = {
            mod.COPYOUS_UUID,
            mod.SYNCTHING_TOGGLE_UUID,
            mod.BLUETOOTH_BATTERY_METER_UUID,
            mod.AUDIO_HIDER_UUID,
            mod.AUDIO_RENAMER_UUID,
            mod.TILING_ASSISTANT_UUID,
            mod.TAILSCALE_UUID,
        }
        assert len(uuids) == 7
        assert mod.COPYOUS_UUID == "copyous@boerdereinar.dev"


# ---------------------------------------------------------------------------
# Journal helpers
# ---------------------------------------------------------------------------

class TestJournalErrorsSince:
    def test_filters_to_gnome_shell_lines(self, mod):
        output = "gnome-shell[1]: crashed\nsomeotherdaemon[2]: unrelated error\n"
        with patch.object(mod, "_run_host", return_value=(output, 0, "")):
            errors = mod._journal_errors_since("2026-01-01 00:00:00")
        assert errors == ["gnome-shell[1]: crashed"]

    def test_extra_pattern_further_restricts_matches(self, mod):
        output = "gnome-shell[1]: extension copyous@boerdereinar.dev failed\ngnome-shell[2]: unrelated\n"
        with patch.object(mod, "_run_host", return_value=(output, 0, "")):
            errors = mod._journal_errors_since("marker", extra_pattern="copyous")
        assert len(errors) == 1
        assert "copyous" in errors[0]

    def test_raises_when_journalctl_fails(self, mod):
        with patch.object(mod, "_run_host", return_value=("", 1, "boom")):
            with pytest.raises(AssertionError, match="journalctl failed"):
                mod._journal_errors_since("marker")


class TestAssertNoNewShellErrors:
    def test_passes_when_no_errors(self, mod):
        with patch.object(mod, "_journal_errors_since", return_value=[]):
            mod._assert_no_new_shell_errors("marker")

    def test_raises_with_error_lines_in_message(self, mod):
        with patch.object(mod, "_journal_errors_since", return_value=["gnome-shell[1]: boom"]):
            with pytest.raises(AssertionError, match="boom"):
                mod._assert_no_new_shell_errors("marker")


class TestAssertNoShellCoredump:
    def test_soft_passes_when_coredumpctl_unavailable(self, mod, capsys):
        with patch.object(mod, "_run_host", return_value=("", 127, "not found")):
            mod._assert_no_shell_coredump()
        assert "coredumpctl not available" in capsys.readouterr().out

    def test_passes_when_no_matches(self, mod):
        with patch.object(mod, "_run_host", return_value=("No coredumps found.", 1, "")):
            mod._assert_no_shell_coredump()

    def test_raises_when_coredump_present(self, mod):
        with patch.object(mod, "_run_host", return_value=("TIME PID gnome-shell", 0, "")):
            with pytest.raises(AssertionError, match="coredump"):
                mod._assert_no_shell_coredump()


# ---------------------------------------------------------------------------
# Memory helpers
# ---------------------------------------------------------------------------

class TestGnomeShellRssKb:
    def test_sums_multiple_process_rss_values(self, mod):
        with patch.object(mod, "_run_host", return_value=("123456\n7890", 0, "")):
            assert mod._gnome_shell_rss_kb() == 131346

    def test_raises_when_no_process_found(self, mod):
        with patch.object(mod, "_run_host", return_value=("", 0, "")):
            with pytest.raises(AssertionError, match="No gnome-shell process"):
                mod._gnome_shell_rss_kb()

    def test_raises_when_ps_fails(self, mod):
        with patch.object(mod, "_run_host", return_value=("", 1, "err")):
            with pytest.raises(AssertionError, match="ps -C gnome-shell failed"):
                mod._gnome_shell_rss_kb()


class TestGnomeShellMemoryUsageRemainsBounded:
    def test_passes_within_bound(self, mod):
        context = _ctx(gnome_shell_rss_baseline_kb=100_000)
        with patch.object(mod, "_gnome_shell_rss_kb", return_value=120_000):
            mod.gnome_shell_memory_usage_remains_bounded(context)

    def test_raises_when_growth_exceeds_bound(self, mod):
        context = _ctx(gnome_shell_rss_baseline_kb=100_000)
        with patch.object(mod, "_gnome_shell_rss_kb", return_value=500_000):
            with pytest.raises(AssertionError, match="possible leak"):
                mod.gnome_shell_memory_usage_remains_bounded(context)

    def test_soft_passes_without_baseline(self, mod, capsys):
        context = MagicMock(spec=[])
        with patch.object(mod, "_gnome_shell_rss_kb", return_value=100_000):
            mod.gnome_shell_memory_usage_remains_bounded(context)
        assert "no baseline RSS captured" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# gsettings helpers
# ---------------------------------------------------------------------------

class TestExtensionGsettingsValue:
    def test_returns_value_and_schema_on_first_candidate_match(self, mod):
        with patch.object(mod, "_run_host", return_value=("uint32 0", 0, "")):
            value, schema = mod._extension_gsettings_value(
                "Bluetooth-Battery-Meter@maniacx.github.com", "level-indicator-color"
            )
        assert value == "uint32 0"
        assert schema == "org.gnome.shell.extensions.Bluetooth-Battery-Meter"

    def test_returns_none_when_no_schema_resolves(self, mod):
        with patch.object(mod, "_run_host", return_value=("", 1, "No such schema")):
            value, schema = mod._extension_gsettings_value(
                "copyous@boerdereinar.dev", "some-key"
            )
        assert value is None
        assert schema is None


class TestTheExtensionHonorsSetting:
    def test_soft_passes_when_schema_unresolvable(self, mod, capsys):
        context = _ctx()
        with patch.object(mod, "_extension_gsettings_value", return_value=(None, None)):
            mod.the_extension_honors_setting(context, "start-stop-only = true")
        assert "WARNING" in capsys.readouterr().out

    def test_passes_when_value_matches(self, mod):
        context = _ctx()
        with patch.object(
            mod, "_extension_gsettings_value",
            return_value=("true", "org.gnome.shell.extensions.syncthing-toggle"),
        ):
            mod.the_extension_honors_setting(context, "start-stop-only = true")

    def test_raises_when_value_differs(self, mod):
        context = _ctx()
        with patch.object(
            mod, "_extension_gsettings_value",
            return_value=("false", "org.gnome.shell.extensions.syncthing-toggle"),
        ):
            with pytest.raises(AssertionError, match="expected 'true'"):
                mod.the_extension_honors_setting(context, "start-stop-only = true")

    def test_rejects_unparsable_setting_expression(self, mod):
        context = _ctx()
        with pytest.raises(AssertionError, match="Could not parse"):
            mod.the_extension_honors_setting(context, "not a key value pair")


class TestSymbolicIndicatorColor:
    def test_strips_gvariant_type_prefix_before_comparing(self, mod):
        context = _ctx()
        with patch.object(
            mod, "_extension_gsettings_value",
            return_value=("uint32 0", "org.gnome.shell.extensions.Bluetooth-Battery-Meter"),
        ):
            mod.the_extension_uses_symbolic_indicator_color(context, "level-indicator-color = 0")

    def test_raises_when_value_mismatches(self, mod):
        context = _ctx()
        with patch.object(
            mod, "_extension_gsettings_value",
            return_value=("uint32 2", "org.gnome.shell.extensions.Bluetooth-Battery-Meter"),
        ):
            with pytest.raises(AssertionError, match="expected '0'"):
                mod.the_extension_uses_symbolic_indicator_color(context, "level-indicator-color = 0")


# ---------------------------------------------------------------------------
# systemd unit helper
# ---------------------------------------------------------------------------

class TestSystemdUnitStartStop:
    def test_unit_not_found_reports_unavailable(self, mod):
        with patch.object(mod, "_run_host", return_value=("LoadState=not-found", 0, "")):
            available, ok, _detail = mod._systemd_unit_start_stop("syncthing.service")
        assert available is False
        assert ok is False

    def test_available_unit_starts_and_stops_successfully(self, mod):
        responses = iter([
            ("LoadState=loaded", 0, ""),
            ("", 0, ""),
            ("", 0, ""),
        ])
        with patch.object(mod, "_run_host", side_effect=lambda *a, **kw: next(responses)), \
             patch.object(mod.time, "sleep"):
            available, ok, _detail = mod._systemd_unit_start_stop("syncthing.service")
        assert available is True
        assert ok is True

    def test_available_unit_reports_failure_detail(self, mod):
        responses = iter([
            ("LoadState=loaded", 0, ""),
            ("", 1, "start failed"),
            ("", 0, ""),
        ])
        with patch.object(mod, "_run_host", side_effect=lambda *a, **kw: next(responses)), \
             patch.object(mod.time, "sleep"):
            available, ok, detail = mod._systemd_unit_start_stop("syncthing.service")
        assert available is True
        assert ok is False
        assert detail == "start failed"


# ---------------------------------------------------------------------------
# Quick Settings text scan
# ---------------------------------------------------------------------------

class TestQuickSettingsContainsText:
    def test_returns_true_when_eval_bool_true(self, mod):
        with patch.object(mod, "_eval_bool", return_value=True) as eval_bool:
            assert mod._quick_settings_contains_text("Sync Folder") is True
        assert "Sync Folder" in eval_bool.call_args[0][0]

    def test_returns_false_when_eval_bool_raises(self, mod):
        with patch.object(mod, "_eval_bool", side_effect=AssertionError("boom")):
            assert mod._quick_settings_contains_text("Sync Folder") is False


class TestQuickSettingsContainsALabeledToggle:
    def test_passes_when_present(self, mod):
        context = _ctx()
        with patch.object(mod, "_quick_settings_contains_text", return_value=True):
            mod.quick_settings_contains_a_toggle_labeled(context, "Sync Folder")

    def test_raises_when_absent(self, mod):
        context = _ctx()
        with patch.object(mod, "_quick_settings_contains_text", return_value=False):
            with pytest.raises(AssertionError, match="Sync Folder"):
                mod.quick_settings_contains_a_toggle_labeled(context, "Sync Folder")


# ---------------------------------------------------------------------------
# Window snapping (Tiling Assistant) — headless soft-pass behavior
# ---------------------------------------------------------------------------

class TestWindowSnappingGesturesWork:
    def test_soft_passes_and_checks_extension_still_enabled(self, mod, capsys):
        context = _ctx()
        with patch.object(mod, "_wait_gnome_shell_accessible"), \
             patch.object(mod, "_extension_state", return_value="1"):
            mod.window_snapping_gestures_work(context)
        assert "cannot be synthesized" in capsys.readouterr().out

    def test_raises_when_extension_not_enabled(self, mod):
        context = _ctx()
        with patch.object(mod, "_wait_gnome_shell_accessible"), \
             patch.object(mod, "_extension_state", return_value="3"):
            with pytest.raises(AssertionError, match="not enabled"):
                mod.window_snapping_gestures_work(context)


class TestGnomeShellRemainsResponsiveWithoutShellErrors:
    def test_passes_when_shell_eval_and_journal_clean(self, mod):
        context = _ctx()
        with patch.object(mod, "_journal_snapshot_marker", return_value="marker"), \
             patch.object(mod, "_wait_gnome_shell_accessible"), \
             patch.object(mod, "_eval_bool", return_value=True), \
             patch.object(mod, "_assert_no_new_shell_errors") as assert_clean:
            mod.gnome_shell_remains_responsive_without_shell_errors(context)
        assert_clean.assert_called_once_with("marker")

    def test_raises_when_shell_eval_unresponsive(self, mod):
        context = _ctx()
        with patch.object(mod, "_journal_snapshot_marker", return_value="marker"), \
             patch.object(mod, "_wait_gnome_shell_accessible"), \
             patch.object(mod, "_eval_bool", return_value=False):
            with pytest.raises(AssertionError, match="unresponsive"):
                mod.gnome_shell_remains_responsive_without_shell_errors(context)


# ---------------------------------------------------------------------------
# _wait_gnome_shell_accessible
# ---------------------------------------------------------------------------

class TestWaitGnomeShellAccessible:
    def test_soft_passes_when_dogtail_unavailable(self, capsys):
        m = _import_module(tree_available=False)
        m.tree = None
        m._wait_gnome_shell_accessible()
        assert "dogtail unavailable" in capsys.readouterr().out

    def test_raises_after_timeout_when_shell_never_appears(self, mod):
        mod.tree.root.application.side_effect = Exception("not found")
        with patch.object(mod.time, "monotonic", side_effect=[0, 1, 99]), \
             patch.object(mod, "sleep"):
            with pytest.raises(AssertionError, match="not accessible via AT-SPI"):
                mod._wait_gnome_shell_accessible()

    def test_returns_when_shell_found(self, mod):
        mod.tree.root.application.return_value = MagicMock()
        mod._wait_gnome_shell_accessible()
